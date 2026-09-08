"""Private IQraMentor history and bounded performance query index."""
from alembic import op
from database import translate_ddl
SCHEMA = "\nCREATE TABLE IF NOT EXISTS tutor_sessions (\n id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),\n created_at REAL NOT NULL, updated_at REAL NOT NULL, status TEXT NOT NULL DEFAULT 'ACTIVE');\nCREATE INDEX IF NOT EXISTS idx_tutor_sessions_user ON tutor_sessions(user_id,updated_at);\nCREATE TABLE IF NOT EXISTS tutor_messages (\n id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER NOT NULL REFERENCES tutor_sessions(id),\n role TEXT NOT NULL, content TEXT NOT NULL, structured_payload TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL);\nCREATE INDEX IF NOT EXISTS idx_tutor_messages_session ON tutor_messages(session_id,id);\nCREATE INDEX IF NOT EXISTS idx_sessions_user_submitted ON exam_sessions(user_id,submitted_at);\n"
revision = '0005_tutor'
down_revision = '0004_explanation_languages'
branch_labels = None
depends_on = None

def upgrade():
    for statement in translate_ddl(SCHEMA).split(';'):
        if statement.strip(): op.execute(statement)

def downgrade():
    op.drop_table('tutor_messages')
    op.drop_table('tutor_sessions')
    op.drop_index('idx_sessions_user_submitted',table_name='exam_sessions')
