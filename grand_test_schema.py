"""Additive Grand Test workspace storage; exams retain their existing schema."""
SCHEMA = """
CREATE TABLE IF NOT EXISTS grand_tests (
 id INTEGER PRIMARY KEY AUTOINCREMENT, program_id INTEGER NOT NULL REFERENCES programs(id),
 name TEXT NOT NULL, paper_name TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
 academic_year TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'DRAFT',
 source_json TEXT NOT NULL DEFAULT '{}', questions_json TEXT NOT NULL DEFAULT '[]',
 revision INTEGER NOT NULL DEFAULT 1, exam_id INTEGER REFERENCES exams(id),
 created_by INTEGER NOT NULL REFERENCES users(id), updated_by INTEGER NOT NULL REFERENCES users(id),
 created_at REAL NOT NULL, updated_at REAL NOT NULL, error TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_grand_tests_owner ON grand_tests(created_by,id);
"""
