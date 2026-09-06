"""Add per-registration attempt allowance."""
from alembic import op

revision = "0003_registration_attempt_override"
down_revision = "0002_exam_blueprints"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("ALTER TABLE exam_enrollments ADD COLUMN IF NOT EXISTS max_attempts_override INTEGER")

def downgrade():
    op.drop_column("exam_enrollments", "max_attempts_override")
