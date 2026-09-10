"""Private FLAG library and administrator-managed entitlements."""
SCHEMA = '''
CREATE TABLE IF NOT EXISTS flag_members (
 email TEXT PRIMARY KEY, kind TEXT NOT NULL, expires_at REAL,
 active INTEGER NOT NULL DEFAULT 1, updated_by INTEGER NOT NULL REFERENCES users(id), updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS flag_materials (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, filename TEXT NOT NULL,
 object_key TEXT NOT NULL, metadata_json TEXT NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id),
 created_at REAL NOT NULL, active INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS idx_flag_materials_active ON flag_materials(kind,active);
CREATE TABLE IF NOT EXISTS flag_audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id),
 action TEXT NOT NULL, detail TEXT NOT NULL, created_at REAL NOT NULL);
'''
