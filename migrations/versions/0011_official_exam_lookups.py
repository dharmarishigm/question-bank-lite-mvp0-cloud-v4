"""Persist live official pattern lookup and evidence."""
from alembic import op
from database import translate_ddl
from official_exam_schema import SCHEMA

revision = '0011_official_exam_lookups'
down_revision = '0010_program_exams'
branch_labels = None
depends_on = None


def upgrade():
    for statement in translate_ddl(SCHEMA).split(';'):
        if statement.strip():
            op.execute(statement)


def downgrade():
    raise RuntimeError('Retain source evidence; roll back application traffic instead.')
