"""Local bootstrap after Programs; managed production uses reviewed migrations."""
SCHEMA = """
CREATE TABLE IF NOT EXISTS program_enrollments (
 id INTEGER PRIMARY KEY AUTOINCREMENT, program_id INTEGER NOT NULL REFERENCES programs(id),
 user_id INTEGER NOT NULL REFERENCES users(id), status TEXT NOT NULL DEFAULT 'ENROLLED',
 registered_at REAL NOT NULL, cancelled_at REAL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
 registration_source TEXT NOT NULL DEFAULT 'PROGRAM', created_by INTEGER,
 UNIQUE(program_id,user_id));
CREATE INDEX IF NOT EXISTS idx_program_enrollments_user ON program_enrollments(user_id);
CREATE INDEX IF NOT EXISTS idx_program_enrollments_program ON program_enrollments(program_id);
"""
