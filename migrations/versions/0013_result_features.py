"""Add question concerns and revocable PDF report shares."""
from alembic import op
from database import translate_ddl
from result_features_schema import SCHEMA
revision='0013_result_features'
down_revision='0012_exam_setups'
branch_labels=None
depends_on=None

def upgrade():
    for statement in translate_ddl(SCHEMA).split(';'):
        if statement.strip():op.execute(statement)

def downgrade():
    raise RuntimeError('Retain concern and sharing audit history; roll back application traffic.')
