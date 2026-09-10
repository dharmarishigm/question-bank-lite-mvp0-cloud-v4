"""Add Programs and immutable generic blueprint payloads alongside legacy exams."""
from alembic import op
from blueprint_store import SCHEMA
from database import translate_ddl

revision = '0008_generic_blueprints'
down_revision = '0007_registration_identities'
branch_labels = None
depends_on = None


def upgrade():
    for statement in translate_ddl(SCHEMA).split(';'):
        if statement.strip():
            op.execute(statement)


def downgrade():
    raise RuntimeError('Blueprint history is retained. Roll back application traffic instead of deleting these tables.')
