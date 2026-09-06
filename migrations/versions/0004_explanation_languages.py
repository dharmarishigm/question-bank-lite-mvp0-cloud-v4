"""Store durable explanations per question and language."""
from alembic import op

revision = "0004_explanation_languages"
down_revision = "0003_attempt_override"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE IF NOT EXISTS question_explanation_translations (
      id BIGSERIAL PRIMARY KEY,
      question_id BIGINT NOT NULL REFERENCES questions(id),
      language TEXT NOT NULL DEFAULT 'en',
      explanation TEXT NOT NULL DEFAULT '',
      liked INTEGER NOT NULL DEFAULT 0,
      created_at DOUBLE PRECISION NOT NULL,
      updated_at DOUBLE PRECISION NOT NULL,
      UNIQUE(question_id, language))""")
    op.execute("CREATE INDEX IF NOT EXISTS idx_question_explanation_language ON question_explanation_translations(question_id, language)")
    op.execute("""INSERT INTO question_explanation_translations
      (question_id, language, explanation, liked, created_at, updated_at)
      SELECT question_id, 'en', explanation, liked, created_at, updated_at FROM question_explanations
      ON CONFLICT (question_id, language) DO NOTHING""")


def downgrade():
    op.drop_table("question_explanation_translations")
