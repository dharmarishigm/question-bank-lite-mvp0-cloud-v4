"""Add shared bounded security counters; no existing data is changed."""
from alembic import op
from database import translate_ddl
from security_boundary import SCHEMA
revision='0021_security_rate_limits'
down_revision='0020_dqb_document_controls'
branch_labels=None
depends_on=None

def upgrade():
    for statement in SCHEMA.split(';'):
        if statement.strip():op.execute(translate_ddl(statement))

def downgrade():
    op.execute('DROP TABLE IF EXISTS security_rate_limits')
