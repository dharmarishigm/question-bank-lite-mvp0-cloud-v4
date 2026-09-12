"""Commerce, verification, communication and result release foundations."""
from alembic import op
from commerce_schema import SCHEMA
from database import translate_ddl

revision='0025_commerce_communications'
down_revision='0024_program_enrollments'
branch_labels=None
depends_on=None

def upgrade():
    for statement in translate_ddl(SCHEMA).split(';'):
        if statement.strip(): op.execute(statement)

def downgrade():
    raise RuntimeError('Commerce and communication records are retained; roll back application traffic instead.')
