"""Shared student exam/result read protection."""
from alembic import op
from database import translate_ddl
from student_content_guard import SCHEMA
revision='0015_student_content_guard'
down_revision='0014_explanation_quota'
branch_labels=None
depends_on=None
def upgrade():
    for statement in translate_ddl(SCHEMA).split(';'):
        if statement.strip():op.execute(statement)
def downgrade():
    raise RuntimeError('Retain read quota history; roll back application traffic instead.')
