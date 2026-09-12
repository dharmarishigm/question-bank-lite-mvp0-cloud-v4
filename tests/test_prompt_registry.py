import sqlite3
import pytest

from prompt_registry import SEEDS, bind_prompt, content_hash, init_prompt_registry, resolve_active_prompt
from prompt_registry import PromptNotConfigured
from prompt_registry import apply_system_rules,GENERATION_SCOPE_RULE,PROGRAM_SETUP_RULE,LATEX_SYSTEM_RULE


def test_runtime_rules_preserve_admin_content_and_are_idempotent():
    original='Administrator-specific style and examples.'
    effective=apply_system_rules(original,'QUESTION_GENERATE')
    assert effective.startswith(original)
    assert GENERATION_SCOPE_RULE in effective and LATEX_SYSTEM_RULE in effective
    assert apply_system_rules(effective,'QUESTION_GENERATE')==effective
    assert 'Different numbers' in effective and 'not mean easier questions' in effective
    assert 'official, current or complete unless supplied evidence' in effective


def test_setup_and_all_seed_prompts_preserve_math_and_source_evidence():
    for key,(_,_,content) in SEEDS.items():
        assert LATEX_SYSTEM_RULE in content,key
        assert 'Keep verbatim evidence_quote/source-quotation fields unchanged' in content,key
    setup=apply_system_rules('Legacy setup prompt','PROGRAM_SETUP')
    assert PROGRAM_SETUP_RULE in setup
    assert 'all applicable subjects and chapters' in setup
    assert 'separate scheduled job' in setup
    assert GENERATION_SCOPE_RULE not in apply_system_rules('Transcribe only','DIGITIZE_TRANSCRIBE')


def test_managed_runtime_never_initializes_missing_registry(monkeypatch):
    monkeypatch.setenv('QB_SCHEMA_MANAGED','1')
    conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
    with pytest.raises(PromptNotConfigured, match='migrations and permissions'):
        resolve_active_prompt('QUESTION_GENERATE',conn=conn)
    assert not conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()


def test_managed_runtime_only_reads_active_prompt(monkeypatch):
    conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
    init_prompt_registry(conn)
    monkeypatch.setenv('QB_SCHEMA_MANAGED','1')
    conn.execute('PRAGMA query_only=ON')
    assert resolve_active_prompt('QUESTION_GENERATE',conn=conn)['status']=='ACTIVE'


def test_registry_bootstraps_all_prompt_purposes_and_resolves_active_version():
    conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
    init_prompt_registry(conn)
    assert conn.execute('SELECT COUNT(*) FROM prompt_definitions').fetchone()[0] == len(SEEDS)
    resolved=resolve_active_prompt('DIGITIZE_TRANSCRIBE',conn=conn)
    assert resolved['status']=='ACTIVE' and resolved['content_hash']==content_hash(resolved['system_content'])


def test_prompt_binding_freezes_content_and_version():
    conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
    init_prompt_registry(conn)
    resolved=resolve_active_prompt('QUESTION_GENERATE',conn=conn)
    bind_prompt(conn,run_type='TEST',run_id='run-1',resolved=resolved,model='test-model')
    row=conn.execute('SELECT * FROM prompt_run_bindings WHERE run_id=?',('run-1',)).fetchone()
    assert row['prompt_version_id']==resolved['id']
    assert row['effective_prompt_snapshot']==resolved['system_content']
