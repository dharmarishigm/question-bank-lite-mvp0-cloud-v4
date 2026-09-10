"""Question concerns and revocable result-report links."""
SCHEMA = """
CREATE TABLE IF NOT EXISTS question_concerns (
 id INTEGER PRIMARY KEY AUTOINCREMENT, question_id INTEGER NOT NULL REFERENCES questions(id),
 session_id INTEGER REFERENCES exam_sessions(id), exam_id INTEGER REFERENCES exams(id),
 reporter_id INTEGER NOT NULL REFERENCES users(id), category TEXT NOT NULL,
 description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN', resolution TEXT NOT NULL DEFAULT '',
 revision INTEGER NOT NULL DEFAULT 1, resolved_by INTEGER REFERENCES users(id),
 created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_concerns_status ON question_concerns(status,created_at);
CREATE TABLE IF NOT EXISTS result_report_links (
 id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER NOT NULL REFERENCES exam_sessions(id),
 token_hash TEXT NOT NULL UNIQUE, created_by INTEGER NOT NULL REFERENCES users(id),
 created_at REAL NOT NULL, expires_at REAL NOT NULL, revoked_at REAL);
CREATE INDEX IF NOT EXISTS idx_report_links_session ON result_report_links(session_id);
"""
