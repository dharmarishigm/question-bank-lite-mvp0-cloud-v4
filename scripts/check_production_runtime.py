"""Read-only startup gates for a production candidate. Never migrates or seeds."""
import os
from urllib.parse import urlsplit,parse_qs

def validate_environment(env):
    for key in ('QB_SCHEMA_MANAGED','SECURITY_HARDENING','REQUIRE_STAFF_MFA','DB_POOL_ENABLED'):
        if env.get(key)!='1':raise RuntimeError(key+' must be enabled')
    if env.get('APP_ENV')!='production':raise RuntimeError('Production environment required')
    for key in ('DATABASE_URL','EXPECTED_DB_NAME','EXPECTED_DB_USER','EXPECTED_CLOUDSQL_CONNECTION','GCS_DATA_BUCKET','EXPECTED_DATA_BUCKET','GOOGLE_CLIENT_ID','MFA_ENCRYPTION_KEY','APP_BASE_URL'):
        if not env.get(key):raise RuntimeError('Missing '+key)
    origin=urlsplit(env['APP_BASE_URL'])
    if origin.scheme!='https' or not origin.hostname or origin.path not in ('','/') or origin.query or origin.fragment:
        raise RuntimeError('APP_BASE_URL must be an HTTPS origin')
    db=urlsplit(env['DATABASE_URL'])
    if db.path!='/'+env['EXPECTED_DB_NAME'] or db.username!=env['EXPECTED_DB_USER']:
        raise RuntimeError('Unexpected database identity configuration')
    if parse_qs(db.query).get('host')!=['/cloudsql/'+env['EXPECTED_CLOUDSQL_CONNECTION']]:
        raise RuntimeError('Expected Cloud SQL socket required')
    if env['GCS_DATA_BUCKET']!=env['EXPECTED_DATA_BUCKET']:raise RuntimeError('Unexpected data bucket')
    if not 1<=int(env.get('DB_POOL_SIZE','0'))<=10:raise RuntimeError('Pool size outside reviewed range')
    from cryptography.fernet import Fernet
    Fernet(env['MFA_ENCRYPTION_KEY'].encode())

def main():
    validate_environment(os.environ)
    import psycopg
    with psycopg.connect(os.environ['DATABASE_URL'].replace('postgresql+psycopg://','postgresql://',1),connect_timeout=5) as conn:
        if conn.execute('SELECT current_database(),current_user').fetchone()!=(os.environ['EXPECTED_DB_NAME'],os.environ['EXPECTED_DB_USER']):raise RuntimeError('Actual database identity differs')
        if conn.execute("SELECT rolsuper OR rolcreatedb OR rolcreaterole FROM pg_roles WHERE rolname=current_user").fetchone()[0]:raise RuntimeError('Runtime role is privileged')
        if conn.execute("SELECT has_schema_privilege(current_user,'public','CREATE')").fetchone()[0]:raise RuntimeError('Runtime must not own schema creation')
        if conn.execute("SELECT has_table_privilege(current_user,'alembic_version','UPDATE')").fetchone()[0]:raise RuntimeError('Runtime must not migrate')
        expected=os.environ.get('EXPECTED_SCHEMA_REVISION','0020_dqb_document_controls')
        if expected not in {'0020_dqb_document_controls','0022_security_sessions'}:raise RuntimeError('Unreviewed schema version')
        if conn.execute('SELECT version_num FROM alembic_version').fetchone()!=(expected,):raise RuntimeError('Reviewed schema version required')
        required_tables = ('security_mfa','security_session_state','security_rate_limits','prompt_definitions','prompt_versions','prompt_run_bindings','prompt_audit','program_enrollments','explanation_jobs')
        for table in required_tables:
            if not conn.execute('SELECT to_regclass(%s)',(table,)).fetchone()[0]:
                raise RuntimeError('Missing required production table: '+table)
        # Resolve required security columns even in backward-compatible expansion mode.
        conn.execute('SELECT user_id,secret_ciphertext,enabled,last_counter FROM security_mfa LIMIT 0')
        conn.execute('SELECT token_hash,last_seen,mfa_at FROM security_session_state LIMIT 0')
        conn.execute('SELECT bucket,hits,expires_at FROM security_rate_limits LIMIT 0')
    print('Production runtime identity, schema and privilege checks passed')

if __name__=='__main__':main()
