"""Add per-page DigitalQBank progress and audit history."""
from alembic import op
from database import translate_ddl

revision = '0019_digitalqbank_page_tracking'
down_revision = '0018_grand_tests'
branch_labels = None
depends_on = None

def upgrade():
    statements = ["""CREATE TABLE IF NOT EXISTS grand_test_page_status (
      id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id INTEGER NOT NULL REFERENCES grand_tests(id) ON DELETE CASCADE,
      source_document_id TEXT NOT NULL, page_number INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'Pending'
        CHECK(status IN ('Pending','InProgress','Completed','Not Applicable')),
      created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id), updated_by INTEGER NOT NULL REFERENCES users(id),
      UNIQUE(workspace_id,page_number))""", """CREATE INDEX IF NOT EXISTS idx_gt_page_status_workspace ON grand_test_page_status(workspace_id,page_number)""", """CREATE TABLE IF NOT EXISTS grand_test_page_status_audit (
      id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id INTEGER NOT NULL REFERENCES grand_tests(id) ON DELETE CASCADE,
      source_document_id TEXT NOT NULL, page_number INTEGER NOT NULL, previous_status TEXT, new_status TEXT NOT NULL,
      changed_at REAL NOT NULL, changed_by INTEGER NOT NULL REFERENCES users(id), reason TEXT NOT NULL DEFAULT '')"""]
    for statement in statements:
        op.execute(translate_ddl(statement))

def downgrade():
    raise RuntimeError('Retain DigitalQBank audit history; roll back application traffic instead.')
