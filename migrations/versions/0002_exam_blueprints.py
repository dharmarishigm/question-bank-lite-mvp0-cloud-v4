"""Add durable exam blueprints and generation runs."""
from alembic import op

revision = "0002_exam_blueprints"
down_revision = "0001_cloud_postgres"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE IF NOT EXISTS exam_blueprints (
      id BIGSERIAL PRIMARY KEY, exam_id BIGINT REFERENCES exams(id), name TEXT NOT NULL,
      blueprint_json TEXT NOT NULL, created_by BIGINT NOT NULL REFERENCES users(id),
      created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL)""")
    op.execute("""CREATE TABLE IF NOT EXISTS exam_generation_runs (
      id BIGSERIAL PRIMARY KEY, exam_id BIGINT REFERENCES exams(id),
      blueprint_id BIGINT NOT NULL REFERENCES exam_blueprints(id), requested_questions INTEGER NOT NULL,
      selected_questions INTEGER NOT NULL DEFAULT 0, shortage_count INTEGER NOT NULL DEFAULT 0,
      fallback_count INTEGER NOT NULL DEFAULT 0, selection_seed INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL, request_json TEXT NOT NULL, result_json TEXT NOT NULL,
      created_by BIGINT NOT NULL REFERENCES users(id), created_at DOUBLE PRECISION NOT NULL)""")
    op.execute("CREATE INDEX IF NOT EXISTS idx_exam_blueprints_exam ON exam_blueprints(exam_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_exam_generation_runs_exam ON exam_generation_runs(exam_id)")


def downgrade():
    op.drop_table("exam_generation_runs")
    op.drop_table("exam_blueprints")
