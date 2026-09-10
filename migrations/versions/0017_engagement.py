from alembic import op
from database import translate_ddl
from engagement_schema import SCHEMA
revision='0017_engagement'
down_revision='0016_flag_library'
branch_labels=None
depends_on=None
def upgrade():
    for statement in translate_ddl(SCHEMA).split(';'):
        if statement.strip():op.execute(statement)
def downgrade():raise RuntimeError('Retain enquiries and trial history; roll back application traffic instead.')
