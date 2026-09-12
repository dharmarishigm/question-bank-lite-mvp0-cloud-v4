import json
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import pytest

from ai_runtime import response_payload, response_metadata
from blueprint_gemini import Proposal, structured_call


def test_schema_complexity_falls_back_once_without_mutating_config():
    from google.genai import types
    from ai_runtime import generate_content
    error=RuntimeError('The specified schema produces a constraint that has too many states for serving')
    error.code=400
    config=types.GenerateContentConfig(system_instruction='Preserve LaTeX.',response_mime_type='application/json',response_schema={'type':'OBJECT','properties':{'answer':{'type':'STRING'}}},max_output_tokens=1000)
    client=Mock();client.models.generate_content.side_effect=[error,NS(text='{"answer":"ok"}')]
    assert generate_content(client,model='test',contents='question',config=config).text=='{"answer":"ok"}'
    fallback=client.models.generate_content.call_args.kwargs['config']
    assert fallback.response_schema is None
    assert fallback.response_mime_type=='application/json'
    assert 'answer' in fallback.system_instruction and 'Preserve LaTeX' in fallback.system_instruction
    assert config.response_schema is not None
    assert fallback.max_output_tokens==1000
    client.models.generate_content.side_effect=[error,error]
    with pytest.raises(RuntimeError):generate_content(client,model='test',contents='question',config=config)
    assert client.models.generate_content.call_count==4


def test_unrelated_400_is_never_retried():
    from ai_runtime import generate_content
    error=RuntimeError('INVALID_ARGUMENT: invalid model');error.code=400
    client=Mock();client.models.generate_content.side_effect=error
    with pytest.raises(RuntimeError):generate_content(client,model='test',config=None)
    assert client.models.generate_content.call_count==1


def test_serving_schema_removes_nested_bounds_but_local_validation_remains():
    from pydantic import BaseModel,Field,ValidationError
    from ai_runtime import serving_schema
    class Item(BaseModel):
        number:int=Field(ge=1,le=5)
    class Batch(BaseModel):
        items:list[Item]=Field(min_length=1,max_length=100)
    schema=serving_schema(Batch)
    assert 'maxItems' not in json.dumps(schema) and 'maximum' not in json.dumps(schema)
    with pytest.raises(ValidationError):Batch.model_validate({'items':[{'number':10}]})


def test_candidate_parts_exclude_thoughts_and_do_not_join_candidates():
    response=NS(candidates=[
        NS(content=NS(parts=[NS(text='private reasoning',thought=True),NS(text='{"patches":',thought=False)])),
        NS(content=NS(parts=[NS(text='{"patches":[],"warnings":[]}',thought=False)]))])
    assert response_payload(response)=={'patches':[],'warnings':[]}
    assert 'private reasoning' not in json.dumps(response_metadata(response))


def test_thought_only_response_does_not_fall_back_to_convenience_text():
    response=NS(text='{"secret":"reasoning"}',candidates=[NS(content=NS(parts=[NS(text='{"secret":"reasoning"}',thought=True)]))])
    with pytest.raises(ValueError):response_payload(response)


def test_parsed_and_fenced_responses_are_supported():
    assert response_payload(NS(parsed={'ok':True}))=={'ok':True}
    assert response_payload(NS(text='```json\n{"ok":true}\n```'))=={'ok':True}


def test_zero_retries_raises_instead_of_returning_none():
    client=Mock();client.models.generate_content.return_value=NS(text='{"patches":[')
    with patch.dict('os.environ',{'BLUEPRINT_GEMINI_MODEL':'gemini-2.5-flash','BLUEPRINT_MAX_RETRIES':'0'}),pytest.raises(ValueError):
        structured_call('BLUEPRINT_REFINEMENT','Review',{},Proposal,client)
    assert client.models.generate_content.call_count==1


def test_correction_has_one_attempt_and_enforces_latex_for_legacy_prompts():
    client=Mock();client.models.generate_content.return_value=NS(parsed={'patches':[],'warnings':[]},usage_metadata=None)
    prompt={'id':1,'content_hash':'legacy','system_content':'An old active prompt.'}
    with patch.dict('os.environ',{'BLUEPRINT_GEMINI_MODEL':'gemini-2.5-flash','BLUEPRINT_MAX_OUTPUT_TOKENS':'1000'}),patch('prompt_registry.resolve_active_prompt',return_value=prompt):
        _,metadata=structured_call('QUESTION_CORRECTION','Review',{},Proposal,client)
    config=client.models.generate_content.call_args.kwargs['config']
    assert 'Represent all equations' in config.system_instruction
    assert config.max_output_tokens>=6000
    assert config.thinking_config.thinking_budget==512
    assert metadata['attempts']==1 and metadata['effective_system_prompt_hash']!='legacy'


def test_safety_block_is_not_retried():
    client=Mock();client.models.generate_content.return_value=NS(candidates=[NS(finish_reason='SAFETY',content=None)])
    with patch.dict('os.environ',{'BLUEPRINT_GEMINI_MODEL':'gemini-2.5-flash','BLUEPRINT_MAX_RETRIES':'1'}),pytest.raises(ValueError):
        structured_call('BLUEPRINT_REFINEMENT','Review',{},Proposal,client)
    assert client.models.generate_content.call_count==1
