"""Private FLAG learning materials and expiring membership."""
from alembic import op
from database import translate_ddl
from flag_schema import SCHEMA
revision='0016_flag_library'
down_revision='0015_student_content_guard'
branch_labels=None
depends_on=None
def upgrade():
    for statement in translate_ddl(SCHEMA).split(';'):
        if statement.strip():op.execute(statement)
def downgrade():
    raise RuntimeError('Retain FLAG access and material history; roll back application traffic instead.')
