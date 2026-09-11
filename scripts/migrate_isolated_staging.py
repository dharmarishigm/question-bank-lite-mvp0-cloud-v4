"""Controlled staging migration job. Rejects every production destination."""
import os,time
from urllib.parse import urlsplit,parse_qs
import psycopg
from alembic import command
from alembic.config import Config

url=os.environ['DATABASE_URL']
parts=urlsplit(url)
assert parts.path=='/security_staging'
assert parts.username=='qb_staging_migrator'
assert parse_qs(parts.query).get('host')==['/cloudsql/gen-lang-client-0491787004:asia-south1:qb-security-staging-20260911']
os.environ['QB_SCHEMA_MANAGED']='1'
with psycopg.connect(url.replace('postgresql+psycopg://','postgresql://',1),autocommit=True) as lock:
    assert lock.execute('SELECT current_database()').fetchone()[0]=='security_staging'
    assert lock.execute('SELECT pg_try_advisory_lock(82941722)').fetchone()[0], 'Another migration is running'
    try:
        command.upgrade(Config('alembic.ini'),'head')
        command.upgrade(Config('alembic.ini'),'head')
        lock.execute('REVOKE cloudsqlsuperuser FROM qb_staging_app')
        lock.execute('ALTER ROLE qb_staging_app NOCREATEDB NOCREATEROLE')
        assert lock.execute("SELECT NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole FROM pg_roles WHERE rolname='qb_staging_app'").fetchone()[0], 'Runtime role has privileged role attributes'
        lock.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
        lock.execute('GRANT USAGE ON SCHEMA public TO qb_staging_app')
        lock.execute('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO qb_staging_app')
        lock.execute('REVOKE ALL ON TABLE alembic_version FROM qb_staging_app')
        lock.execute('GRANT SELECT ON TABLE alembic_version TO qb_staging_app')
        lock.execute('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO qb_staging_app')
        now=time.time()
        lock.execute("INSERT INTO users(google_sub,email,email_verified,display_name,role,status,created_at,updated_at,last_login_at) SELECT 'staging-admin','security-admin@example.test',1,'Staging Administrator','ADMIN','ACTIVE',%s,%s,%s WHERE NOT EXISTS (SELECT 1 FROM users WHERE email='security-admin@example.test')",(now,now,now))
        print('Isolated staging migration complete; runtime granted DML only; synthetic Admin seeded.')
    finally:lock.execute('SELECT pg_advisory_unlock(82941722)')
