"""Persist minimal-input Gemini program setup proposals and application results."""
from alembic import op
from database import translate_ddl
from program_setup_schema import SCHEMA

revision = '0009_program_setup'
down_revision = '0008_generic_blueprints'
branch_labels = None
depends_on = None


def upgrade():
    for statement in translate_ddl(SCHEMA).split(';'):
        if statement.strip():
            op.execute(statement)


def downgrade():
    raise RuntimeError('Retain setup history; roll back application traffic instead.')
