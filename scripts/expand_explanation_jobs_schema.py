"""Privileged, additive queue expansion; preserve the existing rollback marker."""
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine,text
from database import translate_ddl
from explanation_jobs import SCHEMA


def main():
    engine=create_engine(os.environ['DATABASE_URL'])
    with engine.begin() as conn:
        if conn.execute(text('SELECT current_database()')).scalar()!='question_bank':raise RuntimeError('Unexpected database')
        if conn.execute(text('SELECT current_user')).scalar()=='qb_production_runtime':raise RuntimeError('Separate migration role required')
        conn.execute(text("SET LOCAL lock_timeout='10s'"))
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('qb-explanation-queue-schema'))"))
        marker=conn.execute(text('SELECT version_num FROM alembic_version')).scalar()
        if marker not in ('0020_dqb_document_controls','0022_security_sessions'):raise RuntimeError('Unexpected rollback marker')
        for statement in SCHEMA.split(';'):
            if statement.strip():conn.execute(text(translate_ddl(statement)))
        conn.execute(text('GRANT SELECT, INSERT, UPDATE, DELETE ON explanation_jobs TO qb_production_runtime'))
        sequence=conn.execute(text("SELECT pg_get_serial_sequence('explanation_jobs','id')")).scalar()
        if not sequence:raise RuntimeError('Missing queue sequence')
        quoted='.'.join('"'+part.replace('"','""')+'"' for part in sequence.split('.'))
        conn.execute(text(f'GRANT USAGE, SELECT ON SEQUENCE {quoted} TO qb_production_runtime'))
        if conn.execute(text('SELECT version_num FROM alembic_version')).scalar()!=marker:raise RuntimeError('Rollback marker changed')
    print('Explanation queue created, runtime grants verified, rollback marker unchanged')


if __name__=='__main__':main()
