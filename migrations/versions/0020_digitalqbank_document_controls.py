"""Add metadata and Admin availability controls to Program PDFs."""
from alembic import op
from database import translate_ddl
from sqlalchemy import inspect
revision='0020_dqb_document_controls'
down_revision='0019_digitalqbank_page_tracking'
branch_labels=None
depends_on=None

def upgrade():
    columns = [('subject', "TEXT NOT NULL DEFAULT ''"), ('chapter', "TEXT NOT NULL DEFAULT ''"),
      ('available_for_digitisation', 'INTEGER NOT NULL DEFAULT 0'), ('availability_changed_at', 'REAL'),
      ('availability_changed_by', 'INTEGER'), ('updated_by', 'INTEGER'), ('updated_at', 'REAL')]
    bind = op.get_bind()
    existing = {column['name'] for column in inspect(bind).get_columns('program_documents')}
    for name, definition in columns:
        if name not in existing:
            op.execute(f'ALTER TABLE program_documents ADD COLUMN {name} {translate_ddl(definition)}')
    op.execute('UPDATE program_documents SET updated_at=COALESCE(updated_at,created_at),updated_by=COALESCE(updated_by,created_by)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_program_documents_available ON program_documents(program_id,available_for_digitisation,created_at)')
    op.execute(translate_ddl("""CREATE TABLE IF NOT EXISTS program_document_audit (
      id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER NOT NULL REFERENCES program_documents(id) ON DELETE CASCADE,
      action TEXT NOT NULL, previous_value TEXT NOT NULL DEFAULT '', new_value TEXT NOT NULL DEFAULT '', changed_at REAL NOT NULL,
      changed_by INTEGER NOT NULL REFERENCES users(id), reason TEXT NOT NULL DEFAULT '')"""))

def downgrade():
    raise RuntimeError('Retain document metadata and availability history.')
