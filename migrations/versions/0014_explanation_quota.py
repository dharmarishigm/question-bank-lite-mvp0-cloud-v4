"""Persist student explanation quotas across instances."""
from alembic import op
from database import translate_ddl
from explanation_quota import SCHEMA
revision='0014_explanation_quota'
down_revision='0013_result_features'
branch_labels=None
depends_on=None

def upgrade():
    for statement in translate_ddl(SCHEMA).split(';'):
        if statement.strip():op.execute(statement)

def downgrade():
    raise RuntimeError('Retain quota history; roll back application traffic instead.')
