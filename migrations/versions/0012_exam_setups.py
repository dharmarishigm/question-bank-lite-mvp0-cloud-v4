"""Persist editable guided exam defaults separately from generated papers."""
from alembic import op
from database import translate_ddl
from program_exam_schema import SETUP_SCHEMA
revision = '0012_exam_setups'
down_revision = '0011_official_exam_lookups'
branch_labels = None
depends_on = None

def upgrade():
    for statement in translate_ddl(SETUP_SCHEMA).split(';'):
        if statement.strip():
            op.execute(statement)

def downgrade():
    raise RuntimeError('Retain saved setups; roll back application traffic instead.')
