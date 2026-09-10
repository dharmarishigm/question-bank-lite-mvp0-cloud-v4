"""Auditable live official-source lookups; no hard-coded exam patterns."""
SCHEMA = """
CREATE TABLE IF NOT EXISTS program_official_lookups (
 id INTEGER PRIMARY KEY AUTOINCREMENT, program_id INTEGER NOT NULL REFERENCES programs(id),
 request_key TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'QUEUED',
 input_json TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '',
 created_by INTEGER NOT NULL REFERENCES users(id), created_at REAL NOT NULL, updated_at REAL NOT NULL,
 UNIQUE(program_id,request_key));
CREATE INDEX IF NOT EXISTS idx_program_official_lookups ON program_official_lookups(program_id,id);
"""
