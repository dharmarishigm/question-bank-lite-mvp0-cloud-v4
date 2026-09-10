"""Durable guided paper requests, shared by SQLite startup and migrations."""
SCHEMA = """
CREATE TABLE IF NOT EXISTS program_exam_jobs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, program_id INTEGER NOT NULL REFERENCES programs(id),
 request_key TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'QUEUED',
 input_json TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '',
 exam_id INTEGER REFERENCES exams(id), created_by INTEGER NOT NULL REFERENCES users(id),
 created_at REAL NOT NULL, updated_at REAL NOT NULL, UNIQUE(program_id,request_key));
CREATE INDEX IF NOT EXISTS idx_program_exam_jobs ON program_exam_jobs(program_id,id);
"""

SETUP_SCHEMA = """
CREATE TABLE IF NOT EXISTS program_exam_setups (
 program_id INTEGER PRIMARY KEY REFERENCES programs(id),
 settings_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
 updated_by INTEGER NOT NULL REFERENCES users(id), updated_at REAL NOT NULL);
"""
SCHEMA += SETUP_SCHEMA
