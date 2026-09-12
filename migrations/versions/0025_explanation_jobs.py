"""Durable scheduled bilingual explanation queue."""
from alembic import op
from database import translate_ddl
from explanation_jobs import SCHEMA

revision='0025_explanation_jobs'
down_revision='0024_program_enrollments'
branch_labels=None
depends_on=None


def upgrade():
    bind=op.get_bind()
    for statement in SCHEMA.split(';'):
        if statement.strip():
            bind.exec_driver_sql(translate_ddl(statement) if bind.dialect.name=='postgresql' else statement)


def downgrade():
    op.drop_table('explanation_jobs')
