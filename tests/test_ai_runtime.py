import json
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import pytest

from ai_runtime import response_payload, response_metadata
from blueprint_gemini import Proposal, structured_call


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
