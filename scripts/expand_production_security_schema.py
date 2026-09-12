"""Apply the reviewed additive security tables to the production database.

Run this once with a separately privileged migration connection (never the
Cloud Run runtime role). It deliberately leaves alembic_version unchanged so
the existing production rollback marker remains valid.
"""
import os
from urllib.parse import urlsplit

import psycopg

from database import translate_ddl
from security_boundary import SCHEMA as RATE_LIMIT_SCHEMA
from security_mfa import SCHEMA as MFA_SCHEMA


def main():
    url = os.environ.get("DATABASE_URL", "").replace("postgresql+psycopg://", "postgresql://", 1)
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    parsed = urlsplit(url)
    expected_db = os.environ.get("EXPECTED_DB_NAME", "question_bank")
    runtime_user = os.environ.get("EXPECTED_DB_USER", "qb_production_runtime")
    migrator_user = parsed.username or ""
    if parsed.path != "/" + expected_db:
        raise RuntimeError("Refusing unexpected database")
    if not migrator_user or migrator_user == runtime_user:
        raise RuntimeError("Use a separate privileged migration role")
    with psycopg.connect(url, connect_timeout=10) as conn:
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('qb-production-security-schema'))")
            marker = conn.execute("SELECT version_num FROM alembic_version").fetchone()
            if not marker or marker[0] not in {"0020_dqb_document_controls", "0022_security_sessions"}:
                raise RuntimeError("Unexpected alembic schema marker")
            for ddl in (RATE_LIMIT_SCHEMA, MFA_SCHEMA):
                for statement in translate_ddl(ddl).split(";"):
                    if statement.strip():
                        conn.execute(statement)
            for table in ("security_mfa", "security_session_state", "security_rate_limits"):
                if not conn.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0]:
                    raise RuntimeError("Schema verification failed: " + table)
    print("Production security schema expanded; alembic marker preserved")


if __name__ == "__main__":
    main()
