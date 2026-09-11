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
CREATE TABLE IF NOT EXISTS program_documents (
 id INTEGER PRIMARY KEY AUTOINCREMENT, program_id INTEGER NOT NULL REFERENCES programs(id),
 source_document_id TEXT NOT NULL REFERENCES source_documents(id), original_filename TEXT NOT NULL,
 gcs_object TEXT NOT NULL DEFAULT '', subject TEXT NOT NULL DEFAULT '', chapter TEXT NOT NULL DEFAULT '',
 available_for_digitisation INTEGER NOT NULL DEFAULT 0, availability_changed_at REAL, availability_changed_by INTEGER REFERENCES users(id),
 created_by INTEGER NOT NULL REFERENCES users(id), updated_by INTEGER REFERENCES users(id), updated_at REAL,
 created_at REAL NOT NULL, UNIQUE(program_id,source_document_id));
CREATE INDEX IF NOT EXISTS idx_program_documents_program ON program_documents(program_id,created_at);
CREATE TABLE IF NOT EXISTS program_document_audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER NOT NULL REFERENCES program_documents(id) ON DELETE CASCADE,
 action TEXT NOT NULL, previous_value TEXT NOT NULL DEFAULT '', new_value TEXT NOT NULL DEFAULT '', changed_at REAL NOT NULL,
 changed_by INTEGER NOT NULL REFERENCES users(id), reason TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS grand_test_page_status (
 id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id INTEGER NOT NULL REFERENCES grand_tests(id) ON DELETE CASCADE,
 source_document_id TEXT NOT NULL, page_number INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'Pending'
   CHECK(status IN ('Pending','InProgress','Completed','Not Applicable')),
 created_at REAL NOT NULL, updated_at REAL NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id), updated_by INTEGER NOT NULL REFERENCES users(id),
 UNIQUE(workspace_id,page_number)
);
CREATE INDEX IF NOT EXISTS idx_gt_page_status_workspace ON grand_test_page_status(workspace_id,page_number);
CREATE TABLE IF NOT EXISTS grand_test_page_status_audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id INTEGER NOT NULL REFERENCES grand_tests(id) ON DELETE CASCADE,
 source_document_id TEXT NOT NULL, page_number INTEGER NOT NULL, previous_status TEXT, new_status TEXT NOT NULL,
 changed_at REAL NOT NULL, changed_by INTEGER NOT NULL REFERENCES users(id), reason TEXT NOT NULL DEFAULT ''
);
"""
