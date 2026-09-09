"""Additive storage for generic blueprints; no legacy records are rewritten."""
SCHEMA = """
CREATE TABLE IF NOT EXISTS programs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 payload_json TEXT NOT NULL, status TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
 created_by INTEGER NOT NULL REFERENCES users(id), updated_by INTEGER NOT NULL REFERENCES users(id),
 created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_programs_status ON programs(status,name);
CREATE TABLE IF NOT EXISTS blueprints (
 id INTEGER PRIMARY KEY AUTOINCREMENT, program_id INTEGER NOT NULL REFERENCES programs(id),
 kind TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ACTIVE', revision INTEGER NOT NULL DEFAULT 0,
 created_by INTEGER NOT NULL REFERENCES users(id), created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_blueprints_program ON blueprints(program_id,kind,status);
CREATE TABLE IF NOT EXISTS blueprint_versions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, blueprint_id INTEGER NOT NULL REFERENCES blueprints(id),
 version_number INTEGER NOT NULL, parent_version_id INTEGER REFERENCES blueprint_versions(id),
 payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL, schema_version INTEGER NOT NULL DEFAULT 1,
 status TEXT NOT NULL DEFAULT 'DRAFT', origin TEXT NOT NULL, summary TEXT NOT NULL,
 validation_json TEXT NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id), created_at REAL NOT NULL,
 UNIQUE(blueprint_id,version_number));
CREATE INDEX IF NOT EXISTS idx_blueprint_versions_status ON blueprint_versions(blueprint_id,status);
CREATE TABLE IF NOT EXISTS blueprint_sources (
 id INTEGER PRIMARY KEY AUTOINCREMENT, program_id INTEGER NOT NULL REFERENCES programs(id),
 kind TEXT NOT NULL, payload_json TEXT NOT NULL, sha256 TEXT NOT NULL, included INTEGER NOT NULL DEFAULT 1,
 review_status TEXT NOT NULL DEFAULT 'IN_REVIEW', created_by INTEGER NOT NULL REFERENCES users(id), created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_blueprint_sources_program ON blueprint_sources(program_id,kind);
CREATE TABLE IF NOT EXISTS curriculum_versions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, program_id INTEGER NOT NULL REFERENCES programs(id),
 name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT', created_by INTEGER NOT NULL REFERENCES users(id), created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS curriculum_nodes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, version_id INTEGER NOT NULL REFERENCES curriculum_versions(id),
 parent_id INTEGER REFERENCES curriculum_nodes(id), kind TEXT NOT NULL, name TEXT NOT NULL, learning_outcome TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_curriculum_nodes_version ON curriculum_nodes(version_id,parent_id);
CREATE TABLE IF NOT EXISTS blueprint_question_snapshots (
 id INTEGER PRIMARY KEY AUTOINCREMENT, program_id INTEGER NOT NULL REFERENCES programs(id),
 question_id INTEGER REFERENCES questions(id), question_version_id INTEGER REFERENCES question_versions(id),
 payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL, provenance_json TEXT NOT NULL,
 origin TEXT NOT NULL, transcription_status TEXT NOT NULL DEFAULT 'IN_REVIEW', academic_status TEXT NOT NULL DEFAULT 'IN_REVIEW',
 created_by INTEGER NOT NULL REFERENCES users(id), created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_blueprint_inventory ON blueprint_question_snapshots(program_id,academic_status,transcription_status);
CREATE TABLE IF NOT EXISTS paper_generation_runs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, program_id INTEGER NOT NULL REFERENCES programs(id),
 blueprint_version_id INTEGER NOT NULL REFERENCES blueprint_versions(id), status TEXT NOT NULL DEFAULT 'DRAFT',
 payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id), created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_paper_runs_program ON paper_generation_runs(program_id,status);
CREATE TABLE IF NOT EXISTS blueprint_generation_jobs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, program_id INTEGER NOT NULL REFERENCES programs(id),
 run_id INTEGER NOT NULL REFERENCES paper_generation_runs(id), slot_position INTEGER NOT NULL,
 author_prompt_id INTEGER NOT NULL REFERENCES blueprint_prompts(id), verifier_prompt_id INTEGER NOT NULL REFERENCES blueprint_prompts(id),
 status TEXT NOT NULL DEFAULT 'QUEUED', result_json TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '',
 created_by INTEGER NOT NULL REFERENCES users(id), created_at REAL NOT NULL, updated_at REAL NOT NULL,
 UNIQUE(run_id,slot_position));
CREATE INDEX IF NOT EXISTS idx_generation_jobs_program ON blueprint_generation_jobs(program_id,status);
CREATE TABLE IF NOT EXISTS paper_question_exposure (
 run_id INTEGER NOT NULL REFERENCES paper_generation_runs(id), snapshot_id INTEGER NOT NULL REFERENCES blueprint_question_snapshots(id),
 PRIMARY KEY(run_id,snapshot_id));
CREATE TABLE IF NOT EXISTS blueprint_prompts (
 id INTEGER PRIMARY KEY AUTOINCREMENT, program_id INTEGER NOT NULL REFERENCES programs(id),
 purpose TEXT NOT NULL, version_number INTEGER NOT NULL, template TEXT NOT NULL,
 payload_hash TEXT NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id), created_at REAL NOT NULL,
 UNIQUE(program_id,purpose,version_number));
CREATE TABLE IF NOT EXISTS blueprint_refinements (
 id INTEGER PRIMARY KEY AUTOINCREMENT, program_id INTEGER NOT NULL REFERENCES programs(id),
 blueprint_version_id INTEGER NOT NULL REFERENCES blueprint_versions(id), prompt_id INTEGER NOT NULL REFERENCES blueprint_prompts(id),
 status TEXT NOT NULL DEFAULT 'QUEUED', proposal_json TEXT NOT NULL DEFAULT '{}', telemetry_json TEXT NOT NULL DEFAULT '{}',
 decisions_json TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '', created_by INTEGER NOT NULL REFERENCES users(id),
 created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_refinements_program ON blueprint_refinements(program_id,status);
CREATE TABLE IF NOT EXISTS historical_observations (
 id INTEGER PRIMARY KEY AUTOINCREMENT, program_id INTEGER NOT NULL REFERENCES programs(id),
 source_id INTEGER NOT NULL REFERENCES blueprint_sources(id), source_question_ref TEXT NOT NULL,
 payload_json TEXT NOT NULL, review_status TEXT NOT NULL DEFAULT 'IN_REVIEW',
 created_by INTEGER NOT NULL REFERENCES users(id), created_at REAL NOT NULL,
 UNIQUE(source_id,source_question_ref));
CREATE INDEX IF NOT EXISTS idx_history_program ON historical_observations(program_id,review_status);
CREATE TABLE IF NOT EXISTS historical_profiles (
 id INTEGER PRIMARY KEY AUTOINCREMENT, program_id INTEGER NOT NULL REFERENCES programs(id),
 payload_json TEXT NOT NULL, evidence_json TEXT NOT NULL, payload_hash TEXT NOT NULL,
 created_by INTEGER NOT NULL REFERENCES users(id), created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_profiles_program ON historical_profiles(program_id,id);
CREATE TABLE IF NOT EXISTS blueprint_audit_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, program_id INTEGER REFERENCES programs(id), actor_id INTEGER NOT NULL REFERENCES users(id),
 action TEXT NOT NULL, entity_id INTEGER NOT NULL, details_json TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_blueprint_audit_program ON blueprint_audit_events(program_id,id);
"""


def init_blueprints():
    from contextlib import closing
    from platform_api import db
    with closing(db()) as conn:
        conn.executescript(SCHEMA)
        conn.commit()
