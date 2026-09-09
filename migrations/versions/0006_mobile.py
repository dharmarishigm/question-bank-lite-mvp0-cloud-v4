"""Mobile sign-in handoff and opt-in device delivery."""
from alembic import op
from database import translate_ddl
revision="0006_mobile"
down_revision="0005_tutor"
branch_labels=None
depends_on=None
SCHEMA='\nCREATE TABLE IF NOT EXISTS mobile_auth_requests (\n id INTEGER PRIMARY KEY AUTOINCREMENT, request_hash TEXT NOT NULL UNIQUE, challenge TEXT NOT NULL,\n user_id INTEGER REFERENCES users(id), expires_at REAL NOT NULL, consumed INTEGER NOT NULL DEFAULT 0);\nCREATE INDEX IF NOT EXISTS idx_mobile_auth_expiry ON mobile_auth_requests(expires_at);\nCREATE TABLE IF NOT EXISTS mobile_devices (\n id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id), token TEXT NOT NULL UNIQUE,\n enabled INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL);\nCREATE INDEX IF NOT EXISTS idx_mobile_devices_user ON mobile_devices(user_id);\n'
def upgrade():
    for sql in translate_ddl(SCHEMA).split(";"):
        if sql.strip():op.execute(sql)
def downgrade():
    op.drop_table("mobile_devices")
    op.drop_table("mobile_auth_requests")
