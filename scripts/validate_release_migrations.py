"""Run inside the release image against a disposable Cloud Build PostgreSQL DB."""
import os
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

url = os.environ['DATABASE_URL']
assert '@qb-migration-db:5432/qb_migration_test' in url, 'Disposable database required'
config = Config('alembic.ini')
engine = create_engine(url)
command.upgrade(config, '0018_grand_tests')
# Simulate a deployed 0018 installation whose library lacks the new columns.
with engine.begin() as conn:
    for table in ('program_document_audit', 'grand_test_page_status_audit', 'grand_test_page_status'):
        conn.execute(text(f'DROP TABLE IF EXISTS {table}'))
    for column in ('subject','chapter','available_for_digitisation','availability_changed_at','availability_changed_by','updated_at','updated_by'):
        conn.execute(text(f'ALTER TABLE program_documents DROP COLUMN IF EXISTS {column}'))
# Verify additive security expansion preserves the legacy rollback marker.
command.upgrade(config, '0020_dqb_document_controls')
from security_boundary import SCHEMA as QUOTAS
from security_mfa import SCHEMA as MFA
from database import translate_ddl
with engine.begin() as conn:
    for ddl in (QUOTAS+';'+MFA).split(';'):
        if ddl.strip():conn.execute(text(translate_ddl(ddl)))
    assert conn.execute(text('SELECT version_num FROM alembic_version')).scalar()=='0020_dqb_document_controls'
print('Security schema expansion preserves legacy Alembic marker')
command.upgrade(config, 'head')
command.upgrade(config, 'head')
with engine.connect() as conn:
    assert conn.execute(text('SELECT version_num FROM alembic_version')).scalar() == '0022_security_sessions'
    for table in ('program_document_audit','grand_test_page_status','grand_test_page_status_audit'):
        columns = {c['name']: c for c in inspect(conn).get_columns(table)}
        assert 'nextval' in columns['id']['default'], (table, columns['id'])
    assert 'available_for_digitisation' in {c['name'] for c in inspect(conn).get_columns('program_documents')}
print('PostgreSQL upgrade from legacy 0018 and repeated upgrade passed')
from security_boundary import reserve
from fastapi import HTTPException
reserve('cloud-build-disposable','validation',1,now=120)
try:
    reserve('cloud-build-disposable','validation',1,now=120)
except HTTPException as exc:
    assert exc.status_code==429
else:
    raise AssertionError('PostgreSQL security quota did not reject excess request')
reserve('cloud-build-disposable','validation',1,now=180)
print('PostgreSQL security quota increment, rejection and reset passed')

os.environ["DB_POOL_ENABLED"]="1"
from database import connect
for _ in range(8):
    c=connect("")
    assert c.execute("SELECT 1 AS n").fetchone()["n"]==1
    c.close()
print("Bounded PostgreSQL pool checkout/reuse passed")
