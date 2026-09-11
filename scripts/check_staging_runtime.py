"""Fail before serving if staging points at unexpected storage or a privileged DB."""
import os
from urllib.parse import urlsplit,parse_qs
import psycopg
url=os.environ['DATABASE_URL'];parts=urlsplit(url)
assert parts.username=='qb_staging_app' and parts.path=='/security_staging'
assert parse_qs(parts.query).get('host')==['/cloudsql/gen-lang-client-0491787004:asia-south1:qb-security-staging-20260911']
assert os.environ['GCS_DATA_BUCKET']=='gen-lang-client-0491787004-security-staging-20260911'
assert os.environ.get('QB_SCHEMA_MANAGED')=='1'
with psycopg.connect(url.replace('postgresql+psycopg://','postgresql://',1)) as conn:
    assert conn.execute('SELECT current_database(),current_user').fetchone()==('security_staging','qb_staging_app')
    assert not conn.execute("SELECT has_schema_privilege(current_user,'public','CREATE')").fetchone()[0]
    assert not conn.execute("SELECT has_table_privilege(current_user,'alembic_version','UPDATE')").fetchone()[0]
    assert conn.execute("SELECT to_regclass('security_mfa')").fetchone()[0]
print('Staging database identity and restricted privileges verified.')
