"""Add guided full and subject paper generation."""
from alembic import op
from database import translate_ddl
from program_exam_schema import SCHEMA

revision = '0010_program_exams'
down_revision = '0009_program_setup'
branch_labels = None
depends_on = None


def upgrade():
    for statement in translate_ddl(SCHEMA).split(';'):
        if statement.strip():
            op.execute(statement)


def downgrade():
    raise RuntimeError('Retain reviewed papers; roll back application traffic instead.')
