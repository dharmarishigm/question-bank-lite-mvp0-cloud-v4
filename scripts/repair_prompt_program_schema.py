"""Add missing feature tables, retaining the legacy marker for app rollback."""
import importlib
import os
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

engine = create_engine(os.environ['DATABASE_URL'])
with engine.begin() as conn:
    assert conn.execute(text('SELECT current_database()')).scalar() == 'question_bank'
    assert conn.execute(text('SELECT current_user')).scalar() != 'qb_production_runtime'
    conn.execute(text("SET LOCAL lock_timeout = '10s'"))
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('qb-production-feature-schema'))"))
    marker = conn.execute(text('SELECT version_num FROM alembic_version')).scalar()
    assert marker in ('0020_dqb_document_controls', '0022_security_sessions')
    with Operations.context(MigrationContext.configure(conn)):
        importlib.import_module('migrations.versions.0023_prompt_registry').upgrade()
        if not inspect(conn).has_table('program_enrollments'):
            importlib.import_module('migrations.versions.0024_program_enrollments').upgrade()
    for table in ('prompt_definitions','prompt_versions','prompt_run_bindings','prompt_audit','program_enrollments'):
        conn.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO qb_production_runtime'))
        sequence = conn.execute(text('SELECT pg_get_serial_sequence(:table, :column)'), {'table': table, 'column': 'id'}).scalar()
        assert sequence
        quoted = '.'.join('"'+s.replace('"','""')+'"' for s in sequence.split('.'))
        conn.execute(text(f'GRANT USAGE, SELECT ON SEQUENCE {quoted} TO qb_production_runtime'))
    assert conn.execute(text('SELECT version_num FROM alembic_version')).scalar() == marker
    assert conn.execute(text("SELECT COUNT(*) FROM prompt_versions WHERE status='ACTIVE'")).scalar() > 0
print('Feature tables seeded and runtime permissions verified; rollback marker preserved')
