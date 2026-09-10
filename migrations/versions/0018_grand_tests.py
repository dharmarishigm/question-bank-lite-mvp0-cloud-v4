from alembic import op
from database import translate_ddl
from grand_test_schema import SCHEMA
revision = '0018_grand_tests'
down_revision = '0017_engagement'
branch_labels = None
depends_on = None

def upgrade():
    for statement in translate_ddl(SCHEMA).split(';'):
        if statement.strip():
            op.execute(statement)

def downgrade():
    raise RuntimeError('Retain Grand Test records; roll back application traffic instead.')
