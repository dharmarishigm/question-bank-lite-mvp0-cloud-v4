from alembic import op
from database import translate_ddl
from security_mfa import SCHEMA
revision='0022_security_sessions'
down_revision='0021_security_rate_limits'
branch_labels=None
depends_on=None
def upgrade():
    for statement in SCHEMA.split(';'):
        if statement.strip():op.execute(translate_ddl(statement))
def downgrade():
    raise RuntimeError('Preserve security enrollment records; use an application rollback.')
