"""Additive setup-job schema, also used by migration 0009."""
SCHEMA = """
CREATE TABLE IF NOT EXISTS program_setup_jobs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, program_id INTEGER NOT NULL REFERENCES programs(id),
 request_key TEXT NOT NULL, program_revision INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'QUEUED',
 input_json TEXT NOT NULL, proposal_json TEXT NOT NULL DEFAULT '{}', telemetry_json TEXT NOT NULL DEFAULT '{}',
 result_json TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '',
 created_by INTEGER NOT NULL REFERENCES users(id), created_at REAL NOT NULL, updated_at REAL NOT NULL,
 UNIQUE(program_id,request_key));
CREATE INDEX IF NOT EXISTS idx_program_setup_jobs ON program_setup_jobs(program_id,status,id);
"""
