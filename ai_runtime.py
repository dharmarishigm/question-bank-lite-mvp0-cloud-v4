"""Shared response decoding and bounded model settings for Vertex workflows."""
import json
import re
import time
import logging

from pydantic import BaseModel


def _get(value, key, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def response_metadata(response):
    """Diagnostic metadata only: never log input, output, or thought text."""
    usage = _get(response, 'usage_metadata')
    feedback = _get(response, 'prompt_feedback')
    return {
        'finish_reasons': [str(_get(c, 'finish_reason', '')) for c in _get(response, 'candidates', []) or []],
        'block_reason': str(_get(feedback, 'block_reason', '') or ''),
        'prompt_tokens': _get(usage, 'prompt_token_count', 0) or 0,
        'output_tokens': _get(usage, 'candidates_token_count', 0) or 0,
        'thought_tokens': _get(usage, 'thoughts_token_count', 0) or 0,
    }


def response_payload(response):
    parsed = _get(response, 'parsed')
    if parsed is not None:
        return parsed.model_dump() if isinstance(parsed, BaseModel) else parsed
    texts = []
    has_parts = False
    for candidate in _get(response, 'candidates', []) or []:
        parts = _get(_get(candidate, 'content'), 'parts', []) or []
        has_parts = has_parts or bool(parts)
        text = ''.join(str(_get(p, 'text', '') or '') for p in parts if not _get(p, 'thought', False)).strip()
        if text:
            texts.append(text)
    if not texts and not has_parts:
        text = (_get(response, 'text', '') or '').strip()
        if text:
            texts.append(text)
    for text in texts:
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.I).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            continue
    details = response_metadata(response)
    reason = ','.join(details['finish_reasons']) or details['block_reason'] or 'unknown'
    raise ValueError(f'Gemini returned no complete JSON response (finish={reason})')


def thinking_config(model, budget=1024):
    from google.genai import types
    name = model.lower()
    if 'gemini-2.5' in name:
        return types.ThinkingConfig(thinking_budget=max(128 if 'pro' in name else 0, budget), include_thoughts=False)
    if 'gemini-3' in name:
        return types.ThinkingConfig(thinking_level='LOW', include_thoughts=False)
    return None


def is_retryable(exc):
    if isinstance(exc, (TimeoutError, ConnectionError, ValueError)):
        return True
    import httpx
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    return getattr(exc, 'code', None) in {429, 500, 502, 503, 504}


def serving_schema(schema):
    """Simplify provider grammar; enforce full constraints after decoding."""
    source = schema.model_json_schema()
    definitions = source.get('$defs', {})
    omitted = {'$defs','title','default','minLength','maxLength','minItems','maxItems',
               'minimum','maximum','exclusiveMinimum','exclusiveMaximum','pattern','additionalProperties',
               'format','multipleOf','minProperties','maxProperties','uniqueItems','description','examples'}
    def simplify(value):
        if isinstance(value, list):
            return [simplify(item) for item in value]
        if not isinstance(value, dict):
            return value
        if '$ref' in value:
            return simplify(definitions[value['$ref'].split('/')[-1]])
        return {key: ({name: simplify(field) for name, field in item.items()} if key == 'properties' else simplify(item))
                for key, item in value.items() if key not in omitted}
    return simplify(source)


def generate_content(client, **kwargs):
    """Retry only a rejected serving grammar once, retaining JSON + local validation.

    A schema rejection occurs before inference. Other 400 errors must propagate;
    silently retrying them would hide configuration or input errors.
    """
    started=time.monotonic()
    try:
        return client.models.generate_content(**kwargs)
    except Exception as exc:
        message=str(exc).lower()
        if str(getattr(exc,'code',''))!='400' or not (
            'too many states for serving' in message or
            ('schema' in message and 'constraint' in message and 'too many states' in message)
        ):
            raise
        config=kwargs.get('config')
        schema=getattr(config,'response_schema',None)
        if schema is None:raise
        if hasattr(schema,'model_dump'):schema=schema.model_dump(exclude_none=True)
        contract=json.dumps(schema,ensure_ascii=False,default=str,separators=(',',':'))
        fallback=config.model_copy(update={
            'response_schema':None,
            'response_mime_type':'application/json',
            'system_instruction':str(config.system_instruction or '')+'\nReturn one complete JSON value matching this output contract. No Markdown fences. Constraints are validated by the application:\n'+contract,
        })
        http_options=getattr(config,'http_options',None)
        timeout=getattr(http_options,'timeout',None)
        if timeout:
            remaining=int(timeout-(time.monotonic()-started)*1000)
            if remaining<=0:raise TimeoutError('AI request deadline reached during schema validation') from exc
            fallback.http_options=http_options.model_copy(update={'timeout':remaining})
        logging.getLogger(__name__).warning('Gemini rejected serving schema complexity; using one JSON-contract fallback')
        # No recursive fallback and no retry of unrelated INVALID_ARGUMENT errors.
        return client.models.generate_content(**{**kwargs,'config':fallback})
