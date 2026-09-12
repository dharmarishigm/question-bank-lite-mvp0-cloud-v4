"""Question Bank Cloud MVP-0 v4: question digitization and examinations."""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import mimetypes
import math
import os
import re
import sqlite3
import time
import uuid
import zipfile
from contextlib import closing, contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool

from llm_extract import extract_image, extract_pdf, extract_source, llm_status
from ocr import OcrUnavailable, ocr_status, ocr_to_latex, vision_status
from pdf_import import parse_pdf
from multimodal import build_content_blocks
from llm_generate import GenerationRequest, PromptGuidanceRequest, SYSTEM_PROMPT_VERSION, fingerprint, generate_prompt_guidance, generate_questions, public_prompt_preview
from database import connect as connect_database

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("QB_DATA_DIR", os.path.join(BASE_DIR, "data"))
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
SOURCE_DIR = os.path.join(DATA_DIR, "sources")
DB_PATH = os.path.join(DATA_DIR, "questions.db")
ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_TEXT_EXT = {".txt", ".md", ".csv", ".json", ".log", ".ipynb", ".html", ".xml", ".rtf"}
ALLOWED_DOC_EXT = {".doc", ".docx", ".odt", ".ppt", ".pptx", ".xls", ".xlsx"}
ALLOWED_SOURCE_EXT = ALLOWED_IMAGE_EXT | {".pdf"} | ALLOWED_TEXT_EXT | ALLOWED_DOC_EXT
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_SOURCE_BYTES = 50 * 1024 * 1024

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(SOURCE_DIR, exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL DEFAULT '',
    chapter TEXT NOT NULL DEFAULT '',
    topic TEXT NOT NULL DEFAULT '',
    subtopic TEXT NOT NULL DEFAULT '',
    exam TEXT NOT NULL DEFAULT '',
    year TEXT NOT NULL DEFAULT '',
    qtype TEXT NOT NULL DEFAULT 'mcq_single',
    difficulty TEXT NOT NULL DEFAULT 'medium',
    marks TEXT NOT NULL DEFAULT '',
    statement TEXT NOT NULL DEFAULT '',
    options TEXT NOT NULL DEFAULT '[]',
    answer TEXT NOT NULL DEFAULT '',
    solution TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    source_image TEXT NOT NULL DEFAULT '',
    source_segments TEXT NOT NULL DEFAULT '[]',
    source_document_id TEXT NOT NULL DEFAULT '',
    source_document_sha256 TEXT NOT NULL DEFAULT '',
    source_page INTEGER NOT NULL DEFAULT 0,
    source_bbox TEXT NOT NULL DEFAULT '[]',
    extraction_run_id TEXT NOT NULL DEFAULT '',
    extraction_provider TEXT NOT NULL DEFAULT '',
    extraction_model TEXT NOT NULL DEFAULT '',
    verification_status TEXT NOT NULL DEFAULT 'UNVERIFIED',
    confidence REAL NOT NULL DEFAULT 0,
    verification_issues TEXT NOT NULL DEFAULT '[]',
    uncertainties TEXT NOT NULL DEFAULT '[]',
    content_blocks TEXT NOT NULL DEFAULT '[]',
    visual_assets TEXT NOT NULL DEFAULT '[]',
    math_evidence TEXT NOT NULL DEFAULT '[]',
    source_type TEXT NOT NULL DEFAULT 'MANUAL',
    generation_run_id TEXT NOT NULL DEFAULT '',
    generation_provider TEXT NOT NULL DEFAULT '',
    generation_model TEXT NOT NULL DEFAULT '',
    generation_prompt_version TEXT NOT NULL DEFAULT '',
    generation_prompt TEXT NOT NULL DEFAULT '',
    generation_metadata TEXT NOT NULL DEFAULT '{}',
    generation_fingerprint TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_questions_subject ON questions(subject);
CREATE INDEX IF NOT EXISTS idx_questions_chapter ON questions(chapter);
CREATE INDEX IF NOT EXISTS idx_questions_topic ON questions(topic);
CREATE INDEX IF NOT EXISTS idx_questions_difficulty ON questions(difficulty);
CREATE INDEX IF NOT EXISTS idx_questions_qtype ON questions(qtype);
CREATE INDEX IF NOT EXISTS idx_questions_verification ON questions(verification_status);
CREATE INDEX IF NOT EXISTS idx_questions_source_type ON questions(source_type);

CREATE TABLE IF NOT EXISTS source_documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    mime_type TEXT NOT NULL,
    page_count INTEGER NOT NULL DEFAULT 0,
    local_path TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS extraction_runs (
    id TEXT PRIMARY KEY,
    source_document_id TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    usage_json TEXT NOT NULL DEFAULT '{}',
    warnings_json TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    FOREIGN KEY(source_document_id) REFERENCES source_documents(id)
);

CREATE TABLE IF NOT EXISTS question_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL,
    version_no INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    FOREIGN KEY(question_id) REFERENCES questions(id)
);

CREATE TABLE IF NOT EXISTS question_explanations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL UNIQUE,
    explanation TEXT NOT NULL DEFAULT '',
    liked INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(question_id) REFERENCES questions(id)
);

CREATE TABLE IF NOT EXISTS question_explanation_translations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL,
    language TEXT NOT NULL DEFAULT 'en',
    explanation TEXT NOT NULL DEFAULT '',
    liked INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(question_id, language),
    FOREIGN KEY(question_id) REFERENCES questions(id)
);

CREATE TABLE IF NOT EXISTS exam_registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL DEFAULT '',
    last_name TEXT NOT NULL DEFAULT '',
    date_of_birth TEXT NOT NULL DEFAULT '',
    full_name TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    exam_name TEXT NOT NULL DEFAULT '',
    exam_date TEXT NOT NULL DEFAULT '',
    center_preference TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    notes TEXT NOT NULL DEFAULT '',
    confirmation_token TEXT NOT NULL DEFAULT '',
    is_confirmed INTEGER NOT NULL DEFAULT 0,
    confirmation_sent_at REAL NOT NULL DEFAULT 0,
    confirmed_at REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_generation_runs (
    id TEXT PRIMARY KEY, exam_name TEXT NOT NULL, exam_type TEXT NOT NULL DEFAULT '', level TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL, chapter TEXT NOT NULL DEFAULT '', topic TEXT NOT NULL DEFAULT '', subtopic TEXT NOT NULL DEFAULT '',
    difficulty TEXT NOT NULL DEFAULT '', question_type TEXT NOT NULL DEFAULT '', requested_count INTEGER NOT NULL,
    generated_count INTEGER NOT NULL DEFAULT 0, accepted_count INTEGER NOT NULL DEFAULT 0, rejected_count INTEGER NOT NULL DEFAULT 0,
    language TEXT NOT NULL DEFAULT 'English', model TEXT NOT NULL DEFAULT '', system_prompt_version TEXT NOT NULL DEFAULT '',
    generation_prompt TEXT NOT NULL, syllabus TEXT NOT NULL DEFAULT '', metadata_json TEXT NOT NULL DEFAULT '{}',
    request_json TEXT NOT NULL DEFAULT '{}', output_json TEXT NOT NULL DEFAULT '{}', usage_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'RUNNING',
    error_message TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL
);
"""

# Additive migration map for databases created by the original ZIP.
QUESTION_MIGRATIONS = {
    "subtopic": "TEXT NOT NULL DEFAULT ''",
    "source_image": "TEXT NOT NULL DEFAULT ''",
    "source_segments": "TEXT NOT NULL DEFAULT '[]'",
    "source_document_id": "TEXT NOT NULL DEFAULT ''",
    "source_document_sha256": "TEXT NOT NULL DEFAULT ''",
    "source_page": "INTEGER NOT NULL DEFAULT 0",
    "source_bbox": "TEXT NOT NULL DEFAULT '[]'",
    "extraction_run_id": "TEXT NOT NULL DEFAULT ''",
    "extraction_provider": "TEXT NOT NULL DEFAULT ''",
    "extraction_model": "TEXT NOT NULL DEFAULT ''",
    "verification_status": "TEXT NOT NULL DEFAULT 'UNVERIFIED'",
    "confidence": "REAL NOT NULL DEFAULT 0",
    "verification_issues": "TEXT NOT NULL DEFAULT '[]'",
    "uncertainties": "TEXT NOT NULL DEFAULT '[]'",
    "content_blocks": "TEXT NOT NULL DEFAULT '[]'",
    "visual_assets": "TEXT NOT NULL DEFAULT '[]'",
    "math_evidence": "TEXT NOT NULL DEFAULT '[]'",
    "source_type": "TEXT NOT NULL DEFAULT 'MANUAL'",
    "generation_run_id": "TEXT NOT NULL DEFAULT ''",
    "generation_provider": "TEXT NOT NULL DEFAULT ''",
    "generation_model": "TEXT NOT NULL DEFAULT ''",
    "generation_prompt_version": "TEXT NOT NULL DEFAULT ''",
    "generation_prompt": "TEXT NOT NULL DEFAULT ''",
    "generation_metadata": "TEXT NOT NULL DEFAULT '{}'",
    "generation_fingerprint": "TEXT NOT NULL DEFAULT ''",
}
EXAM_REGISTRATION_MIGRATIONS = {
    "first_name": "TEXT NOT NULL DEFAULT ''",
    "last_name": "TEXT NOT NULL DEFAULT ''",
    "date_of_birth": "TEXT NOT NULL DEFAULT ''",
    "confirmation_token": "TEXT NOT NULL DEFAULT ''",
    "is_confirmed": "INTEGER NOT NULL DEFAULT 0",
    "confirmation_sent_at": "REAL NOT NULL DEFAULT 0",
    "confirmed_at": "REAL NOT NULL DEFAULT 0",
}
AI_RUN_MIGRATIONS = {"output_json": "TEXT NOT NULL DEFAULT '{}'"}

FIELDS = (
    "subject", "chapter", "topic", "subtopic", "exam", "year", "qtype", "difficulty",
    "marks", "statement", "options", "answer", "solution", "tags", "source_image",
    "source_segments", "source_document_id", "source_document_sha256", "source_page",
    "source_bbox", "extraction_run_id", "extraction_provider", "extraction_model",
    "verification_status", "confidence", "verification_issues", "uncertainties",
    "content_blocks", "visual_assets", "math_evidence", "source_type", "generation_run_id",
    "generation_provider", "generation_model", "generation_prompt_version", "generation_prompt",
    "generation_metadata", "generation_fingerprint",
)
JSON_FIELDS = {"options", "source_segments", "source_bbox", "verification_issues", "uncertainties", "content_blocks", "visual_assets", "math_evidence", "generation_metadata"}


def connect():
    """Return SQLite locally or Cloud SQL PostgreSQL when DATABASE_URL is set."""
    return connect_database(DB_PATH)


if not os.getenv("DATABASE_URL"):
    with closing(connect()) as _conn:
        _conn.executescript(SCHEMA)
        columns = {r["name"] for r in _conn.execute("PRAGMA table_info(questions)")}
        for name, ddl in QUESTION_MIGRATIONS.items():
            if name not in columns:
                _conn.execute(f"ALTER TABLE questions ADD COLUMN {name} {ddl}")
        registration_columns = {r["name"] for r in _conn.execute("PRAGMA table_info(exam_registrations)")}
        for name, ddl in EXAM_REGISTRATION_MIGRATIONS.items():
            if name not in registration_columns:
                _conn.execute(f"ALTER TABLE exam_registrations ADD COLUMN {name} {ddl}")
        run_columns = {r["name"] for r in _conn.execute("PRAGMA table_info(ai_generation_runs)")}
        for name, ddl in AI_RUN_MIGRATIONS.items():
            if name not in run_columns:
                _conn.execute(f"ALTER TABLE ai_generation_runs ADD COLUMN {name} {ddl}")
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_questions_source_document ON questions(source_document_id)")
        _conn.commit()


class Question(BaseModel):
    subject: str = ""
    chapter: str = ""
    topic: str = ""
    subtopic: str = ""
    exam: str = ""
    year: str = ""
    qtype: str = "mcq_single"
    difficulty: str = "medium"
    marks: str = ""
    statement: str = ""
    options: list[str] = Field(default_factory=list)
    answer: str = ""
    solution: str = ""
    tags: str = ""
    source_image: str = ""
    source_segments: list[dict] = Field(default_factory=list)
    source_document_id: str = ""
    source_document_sha256: str = ""
    source_page: int = 0
    source_bbox: list[float] = Field(default_factory=list)
    extraction_run_id: str = ""
    extraction_provider: str = ""
    extraction_model: str = ""
    verification_status: str = "UNVERIFIED"
    confidence: float = 0.0
    verification_issues: list[dict] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    content_blocks: list[dict] = Field(default_factory=list)
    visual_assets: list[dict] = Field(default_factory=list)
    math_evidence: list[dict] = Field(default_factory=list)
    source_type: str = "MANUAL"
    generation_run_id: str = ""
    generation_provider: str = ""
    generation_model: str = ""
    generation_prompt_version: str = ""
    generation_prompt: str = ""
    generation_metadata: dict = Field(default_factory=dict)
    generation_fingerprint: str = ""


class ExamRegistration(BaseModel):
    first_name: str = ""
    last_name: str = ""
    date_of_birth: str = ""
    full_name: str = ""
    email: str = ""
    phone: str = ""
    exam_name: str = ""
    exam_date: str = ""
    center_preference: str = ""
    status: str = "pending"
    notes: str = ""
    confirmation_token: str = ""
    is_confirmed: bool = False


app = FastAPI(title="MeritIQra", description="AI-Powered Intelligence Platform", version="4.0.0")

# The authenticated exam platform shares the configured database adapter.
from platform_api import init_platform, router as platform_router
# Run additive schema migrations for both local SQLite and Cloud SQL.  The
# database adapter translates the shared DDL for PostgreSQL.
if os.getenv('QB_SCHEMA_MANAGED') != '1':
    init_platform()
app.include_router(platform_router)
from prompt_registry import init_prompt_registry, router as prompt_registry_router
if os.getenv('QB_SCHEMA_MANAGED') != '1':
    init_prompt_registry()
app.include_router(prompt_registry_router)
from explanation_jobs import router as explanation_jobs_router
app.include_router(explanation_jobs_router)
from security_mfa import router as security_mfa_router
app.include_router(security_mfa_router)
from blueprint_api import router as programs_router
app.include_router(programs_router)
from blueprint_setup import router as program_setup_router
app.include_router(program_setup_router)
from program_exam import router as program_exam_router
app.include_router(program_exam_router)
from official_exam import router as official_exam_router
app.include_router(official_exam_router)
from tutor_agent import router as tutor_router
app.include_router(tutor_router)
from mobile_api import router as mobile_router, init_mobile
if not os.getenv("DATABASE_URL"): init_mobile()
app.include_router(mobile_router)
from exam_conduct import init_exam_conduct, router as exam_conduct_router
if not os.getenv("DATABASE_URL"):
    init_exam_conduct()
app.include_router(exam_conduct_router)
from result_features import router as result_features_router
app.include_router(result_features_router)
from ai_review import router as ai_review_router
app.include_router(ai_review_router)
from question_correction import router as question_correction_router
app.include_router(question_correction_router)
from flag_api import router as flag_router
app.include_router(flag_router)
from engagement import router as engagement_router
app.include_router(engagement_router)
from marketing_pdf import router as marketing_pdf_router
app.include_router(marketing_pdf_router)
from epidemiology_model import router as epidemiology_router
app.include_router(epidemiology_router)

from grand_tests import router as grand_tests_router
app.include_router(grand_tests_router)

@app.middleware("http")
async def protect_legacy_admin_api(request: Request, call_next):
    """Apply role and CSRF checks to the original administrative endpoints.

    Authentication becomes mandatory when Google login or explicit development
    mock mode is configured. This keeps offline parser unit tests usable while a
    configured application never exposes the legacy question APIs to students.
    """
    from security_boundary import enabled
    configured = enabled() or bool(os.getenv("GOOGLE_CLIENT_ID") or os.getenv("ADMIN_LOCAL_EMAIL")) or os.getenv("AUTH_MODE") == "mock"
    admin_prefixes = (
        "/api/questions", "/api/facets", "/api/upload", "/api/source",
        "/api/pdf", "/api/ocr", "/api/export", "/api/import",
        "/api/exam-registrations", "/api/system/status",
    )
    if configured and request.url.path.startswith("/uploads/"):
        from platform_api import _auth
        try:
            _auth(request)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    if configured and any(request.url.path.startswith(prefix) for prefix in admin_prefixes):
        from platform_api import _auth, require_admin
        try:
            require_admin(_auth(request, request.method not in {"GET", "HEAD", "OPTIONS"}))
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    response=await call_next(request)
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control']='no-store, private'
        response.headers['X-Robots-Tag']='noindex, nofollow, noarchive'
    if request.url.path.startswith('/api/flag') or request.url.path=='/app':
        response.headers['X-Frame-Options']='DENY'
        response.headers['Permissions-Policy']='display-capture=()'
        response.headers['X-Content-Type-Options']='nosniff'
    return response

from security_boundary import SecurityBoundary
app.add_middleware(SecurityBoundary)


def row_to_exam_registration(row: sqlite3.Row) -> dict:
    item = dict(row)
    item['is_confirmed'] = bool(item.get('is_confirmed'))
    return item


def normalize_gmail_email(value: str) -> str:
    email = (value or '').strip().lower()
    if not re.fullmatch(r"[a-z0-9._%+\-]+@gmail\.com", email):
        raise ValueError('Only Gmail accounts are allowed for exam registration.')
    return email


def request_exam_registration_confirmation(email: str, *, full_name: str = '', exam_name: str = '', notes: str = '') -> dict:
    gmail = normalize_gmail_email(email)
    token = uuid.uuid4().hex
    now = time.time()
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM exam_registrations WHERE email = ? COLLATE NOCASE", (gmail,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO exam_registrations (full_name, email, phone, exam_name, exam_date, center_preference, status, notes, confirmation_token, is_confirmed, confirmation_sent_at, confirmed_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (full_name.strip(), gmail, '', exam_name.strip(), '', '', 'pending', notes.strip(), token, 0, now, 0, now, now),
            )
        else:
            conn.execute(
                "UPDATE exam_registrations SET full_name = ?, exam_name = ?, notes = ?, confirmation_token = ?, is_confirmed = 0, confirmation_sent_at = ?, updated_at = ? WHERE id = ?",
                (full_name.strip(), exam_name.strip(), notes.strip(), token, now, now, row['id']),
            )
        conn.commit()
    return {
        'email': gmail,
        'token': token,
        'confirmation_url': f'http://127.0.0.1:8001/api/exam-registrations/confirm?token={token}',
    }


def confirm_exam_registration(token: str) -> dict:
    if not token or not str(token).strip():
        raise ValueError('Confirmation token is required.')
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM exam_registrations WHERE confirmation_token = ?", (str(token).strip(),)).fetchone()
        if row is None:
            raise ValueError('Invalid or expired confirmation token.')
        now = time.time()
        conn.execute(
            "UPDATE exam_registrations SET is_confirmed = 1, confirmed_at = ?, status = 'pending', confirmation_token = '', updated_at = ? WHERE id = ?",
            (now, now, row['id']),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM exam_registrations WHERE id = ?", (row['id'],)).fetchone()
    return {'confirmed': True, 'email': updated['email'], 'token': str(token).strip()}


def list_exam_registrations(query: str | None = None) -> list[dict]:
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM exam_registrations ORDER BY id DESC"
        ).fetchall()
    items = [row_to_exam_registration(row) for row in rows]
    if not query:
        return items
    needle = query.strip().lower()
    if not needle:
        return items
    return [
        item for item in items
        if needle in " ".join([
            item.get('full_name', ''),
            item.get('email', ''),
            item.get('phone', ''),
            item.get('exam_name', ''),
            item.get('center_preference', ''),
            item.get('status', ''),
            item.get('notes', ''),
        ]).lower()
    ]


def create_exam_registration(payload: ExamRegistration | dict) -> dict:
    record = payload.model_dump() if isinstance(payload, ExamRegistration) else dict(payload)
    email = normalize_gmail_email(record.get('email') or '')
    first_name=(record.get('first_name') or '').strip();last_name=(record.get('last_name') or '').strip();dob=(record.get('date_of_birth') or '').strip()
    full_name=(record.get('full_name') or f'{first_name} {last_name}').strip()
    if not first_name or not last_name or not dob: raise ValueError('First name, last name, and date of birth are required.')
    if not record.get('is_confirmed') and not record.get('confirmation_token'):
        with closing(connect()) as conn:
            existing = conn.execute("SELECT * FROM exam_registrations WHERE email = ? COLLATE NOCASE", (email,)).fetchone()
        if existing is None or not bool(existing['is_confirmed']):
            raise ValueError('Only a confirmed Gmail account can register for the exam.')
    now = time.time()
    with closing(connect()) as conn:
        cur = conn.execute(
            "INSERT INTO exam_registrations (first_name, last_name, date_of_birth, full_name, email, phone, exam_name, exam_date, center_preference, status, notes, confirmation_token, is_confirmed, confirmation_sent_at, confirmed_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                first_name,last_name,dob,full_name,
                email,
                (record.get('phone') or '').strip(),
                (record.get('exam_name') or '').strip(),
                (record.get('exam_date') or '').strip(),
                (record.get('center_preference') or '').strip(),
                (record.get('status') or 'pending').strip() or 'pending',
                (record.get('notes') or '').strip(),
                (record.get('confirmation_token') or '').strip(),
                1 if record.get('is_confirmed') else 0,
                now,
                now if record.get('is_confirmed') else 0,
                now,
                now,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM exam_registrations WHERE id = ?", (cur.lastrowid,)).fetchone()
    return row_to_exam_registration(row)


def update_exam_registration(registration_id: int, payload: ExamRegistration | dict) -> dict:
    record = payload.model_dump() if isinstance(payload, ExamRegistration) else dict(payload)
    existing = None
    with closing(connect()) as conn:
        existing = conn.execute("SELECT * FROM exam_registrations WHERE id = ?", (registration_id,)).fetchone()
        if existing is None:
            raise HTTPException(404, "exam registration not found")
        email = normalize_gmail_email(record.get('email') or existing['email'])
        first_name=(record.get('first_name') or existing['first_name']).strip();last_name=(record.get('last_name') or existing['last_name']).strip();dob=(record.get('date_of_birth') or existing['date_of_birth']).strip()
        full_name=(record.get('full_name') or f'{first_name} {last_name}').strip()
        if not first_name or not last_name or not dob: raise ValueError('First name, last name, and date of birth are required.')
        if not bool(record.get('is_confirmed', existing['is_confirmed'])):
            raise ValueError('Only a confirmed Gmail account can update an exam registration.')
        conn.execute(
            "UPDATE exam_registrations SET first_name=?,last_name=?,date_of_birth=?,full_name = ?, email = ?, phone = ?, exam_name = ?, exam_date = ?, center_preference = ?, status = ?, notes = ?, confirmation_token = '', is_confirmed = 1, confirmed_at = ?, updated_at = ? WHERE id = ?",
            (
                first_name,last_name,dob,full_name,
                email,
                (record.get('phone') or '').strip(),
                (record.get('exam_name') or '').strip(),
                (record.get('exam_date') or '').strip(),
                (record.get('center_preference') or '').strip(),
                (record.get('status') or 'pending').strip() or 'pending',
                (record.get('notes') or '').strip(),
                time.time(),
                time.time(),
                registration_id,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM exam_registrations WHERE id = ?", (registration_id,)).fetchone()
    return row_to_exam_registration(row)


def delete_exam_registration(registration_id: int) -> dict:
    with closing(connect()) as conn:
        cur = conn.execute("DELETE FROM exam_registrations WHERE id = ?", (registration_id,))
        conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "exam registration not found")
    return {"deleted": registration_id}


def row_to_dict(row: sqlite3.Row) -> dict:
    item = dict(row)
    for field in JSON_FIELDS:
        try:
            item[field] = json.loads(item.get(field) or "[]")
        except (TypeError, ValueError):
            item[field] = []
    return item


def values_of(q: Question) -> list:
    payload = q.model_dump()
    # The statement is the editable canonical text. Rebuild text/math/chemistry
    # blocks on every save while retaining immutable visual source assets.
    payload["content_blocks"] = build_content_blocks(payload.get("statement", ""), payload.get("visual_assets", []))
    for field in JSON_FIELDS:
        payload[field] = json.dumps(payload[field], ensure_ascii=False)
    return [payload[f] for f in FIELDS]


EXPLANATION_LANGUAGES = {
    'en': {'name': 'English', 'native_name': 'English'},
    'te': {'name': 'Telugu', 'native_name': 'తెలుగు'},
}


def explanation_prose(value):
    """Unwrap model JSON containers without damaging TeX braces or Telugu text."""
    if value is None: return ''
    if isinstance(value, str):
        stripped=value.strip()
        if stripped.startswith(('"', '[', '{')):
            try:
                decoded=json.loads(stripped)
                if decoded != value: return explanation_prose(decoded)
            except (ValueError,TypeError): pass
        return value
    if isinstance(value, list): return '\n\n'.join(filter(None,(explanation_prose(x) for x in value)))
    if isinstance(value, dict):
        return '\n\n'.join(filter(None,(explanation_prose(value[k]) for k in ('text','content','explanation','description','reason','value','paragraphs') if k in value))) or '\n\n'.join(explanation_prose(x) for x in value.values())
    return str(value)


class ExplanationDistractor(BaseModel):
    @field_validator('option','reason',mode='before')
    @classmethod
    def prose(cls,value): return explanation_prose(value)
    option: str = ''
    reason: str = Field(description='Two or more sentences explaining the misconception and why this option does not answer the question.')


class StructuredExplanation(BaseModel):
    @field_validator('title','summary','concept','correct_answer','background','memory_tip',mode='before')
    @classmethod
    def prose(cls,value): return explanation_prose(value)

    @field_validator('steps','references',mode='before')
    @classmethod
    def prose_list(cls,value):
        if isinstance(value,str):
            try: value=json.loads(value)
            except ValueError: value=[value]
        return [explanation_prose(x) for x in (value or [])]
    title: str = Field(description='A clear, engaging lesson title.')
    summary: str = Field(description='A useful two-to-three sentence overview of what the student will understand.')
    concept: str = Field(description='A thorough concept explanation with intuition, definitions, and any relevant formula; at least two substantial paragraphs.')
    steps: list[str] = Field(description='Four to six complete reasoning steps that solve or analyse the question in sequence.')
    correct_answer: str = Field(description='A detailed explanation connecting the concept and reasoning directly to the stored correct answer.')
    distractors: list[ExplanationDistractor] = Field(description='One entry for every incorrect displayed option, or an empty list when the question has no options.')
    background: str = Field(description='Two or more sentences of useful prerequisite or real-world context.')
    memory_tip: str = Field(description='A memorable rule, analogy, or exam shortcut in one or two complete sentences.')
    references: list[str] = Field(description='Zero to three cautious textbook topics, chapters, channels, or search phrases; never invent links.')


def explanation_markdown(payload: dict) -> str:
    sections = [f"# {payload.get('title') or 'Concept explanation'}", payload.get('summary', '')]
    mapping = (
        ('Concept', payload.get('concept', '')),
        ('Step-by-step reasoning', '\n'.join(f"{index}. {step}" for index, step in enumerate(payload.get('steps') or [], 1))),
        ('Why this answer is correct', payload.get('correct_answer', '')),
        ('Why the other options are less likely', '\n'.join(
            f"- **{item.get('option', 'Option')}**: {item.get('reason', '')}" for item in payload.get('distractors') or []
        )),
        ('Background', payload.get('background', '')),
        ('Memory tip', payload.get('memory_tip', '')),
        ('Relevant references', '\n'.join(f"- {item}" for item in payload.get('references') or [])),
    )
    for heading, content in mapping:
        if str(content or '').strip():
            sections.extend((f"## {heading}", str(content).strip()))
    return '\n\n'.join(part for part in sections if str(part).strip())


def decode_explanation(value: str) -> tuple[str, Optional[dict]]:
    try:
        cleaned=re.sub(r'^```(?:json)?\s*|\s*```$', '', value.strip(),flags=re.I)
        payload=json.loads(cleaned)
        if isinstance(payload,str): payload=json.loads(payload)
        if isinstance(payload,dict) and isinstance(payload.get('structured'),dict):payload=payload['structured']
        if isinstance(payload, dict) and payload.get('title') and payload.get('concept'):
            validated = StructuredExplanation.model_validate(payload).model_dump()
            return explanation_markdown(validated), validated
    except (TypeError, ValueError):
        pass
    return value, None


def normalize_explanation_language(language: str) -> str:
    normalized = (language or 'en').strip().lower().replace('_', '-').split('-', 1)[0]
    if normalized not in EXPLANATION_LANGUAGES:
        raise HTTPException(400, f"Unsupported explanation language: {language}")
    return normalized


def get_cached_question_explanation(question_id: int, language: str = 'en') -> Optional[dict]:
    language = normalize_explanation_language(language)
    with closing(connect()) as conn:
        row = conn.execute(
            "SELECT question_id, language, explanation, liked, created_at, updated_at FROM question_explanation_translations WHERE question_id = ? AND language = ?",
            (question_id, language),
        ).fetchone()
        if row is None and language == 'en':
            row = conn.execute(
                "SELECT question_id, 'en' language, explanation, liked, created_at, updated_at FROM question_explanations WHERE question_id = ?",
                (question_id,),
            ).fetchone()
    if row is None:
        return None
    markdown, structured = decode_explanation(row["explanation"])
    return {
        "question_id": row["question_id"],
        "language": row["language"],
        "explanation": markdown,
        "structured": structured,
        "liked": bool(row["liked"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def save_question_explanation(question_id: int, explanation: str, *, language: str = 'en', liked: bool = True, structured: Optional[dict] = None, expected_question: Optional[dict] = None) -> dict:
    text = (explanation or '').strip()
    if not text:
        raise ValueError('Explanation text is required before caching.')
    validated_structured = StructuredExplanation.model_validate(structured).model_dump() if structured else None
    stored_text = json.dumps(validated_structured, ensure_ascii=False) if validated_structured else text
    now = time.time()
    language = normalize_explanation_language(language)
    with closing(connect()) as conn:
        if expected_question is not None:
            # Serialize with question edits so a correction cannot invalidate the
            # cache and then have the previous AI response resurrect stale text.
            conn.execute('UPDATE questions SET id=id WHERE id=?', (question_id,))
            current = conn.execute('SELECT * FROM questions WHERE id=?', (question_id,)).fetchone()
            if current is None:
                raise HTTPException(404, 'question not found')
            current = row_to_dict(current)
            if any(current.get(key) != expected_question.get(key) for key in ('statement', 'options', 'answer', 'solution', 'visual_assets')):
                raise HTTPException(409, 'This question changed while the explanation was generated. Please retry.')
        conn.execute(
            "INSERT INTO question_explanation_translations (question_id, language, explanation, liked, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(question_id,language) DO UPDATE SET explanation=excluded.explanation,liked=excluded.liked,updated_at=excluded.updated_at",
            (question_id, language, stored_text, 1 if liked else 0, now, now),
        )
        conn.commit()
    return {"question_id": question_id, "language": language, "explanation": explanation_markdown(validated_structured) if validated_structured else text, "structured": validated_structured, "liked": bool(liked)}


def cache_generated_explanations(conn,question_id,generated):
    """Retain legacy bilingual output, then queue missing explanations separately."""
    now=time.time()
    for language,field in (('en','explanation_en'),('te','explanation_te')):
        text=(getattr(generated,field,'') or '').strip()
        if not text:continue
        conn.execute("INSERT INTO question_explanation_translations(question_id,language,explanation,liked,created_at,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(question_id,language) DO UPDATE SET explanation=excluded.explanation,liked=excluded.liked,updated_at=excluded.updated_at",(question_id,language,text,1,now,now))
    from explanation_jobs import enqueue
    enqueue(conn,question_id)


def _snapshot(conn: sqlite3.Connection, qid: int, reason: str) -> None:
    row = conn.execute("SELECT * FROM questions WHERE id = ?", (qid,)).fetchone()
    if row is None:
        return
    version = conn.execute(
        "SELECT COALESCE(MAX(version_no), 0) + 1 n FROM question_versions WHERE question_id = ?", (qid,)
    ).fetchone()["n"]
    conn.execute(
        "INSERT INTO question_versions(question_id, version_no, payload_json, reason, created_at) VALUES(?,?,?,?,?)",
        (qid, version, json.dumps(row_to_dict(row), ensure_ascii=False), reason, time.time()),
    )


def _source_mime(filename: str, declared: str | None) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext == ".pdf":
        return "application/pdf"
    guess = declared or mimetypes.guess_type(filename or "")[0] or "application/octet-stream"
    if guess == "image/jpg":
        return "image/jpeg"
    return guess


def _office_xml_text(xml_bytes: bytes, tag_name: str = "t") -> str:
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return ""
    texts: list[str] = []
    for node in root.iter():
        if node.tag.endswith(f"}}{tag_name}") or node.tag == tag_name:
            text = (node.text or '').strip()
            if text:
                texts.append(text)
    return "\n".join(texts)


def _text_source_preview(filename: str, content: bytes) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext == ".ipynb":
        try:
            data = json.loads(content.decode("utf-8", errors="replace"))
            cells = data.get("cells", [])
            parts = []
            for cell in cells:
                src = cell.get("source", [])
                if isinstance(src, list):
                    parts.extend(str(item) for item in src)
                elif isinstance(src, str):
                    parts.append(src)
            return "\n".join(parts)
        except Exception:
            return content.decode("utf-8", errors="replace")
    if ext == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                document = zf.read("word/document.xml")
                return _office_xml_text(document, "t")
        except Exception:
            pass
    if ext == ".pptx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                texts = []
                for name in zf.namelist():
                    if name.startswith("ppt/slides/") and name.endswith(".xml"):
                        texts.append(_office_xml_text(zf.read(name), "t"))
                return "\n".join(text for text in texts if text)
        except Exception:
            pass
    if ext == ".xlsx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                shared = ""
                if "xl/sharedStrings.xml" in zf.namelist():
                    shared = zf.read("xl/sharedStrings.xml")
                texts = []
                for name in zf.namelist():
                    if name.startswith("xl/worksheets/") and name.endswith(".xml"):
                        xml = zf.read(name)
                        root = ET.fromstring(xml)
                        ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
                              "b": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
                        for cell in root.findall(".//a:c", ns):
                            value = cell.find("a:v", ns)
                            if value is not None and value.text:
                                texts.append(value.text)
                return "\n".join(texts)
        except Exception:
            pass
    if ext == ".odt":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                if "content.xml" in zf.namelist():
                    return _office_xml_text(zf.read("content.xml"), "p")
        except Exception:
            pass
    if ext in {".txt", ".md", ".csv", ".json", ".log", ".html", ".xml", ".rtf"}:
        return content.decode("utf-8", errors="replace")
    return content.decode("utf-8", errors="replace")


def _validate_source(content: bytes, filename: str, mime_type: str) -> None:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_SOURCE_EXT:
        raise HTTPException(400, f"unsupported source type: {ext or 'unknown'}")
    if ext == ".pdf":
        if not content.startswith(b"%PDF"):
            raise HTTPException(400, "file extension is .pdf but content is not a PDF")
        return
    if ext in ALLOWED_TEXT_EXT | {".doc", ".docx", ".odt", ".ppt", ".pptx", ".xls", ".xlsx"}:
        return
    try:
        from PIL import Image
        with Image.open(io.BytesIO(content)) as im:
            im.verify()
    except Exception as exc:
        raise HTTPException(400, "uploaded image is not decodable") from exc
    if not mime_type.startswith("image/"):
        raise HTTPException(400, "expected an image MIME type")


def _record_source(content: bytes, filename: str, mime_type: str, page_count: int) -> dict:
    sha = hashlib.sha256(content).hexdigest()
    with closing(connect()) as conn:
        existing = conn.execute("SELECT * FROM source_documents WHERE sha256 = ?", (sha,)).fetchone()
        if existing:
            # Deduplicated DB records may outlive a local disk or data-directory move.
            record=dict(existing)
            if not os.path.isfile(record['local_path']):
                path=os.path.join(SOURCE_DIR, record['id'] + (Path(filename).suffix.lower() or '.pdf'))
                with open(path,'wb') as fh: fh.write(content)
                conn.execute('UPDATE source_documents SET local_path=? WHERE id=?',(path,record['id']));conn.commit()
                record['local_path']=path
            return record
        doc_id = uuid.uuid4().hex
        ext = Path(filename).suffix.lower() or (".pdf" if mime_type == "application/pdf" else ".bin")
        stored = f"{doc_id}{ext}"
        path = os.path.join(SOURCE_DIR, stored)
        with open(path, "wb") as fh:
            fh.write(content)
        conn.execute(
            "INSERT INTO source_documents(id,filename,sha256,mime_type,page_count,local_path,created_at) VALUES(?,?,?,?,?,?,?)",
            (doc_id, filename, sha, mime_type, page_count, path, time.time()),
        )
        conn.commit()
    return {"id": doc_id, "filename": filename, "sha256": sha, "mime_type": mime_type,
            "page_count": page_count, "local_path": path}


def _record_run(source_document_id: str, provider: str, model: str, status: str, usage: dict, warnings: list[str]) -> str:
    run_id = uuid.uuid4().hex
    with closing(connect()) as conn:
        conn.execute(
            "INSERT INTO extraction_runs(id,source_document_id,provider,model,status,usage_json,warnings_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (run_id, source_document_id, provider, model, status, json.dumps(usage), json.dumps(warnings), time.time()),
        )
        conn.commit()
    return run_id


def _bind_extraction_prompts(run_id: str, data: dict, model: str) -> None:
    llm = data.get('llm') or {}
    if not llm.get('transcription_prompt_version_id'):
        return
    from prompt_registry import bind_prompt, resolve_active_prompt
    with closing(connect()) as conn:
        for key, prefix in (('DIGITIZE_TRANSCRIBE','transcription'),('DIGITIZE_VERIFY','verification')):
            resolved=resolve_active_prompt(key,conn=conn)
            expected=llm.get(f'{prefix}_prompt_version_id')
            if resolved['id'] != expected:
                row=conn.execute('SELECT v.*,d.prompt_key prompt_key FROM prompt_versions v JOIN prompt_definitions d ON d.id=v.prompt_definition_id WHERE v.id=?',(expected,)).fetchone()
                if row:resolved={**dict(row),'key':row['prompt_key']}
            bind_prompt(conn,run_type='EXTRACTION',run_id=run_id,resolved=resolved,model=model,parameters={'verification_enabled':bool(llm.get('verification'))})
        conn.commit()


def _decorate_drafts(data: dict, source: dict, run_id: str) -> dict:
    for q in data.get("questions", []):
        q["source_document_id"] = source["id"]
        q["source_document_sha256"] = source["sha256"]
        q["source_page"] = int(q.get("page") or 0)
        q.setdefault("source_bbox", [])
        q.setdefault("source_segments", [])
        q["extraction_run_id"] = run_id
        q.setdefault("extraction_provider", data.get("llm", {}).get("provider", "local"))
        q.setdefault("extraction_model", data.get("llm", {}).get("model", ""))
        q["transcription_prompt_version_id"] = (data.get("llm") or {}).get("transcription_prompt_version_id")
        q["verification_prompt_version_id"] = (data.get("llm") or {}).get("verification_prompt_version_id")
        q.setdefault("verification_status", "REVIEW" if data.get("llm") else "UNVERIFIED")
        q.setdefault("confidence", 0.0)
        q.setdefault("verification_issues", [])
        q.setdefault("uncertainties", [])
        q.setdefault("visual_assets", [])
        q.setdefault("math_evidence", [])
        q.setdefault("content_blocks", build_content_blocks(q.get("statement", ""), q.get("visual_assets", [])))
    data["source_document"] = {k: source[k] for k in ("id", "filename", "sha256", "mime_type", "page_count")}
    data["extraction_run_id"] = run_id
    return data


@app.get("/api/questions")
def list_questions(
    q: Optional[str] = None,
    subject: Optional[str] = None,
    chapter: Optional[str] = None,
    difficulty: Optional[str] = None,
    qtype: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
):
    where, params = [], []
    if q:
        like = f"%{q}%"
        where.append("(statement LIKE ? OR solution LIKE ? OR tags LIKE ? OR topic LIKE ? OR chapter LIKE ? OR options LIKE ?)")
        params += [like] * 6
    for column, value in (("subject", subject), ("chapter", chapter), ("difficulty", difficulty), ("qtype", qtype)):
        if value:
            where.append(f"{column} = ?")
            params.append(value)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    with closing(connect()) as conn:
        total = conn.execute(f"SELECT COUNT(*) c FROM questions{clause}", params).fetchone()["c"]
        rows = conn.execute(
            f"SELECT * FROM questions{clause} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [max(1, min(limit, 1000)), max(0, offset)],
        ).fetchall()
    return {"total": total, "items": [row_to_dict(r) for r in rows]}


@app.get("/api/questions/{qid}")
def get_question(qid: int):
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM questions WHERE id = ?", (qid,)).fetchone()
    if row is None:
        raise HTTPException(404, "question not found")
    return row_to_dict(row)


@app.get("/api/questions/{qid}/explain")
def explain_question(qid: int, language: str = 'en'):
    return _generate_question_explanation(qid, language)


def _generate_question_explanation(qid: int, language: str = 'en', student_user_id=None):
    """Cache-only read; a learner request never invokes Gemini or spends quota."""
    language=normalize_explanation_language(language)
    cached=get_cached_question_explanation(qid,language)
    if cached and cached.get('liked') and str(cached.get('explanation') or '').strip():
        return {"explanation":cached['explanation'],"structured":cached.get('structured'),"language":language,"cached":True,"pending":False,"status":"READY"}
    from explanation_jobs import enqueue
    with closing(connect()) as conn:
        job=enqueue(conn,qid)
        conn.commit()
    failed=job['status']=='FAILED'
    message=('వివరణ సిద్ధం కావడానికి మరికొంత సమయం అవసరం. పరిష్కారాన్ని ఇప్పుడే చూడవచ్చు.' if failed else 'వివరణ బ్యాచ్ జాబ్‌లో సిద్ధమవుతోంది. పరిష్కారాన్ని ఇప్పుడే చూడవచ్చు.') if language=='te' else ('The explanation needs administrator attention. The worked solution is available now.' if failed else 'Explanation preparing in the scheduled batch. The worked solution is available now.')
    return {"explanation":"","message":message,"structured":None,"language":language,"cached":False,"pending":not failed,"status":job['status']}


@app.post("/api/questions/{qid}/explain/like")
async def like_question_explanation(qid: int, request: Request):
    data = await request.json()
    if not isinstance(data,dict):
        raise HTTPException(400, 'Expected an explanation acknowledgement.')
    language = normalize_explanation_language(str(data.get('language') or 'en'))
    # Explanations are authored and cached by the scheduled worker. This legacy
    # action may acknowledge a current cache entry, but never accept browser text
    # as new cache content (including a pending message or a stale open dialog).
    with closing(connect()) as conn:
        if not conn.execute('UPDATE questions SET id=id WHERE id=?',(qid,)).rowcount:
            raise HTTPException(404, 'question not found')
        table='question_explanation_translations'
        row=conn.execute('SELECT explanation,liked FROM question_explanation_translations WHERE question_id=? AND language=?',(qid,language)).fetchone()
        if row is None and language=='en':
            table='question_explanations'
            row=conn.execute('SELECT explanation,liked FROM question_explanations WHERE question_id=?',(qid,)).fetchone()
        if row is None or not row['explanation'].strip():
            raise HTTPException(409, 'The explanation is still being prepared. Reload when the cached explanation is ready.')
        explanation,structured=decode_explanation(row['explanation'])
        if 'explanation' in data and (not isinstance(data['explanation'],str) or data['explanation'].strip()!=explanation.strip()):
            raise HTTPException(409, 'This explanation has changed. Reload the current cached explanation.')
        if data.get('structured') is not None and data['structured']!=structured:
            raise HTTPException(409, 'This explanation has changed. Reload the current cached explanation.')
        if not row['liked']:
            if table=='question_explanation_translations':
                conn.execute('UPDATE question_explanation_translations SET liked=1,updated_at=? WHERE question_id=? AND language=?',(time.time(),qid,language))
            else:
                conn.execute('UPDATE question_explanations SET liked=1,updated_at=? WHERE question_id=?',(time.time(),qid))
        conn.commit()
    return {"saved": True, "cached": True, "question_id": qid, "language": language, "explanation": explanation, "structured": structured}


@app.get("/api/questions/{qid}/versions")
def get_versions(qid: int):
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT version_no,payload_json,reason,created_at FROM question_versions WHERE question_id=? ORDER BY version_no DESC", (qid,)
        ).fetchall()
    return [{"version_no": r["version_no"], "payload": json.loads(r["payload_json"]),
             "reason": r["reason"], "created_at": r["created_at"]} for r in rows]


@app.post("/api/questions")
def create_question(q: Question):
    now = time.time()
    cols = ", ".join(FIELDS)
    marks = ", ".join(["?"] * len(FIELDS))
    with closing(connect()) as conn:
        cur = conn.execute(
            f"INSERT INTO questions ({cols}, created_at, updated_at) VALUES ({marks}, ?, ?)",
            values_of(q) + [now, now],
        )
        qid = cur.lastrowid
        conn.commit()
    return get_question(qid)


@app.put("/api/questions/{qid}")
def update_question(qid: int, q: Question, request: Request = None):
    from platform_api import _auth,require_admin
    user=_auth(request,True) if request is not None else None
    if user:require_admin(user)
    assignments = ", ".join(f"{f} = ?" for f in FIELDS)
    with closing(connect()) as conn:
        existing=conn.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
        if existing is None:
            raise HTTPException(404, "question not found")
        previous=row_to_dict(existing)
        from correction_sync import prepare,propagate
        plans=prepare(conn,qid) if user else []
        if "verification_status" not in q.model_fields_set:q.verification_status=previous["verification_status"]
        if previous.get('source_type')=='AI_GENERATED':
            for field in ('source_type','generation_run_id','generation_provider','generation_model','generation_prompt_version','generation_prompt','generation_metadata'):
                setattr(q,field,previous[field])
            q.generation_fingerprint=fingerprint(q.statement)
        if q.statement!=previous['statement'] or q.visual_assets!=previous.get('visual_assets',[]):
            q.content_blocks=build_content_blocks(q.statement,q.visual_assets)
        _snapshot(conn, qid, "before edit")
        if any(getattr(q,key)!=previous.get(key) for key in ('statement','options','answer','solution','visual_assets')):
            conn.execute('DELETE FROM question_explanations WHERE question_id=?',(qid,))
            conn.execute('DELETE FROM question_explanation_translations WHERE question_id=?',(qid,))
        conn.execute(
            f"UPDATE questions SET {assignments}, updated_at = ? WHERE id = ?",
            values_of(q) + [time.time(), qid],
        )
        updated=row_to_dict(conn.execute('SELECT * FROM questions WHERE id=?',(qid,)).fetchone())
        if user:propagate(conn,previous,updated,user['id'],plans)
        from explanation_jobs import enqueue
        enqueue(conn,qid)
        conn.commit()
    return get_question(qid)


@app.delete("/api/questions/{qid}")
def delete_question(qid: int):
    with closing(connect()) as conn:
        conn.execute("DELETE FROM question_versions WHERE question_id = ?", (qid,))
        cur = conn.execute("DELETE FROM questions WHERE id = ?", (qid,))
        conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "question not found")
    return {"deleted": qid}


@app.get("/api/facets")
def facets():
    with closing(connect()) as conn:
        def distinct(column: str) -> list[str]:
            rows = conn.execute(f"SELECT DISTINCT {column} v FROM questions WHERE {column} != '' ORDER BY v").fetchall()
            return [r["v"] for r in rows]
        return {"subjects": distinct("subject"), "chapters": distinct("chapter")}


@app.post("/api/ai/prompt-preview")
def preview_ai_generation(payload: GenerationRequest, request: Request):
    from platform_api import _auth, require_admin
    require_admin(_auth(request, True))
    return {"effective_prompt": public_prompt_preview(payload), "model": os.getenv("VERTEX_MODEL_PRIMARY", "gemini-3.5-flash")}

@app.post("/api/ai/prompt-guidance")
def guide_ai_generation(payload: PromptGuidanceRequest, request: Request):
    from platform_api import _auth, require_admin
    require_admin(_auth(request,True))
    try:
        guidance,model=generate_prompt_guidance(payload)
        return {**guidance.model_dump(),"model":model}
    except (ValueError,RuntimeError) as exc:raise HTTPException(422,str(exc)) from exc


@app.get("/api/ai/runs")
def list_ai_generation_runs(request: Request, response: Response, q: str = Query('', max_length=200),
                            subject: str = Query('', max_length=200), level: str = Query('', max_length=200),
                            difficulty: str = Query('', max_length=30), status: str = Query('', max_length=40),
                            offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100)):
    from platform_api import _auth, require_admin
    require_admin(_auth(request))
    clauses, params = ["status!='DELETED'"], []
    if q.strip():
        clauses.append("(LOWER(exam_name) LIKE ? OR LOWER(subject) LIKE ? OR LOWER(topic) LIKE ? OR LOWER(chapter) LIKE ?)")
        params.extend(['%'+q.strip().lower()+'%']*4)
    for column, value in [('subject',subject),('level',level),('difficulty',difficulty),('status',status)]:
        if value.strip():
            clauses.append(f'LOWER({column})=?')
            params.append(value.strip().lower())
    where = ' WHERE '+' AND '.join(clauses) if clauses else ''
    with closing(connect()) as conn:
        total = conn.execute('SELECT COUNT(*) n FROM ai_generation_runs'+where, params).fetchone()['n']
        rows=conn.execute("SELECT id,exam_name,subject,level,difficulty,topic,requested_count,generated_count,accepted_count,rejected_count,model,status,error_message,created_at FROM ai_generation_runs"+where+" ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?", (*params,limit,offset)).fetchall()
    response.headers['X-Total-Count'] = str(total)
    return [dict(row) for row in rows]


@app.get("/api/ai/runs/{run_id}")
def get_ai_generation_run(run_id: str, request: Request):
    from platform_api import _auth, require_admin
    require_admin(_auth(request))
    with closing(connect()) as conn: row=conn.execute("SELECT * FROM ai_generation_runs WHERE id=?",(run_id,)).fetchone()
    if not row: raise HTTPException(404,"Generation run not found")
    item=dict(row)
    for field in ("metadata_json","request_json","output_json","usage_json"):
        try:item[field.removesuffix("_json")]=json.loads(item.pop(field) or "{}")
        except ValueError:item[field.removesuffix("_json")]={}
    from correction_sync import hydrate_run
    with closing(connect()) as conn:hydrate_run(conn,item)
    return item


@app.post("/api/ai/generate")
def generate_ai_questions(payload: GenerationRequest, request: Request):
    from platform_api import _auth, require_admin
    require_admin(_auth(request, True))
    return generate_ai_questions_core(payload)


def generate_ai_questions_core(payload: GenerationRequest):
    """Shared authoring pipeline; callers must authorize before invoking it."""
    run_id=uuid.uuid4().hex;now=time.time();metadata={"exam_type":payload.exam_type,"level":payload.level,"subtopic":payload.subtopic,"difficulty":payload.difficulty,"question_type":payload.question_type,"marks":payload.marks,"language":payload.language,"tags":payload.tags,"extra_metadata":payload.extra_metadata}
    with closing(connect()) as conn:
        conn.execute("INSERT INTO ai_generation_runs(id,exam_name,exam_type,level,subject,chapter,topic,subtopic,difficulty,question_type,requested_count,language,system_prompt_version,generation_prompt,syllabus,metadata_json,request_json,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'RUNNING',?)",(run_id,payload.exam_name,payload.exam_type,payload.level,payload.subject,payload.chapter,payload.topic,payload.subtopic,payload.difficulty,payload.question_type,payload.count,payload.language,SYSTEM_PROMPT_VERSION,payload.generation_prompt,payload.syllabus,json.dumps(metadata,ensure_ascii=False),payload.model_dump_json(),now));conn.commit()
    try:
        from llm_generate import PartialGenerationError
        failures=[]
        def collect_generation(request):
            from generation_control import pause_check
            def paused():
                with closing(connect()) as control_conn:
                    row=control_conn.execute('SELECT status FROM ai_generation_runs WHERE id=?',(run_id,)).fetchone()
                return not row or row['status'] in {'PAUSING','DELETED'}
            token=pause_check.set(paused)
            try:
                return generate_questions(request),None
            except PartialGenerationError as exc:
                return (exc.batch,exc.usage,exc.model),exc
            except Exception as exc:
                return None,exc
            finally:
                pause_check.reset(token)
        manual_batch_size=max(1,min(10,int(os.getenv('AI_INTERACTIVE_BATCH_SIZE','5'))))
        if payload.count>manual_batch_size and not payload.extra_metadata.get('program_exam_job_id'):
            from concurrent.futures import ThreadPoolExecutor
            # At most one wave of four workers. Queuing additional waves would
            # multiply each worker's bounded deadline beyond the HTTP budget.
            manual_batch_size=max(manual_batch_size,(payload.count+3)//4)
            counts=[manual_batch_size]*(payload.count//manual_batch_size)
            if payload.count%manual_batch_size:counts.append(payload.count%manual_batch_size)
            requests=[payload.model_copy(update={'count':count,'generation_prompt':payload.generation_prompt+f'\n\nINTERACTIVE BATCH {index+1} OF {len(counts)}: use a distinct mix of concepts and scenarios.'}) for index,count in enumerate(counts)]
            with ThreadPoolExecutor(max_workers=min(4,len(requests)),thread_name_prefix='question-batch') as pool:
                outcomes=list(pool.map(collect_generation,requests))
            batches=[result for result,error in outcomes if result is not None]
            failures=[error for result,error in outcomes if error is not None]
            if not batches:raise failures[0]
            batch=batches[0][0].model_copy(update={'questions':[question for result,_,_ in batches for question in result.questions]})
            usage=dict(batches[0][1]);usage['interactive_batches']=len(requests)
            for key in ('prompt_token_count','candidates_token_count','total_token_count','provider_calls'):
                usage[key]=sum(int(details.get(key,0) or 0) for _,details,_ in batches)
            model=batches[0][2]
        else:
            result,error=collect_generation(payload)
            if result is None:raise error
            batch,usage,model=result
            if error is not None:failures.append(error)
        warning=(f'{len(batch.questions)} of {payload.count} questions completed. Completed questions are available for review; remaining questions were not generated.' if failures else '')
        if failures:
            usage={**usage,'partial':True,'failed_batches':len(failures),'failure_types':[type(error).__name__ for error in failures]}
        review=[];rejected=0;seen=set()
        for generated in batch.questions:
            if generated.visual_required and generated.visual_spec:
                from visual_renderer import render_visual_spec,render_visual_panels
                spec=generated.visual_spec.model_dump();url=render_visual_spec(spec,UPLOAD_DIR);panels=render_visual_panels(spec,UPLOAD_DIR)
                original_options={option.label:option.text for option in generated.options};generated.metadata={**generated.metadata,"visual_option_text":original_options,"visual_panel_assets":panels}
                generated.options=[type(option)(label=option.label,text=f"![Option {option.label} visual diagram]({panels[option.label]})") for option in generated.options]
                generated.visual_assets=[{"type":generated.visual_type or "diagram","asset":panels["question"],"description":"AI-generated question figure"},{"type":"answer_figures","asset":url,"description":"AI-generated question with answer figures"}];generated.content_blocks=build_content_blocks(generated.statement,generated.visual_assets)
            fp=fingerprint(generated.statement)
            with closing(connect()) as conn: duplicate=conn.execute("SELECT 1 FROM questions WHERE generation_fingerprint=? OR lower(trim(statement))=lower(trim(?)) LIMIT 1",(fp,generated.statement)).fetchone()
            if duplicate or fp in seen: rejected+=1;continue
            seen.add(fp);item=generated.model_dump();item["review_index"]=len(review);item["fingerprint"]=fp;review.append(item)
        with closing(connect()) as conn:
            prompt_version=f"QUESTION_GENERATE:v{usage.get('prompt_version_id','')}"
            conn.execute("UPDATE ai_generation_runs SET generated_count=?,rejected_count=?,model=?,system_prompt_version=?,output_json=?,usage_json=?,error_message=?,status=CASE WHEN status='PAUSING' THEN 'PAUSED' ELSE 'REVIEW_REQUIRED' END WHERE id=? AND status!='DELETED'",(len(batch.questions),rejected,model,prompt_version,json.dumps({"questions":review},ensure_ascii=False),json.dumps(usage),warning,run_id))
            from prompt_registry import bind_prompt
            prompt_row=(conn.execute('SELECT v.*,d.prompt_key FROM prompt_versions v JOIN prompt_definitions d ON d.id=v.prompt_definition_id WHERE v.id=?',(usage.get('prompt_version_id'),)).fetchone()
                        if usage.get('prompt_version_id') else None)
            if prompt_row:bind_prompt(conn,run_type='QUESTION_GENERATION',run_id=run_id,resolved={**dict(prompt_row),'key':prompt_row['prompt_key']},model=model,parameters={'requested_count':payload.count})
            conn.commit()
        return {"run_id":run_id,"exam":payload.exam_name,"subject":payload.subject,"requested":payload.count,"generated":len(batch.questions),"accepted":0,"rejected":rejected,"review_required":len(review),"model":model,"questions":review,"saved":False,"partial":bool(failures),"warning":warning}
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception('Question generation run %s failed type=%s',run_id,type(exc).__name__)
        with closing(connect()) as conn:conn.execute("UPDATE ai_generation_runs SET status=CASE WHEN status='PAUSING' THEN 'PAUSED' ELSE 'FAILED' END,error_message=? WHERE id=? AND status!='DELETED'",(str(exc)[:2000],run_id));conn.commit()
        if isinstance(exc,(ValueError,RuntimeError)): raise HTTPException(422,str(exc)) from exc
        raise HTTPException(502,"Question generation failed") from exc


@app.post("/api/ai/runs/{run_id}/regenerate")
def regenerate_ai_generation_run(run_id: str, request: Request):
    from platform_api import _auth, require_admin
    require_admin(_auth(request, True))
    with closing(connect()) as conn: row=conn.execute("SELECT request_json,status FROM ai_generation_runs WHERE id=?",(run_id,)).fetchone()
    if not row: raise HTTPException(404,"Generation run not found")
    if row['status'] in {'RUNNING','PAUSING','DELETED'}:raise HTTPException(409,'This generation cannot be regenerated in its current state')
    try: payload=GenerationRequest.model_validate_json(row["request_json"])
    except Exception as exc: raise HTTPException(409,"Stored generation request is invalid") from exc
    return generate_ai_questions(payload,request)


@app.post('/api/ai/runs/{run_id}/pause')
def pause_ai_generation_run(run_id: str, request: Request):
    from platform_api import _auth, require_admin
    require_admin(_auth(request, True))
    with closing(connect()) as conn:
        row=conn.execute('SELECT status,request_json,created_at FROM ai_generation_runs WHERE id=?',(run_id,)).fetchone()
        if not row:raise HTTPException(404,'Generation run not found')
        if json.loads(row['request_json'] or '{}').get('extra_metadata',{}).get('program_exam_job_id'):raise HTTPException(409,'Manage this generation from its program exam job')
        if row['status'] not in {'RUNNING','PAUSING','PAUSED'}:raise HTTPException(409,'This generation is no longer running')
        # Interactive provider work has a <=180s deadline. A 15-minute-old
        # request is interrupted, not live work; make its checkpoint recoverable.
        if row['created_at']<time.time()-900:
            conn.execute("UPDATE ai_generation_runs SET status='PAUSED' WHERE id=? AND status IN ('RUNNING','PAUSING')",(run_id,))
        else:
            conn.execute("UPDATE ai_generation_runs SET status='PAUSING' WHERE id=? AND status='RUNNING'",(run_id,))
        conn.commit()
    return {'message':'Pause requested. In-flight AI calls may finish; completed questions will be preserved.'}


@app.post('/api/ai/runs/{run_id}/resume')
def resume_ai_generation_run(run_id: str, request: Request):
    from platform_api import _auth, require_admin
    require_admin(_auth(request, True))
    with closing(connect()) as conn:
        row=conn.execute('SELECT * FROM ai_generation_runs WHERE id=?',(run_id,)).fetchone()
    if not row:raise HTTPException(404,'Generation run not found')
    if row['status'] not in {'PAUSED','FAILED','REVIEW_REQUIRED','SAVED'}:raise HTTPException(409,'Only stopped or incomplete generations can be continued')
    remaining=row['requested_count']-row['generated_count']
    if remaining<=0:raise HTTPException(409,'All requested questions are ready; review this generation')
    payload=GenerationRequest.model_validate_json(row['request_json'])
    if payload.extra_metadata.get('program_exam_job_id'):raise HTTPException(409,'Resume this generation from its program exam job')
    prior=json.loads(row['output_json'] or '{}').get('questions',[])
    payload=payload.model_copy(update={'count':remaining,'generation_prompt':payload.generation_prompt+'\nContinue the remaining questions in a new batch. Do not repeat these completed questions or their concepts:\n'+'\n'.join(q['statement'] for q in prior)})
    with closing(connect()) as conn:
        claimed=conn.execute("UPDATE ai_generation_runs SET status='CONTINUED' WHERE id=? AND status=?",(run_id,row['status'])).rowcount
        conn.commit()
    if not claimed:raise HTTPException(409,'This paused generation has already been continued')
    return generate_ai_questions_core(payload)


@app.delete('/api/ai/runs/{run_id}')
def delete_ai_generation_run(run_id: str, request: Request):
    from platform_api import _auth, require_admin
    require_admin(_auth(request, True))
    # Retain provenance and foreign-key references for bank questions and papers.
    with closing(connect()) as conn:
        row=conn.execute('SELECT status FROM ai_generation_runs WHERE id=?',(run_id,)).fetchone()
        if not row:raise HTTPException(404,'Generation run not found')
        if row['status'] in {'RUNNING','PAUSING'}:raise HTTPException(409,'Pause generation and wait for in-flight calls to finish before deleting')
        conn.execute("UPDATE ai_generation_runs SET status='DELETED' WHERE id=?",(run_id,));conn.commit()
    return {'message':'Saved generation removed from the list. Bank questions and exam papers are unchanged.'}


@app.post("/api/ai/runs/{run_id}/save")
def save_ai_generation_run(run_id: str, payload: dict, request: Request):
    from platform_api import _auth, require_admin
    require_admin(_auth(request, True))
    from ai_review import SaveSelection, BatchSelection, save_batches
    with closing(connect()) as conn: row=conn.execute('SELECT output_json FROM ai_generation_runs WHERE id=?',(run_id,)).fetchone()
    if not row:raise HTTPException(404,'Generation run not found')
    items=json.loads(row['output_json'] or '{}').get('questions',[])
    try:data=SaveSelection(batches=[BatchSelection(run_id=run_id,indices=payload.get('indices',list(range(len(items)))))],reviewed=True)
    except Exception as exc:raise HTTPException(422,'Select valid question indices') from exc
    result=save_batches(data)
    return {'run_id':run_id,'saved_count':result['saved_count'],'rejected_count':result['already_saved_count'],'questions':[get_question(r['question_id']) for r in result['items'] if r['status']=='SAVED'],'items':result['items']}


@app.put("/api/ai/questions/{question_id}/status")
def set_ai_question_status(question_id: int, payload: dict, request: Request):
    from platform_api import _auth, require_admin
    require_admin(_auth(request, True));status=str(payload.get("status","")).upper()
    if status not in {"APPROVED","REJECTED","REVIEW_REQUIRED"}: raise HTTPException(400,"Invalid review status")
    with closing(connect()) as conn:
        cur=conn.execute("UPDATE questions SET verification_status=?,updated_at=? WHERE id=? AND source_type='AI_GENERATED'",(status,time.time(),question_id));conn.commit()
    if not cur.rowcount: raise HTTPException(404,"AI-generated question not found")
    return {"id":question_id,"status":status}


@app.get("/api/exam-registrations")
def list_exam_registrations_api(query: str | None = None):
    return list_exam_registrations(query)


@app.post("/api/exam-registrations/request-confirmation")
def request_exam_confirmation_api(payload: dict):
    email = str(payload.get('email') or '').strip()
    full_name = str(payload.get('full_name') or '').strip()
    exam_name = str(payload.get('exam_name') or '').strip()
    notes = str(payload.get('notes') or '').strip()
    try:
        return request_exam_registration_confirmation(email, full_name=full_name, exam_name=exam_name, notes=notes)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/exam-registrations/confirm")
def confirm_exam_registration_api(token: str):
    try:
        return confirm_exam_registration(token)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/exam-registrations")
def create_exam_registrations_api(item: ExamRegistration):
    try:
        return create_exam_registration(item)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.put("/api/exam-registrations/{registration_id}")
def update_exam_registrations_api(registration_id: int, item: ExamRegistration):
    return update_exam_registration(registration_id, item)


@app.put("/api/exam-registrations/{registration_id}/status")
def set_exam_registration_status(registration_id: int, payload: dict):
    status = str(payload.get('status', 'pending')).strip().lower() if isinstance(payload, dict) else 'pending'
    if status not in {'pending', 'approved', 'rejected'}:
        raise HTTPException(400, 'status must be pending, approved or rejected')
    item = update_exam_registration(registration_id, {'status': status})
    return {**item, 'status': status}


@app.get("/api/exam-registrations/analytics")
def exam_registration_analytics():
    items = list_exam_registrations()
    status_counts = {'pending': 0, 'approved': 0, 'rejected': 0}
    for item in items:
        name = str(item.get('status', 'pending') or 'pending').lower()
        if name in status_counts:
            status_counts[name] += 1
    exam_summary: dict[str, int] = {}
    for item in items:
        name = str(item.get('exam_name') or 'General').strip() or 'General'
        exam_summary[name] = exam_summary.get(name, 0) + 1
    return {
        'total': len(items),
        'status_counts': status_counts,
        'by_exam': [{'exam_name': exam, 'count': count} for exam, count in sorted(exam_summary.items(), key=lambda row: (-row[1], row[0]))],
    }


@app.get("/api/exam-registrations/export.csv")
def export_exam_registrations_csv():
    items = list_exam_registrations()
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=['id', 'full_name', 'email', 'phone', 'exam_name', 'exam_date', 'center_preference', 'status', 'notes', 'created_at', 'updated_at'])
    writer.writeheader()
    for item in items:
        writer.writerow({key: item.get(key, '') for key in writer.fieldnames})
    body = output.getvalue().encode('utf-8')
    return Response(body, media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="exam-registrations.csv"'})


@app.get("/api/exam-registrations/export.pdf")
def export_exam_registrations_pdf():
    import pymupdf
    items = list_exam_registrations()
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((36, 52), 'Exam Registration Report', fontsize=18)
    y = 82
    for item in items:
        line = f"{item.get('id', '')}. {item.get('full_name', '')} | {item.get('exam_name', '')} | {item.get('status', '')} | {item.get('center_preference', '')}"
        page.insert_text((36, y), line, fontsize=10)
        y += 16
        if y > 720:
            page = doc.new_page()
            y = 52
    buffer = io.BytesIO()
    doc.save(buffer)
    doc.close()
    return Response(buffer.getvalue(), media_type='application/pdf', headers={'Content-Disposition': 'attachment; filename="exam-registrations.pdf"'})


def _clean_exam_option(option):
    if option is None:
        return ''
    if isinstance(option, str):
        return option.strip()
    return str(option).strip()


def _exam_question_from_db(row: sqlite3.Row, number: int) -> dict:
    item = row_to_dict(row)
    options = item.get('options') or []
    cleaned = [_clean_exam_option(opt) for opt in options if _clean_exam_option(opt)]
    return {
        'number': number,
        'subject': item.get('subject') or 'General',
        'chapter': item.get('chapter') or 'General',
        'difficulty': item.get('difficulty') or 'medium',
        'statement': (item.get('statement') or '').strip(),
        'options': cleaned,
        'answer': (item.get('answer') or '').strip(),
        'solution': (item.get('solution') or '').strip(),
    }


def _sample_exam_questions() -> list[dict]:
    with closing(connect()) as conn:
        rows = conn.execute(
            """SELECT * FROM questions WHERE TRIM(statement) != '' AND options IS NOT NULL AND options != '[]'
            ORDER BY CASE lower(verification_status) WHEN 'approved' THEN 0 WHEN 'ai_validated' THEN 1 ELSE 2 END,
            confidence DESC,id LIMIT 15"""
        ).fetchall()
    questions = [_exam_question_from_db(row, idx + 1) for idx, row in enumerate(rows)]
    if len(questions) >= 15:
        return questions
    idx = 0
    fallback = [
        {'number': idx + 1, 'statement': 'If 3x + 5 = 20, what is x?', 'options': ['3', '4', '5', '6'], 'answer': 'B', 'subject': 'Mathematics', 'chapter': 'Linear equations', 'difficulty': 'easy'},
        {'number': idx + 2, 'statement': 'The value of 7^2 is:', 'options': ['14', '49', '56', '63'], 'answer': 'B', 'subject': 'Mathematics', 'chapter': 'Squares', 'difficulty': 'easy'},
        {'number': idx + 3, 'statement': 'Which of these is a prime number?', 'options': ['21', '27', '29', '33'], 'answer': 'C', 'subject': 'Mathematics', 'chapter': 'Number theory', 'difficulty': 'easy'},
        {'number': idx + 4, 'statement': 'Simplify: 12/18', 'options': ['2/3', '3/4', '4/5', '5/6'], 'answer': 'A', 'subject': 'Mathematics', 'chapter': 'Fractions', 'difficulty': 'easy'},
        {'number': idx + 5, 'statement': 'The perimeter of a square of side 6 cm is:', 'options': ['12 cm', '18 cm', '24 cm', '36 cm'], 'answer': 'C', 'subject': 'Mathematics', 'chapter': 'Geometry', 'difficulty': 'easy'},
        {'number': idx + 6, 'statement': 'Find the mean of 4, 6, 8, 10.', 'options': ['6', '7', '8', '9'], 'answer': 'B', 'subject': 'Mathematics', 'chapter': 'Statistics', 'difficulty': 'easy'},
        {'number': idx + 7, 'statement': 'Which gas do plants absorb from the atmosphere?', 'options': ['Oxygen', 'Hydrogen', 'Carbon dioxide', 'Nitrogen'], 'answer': 'C', 'subject': 'Chemistry', 'chapter': 'Environment', 'difficulty': 'easy'},
        {'number': idx + 8, 'statement': 'The organ that pumps blood in the human body is the:', 'options': ['Lungs', 'Brain', 'Heart', 'Kidney'], 'answer': 'C', 'subject': 'Biology', 'chapter': 'Human physiology', 'difficulty': 'easy'},
        {'number': idx + 9, 'statement': 'The capital of France is:', 'options': ['Berlin', 'Rome', 'Paris', 'Madrid'], 'answer': 'C', 'subject': 'General', 'chapter': 'Geography', 'difficulty': 'easy'},
        {'number': idx + 10, 'statement': 'The value of 15% of 200 is:', 'options': ['20', '25', '30', '35'], 'answer': 'C', 'subject': 'Mathematics', 'chapter': 'Percentages', 'difficulty': 'easy'},
        {'number': idx + 11, 'statement': 'Which sentence is grammatically correct?', 'options': ['He go to school every day.', 'He goes to school every day.', 'He going to school every day.', 'He gone to school every day.'], 'answer': 'B', 'subject': 'English', 'chapter': 'Grammar', 'difficulty': 'easy'},
        {'number': idx + 12, 'statement': 'The sum of the angles of a triangle is:', 'options': ['90°', '180°', '270°', '360°'], 'answer': 'B', 'subject': 'Mathematics', 'chapter': 'Triangles', 'difficulty': 'easy'},
        {'number': idx + 13, 'statement': 'The smallest two-digit number is:', 'options': ['0', '1', '10', '11'], 'answer': 'C', 'subject': 'Mathematics', 'chapter': 'Number system', 'difficulty': 'easy'},
        {'number': idx + 14, 'statement': 'Which is the chemical symbol for sodium?', 'options': ['S', 'So', 'Na', 'N'], 'answer': 'C', 'subject': 'Chemistry', 'chapter': 'Periodic table', 'difficulty': 'easy'},
        {'number': idx + 15, 'statement': 'The speed of light is approximately:', 'options': ['3 x 10^5 m/s', '3 x 10^8 m/s', '3 x 10^10 m/s', '3 x 10^12 m/s'], 'answer': 'B', 'subject': 'Physics', 'chapter': 'Modern physics', 'difficulty': 'medium'},
    ]
    combined = questions + [
        {**item, 'number': len(questions) + idx + 1}
        for idx, item in enumerate(fallback[:max(0, 15 - len(questions))])
    ]
    return combined[:15]


@app.get("/api/exam-registrations/sample-paper")
def sample_exam_paper():
    return {'questions': _sample_exam_questions()}


@app.get("/api/exam-registrations/sample-paper.pdf")
def sample_exam_paper_pdf():
    import pymupdf
    questions = _sample_exam_questions()
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((36, 52), 'Sample Exam Paper (15 Questions)', fontsize=18)
    y = 90
    for q in questions:
        statement = f"{q['number']}. {q['statement']}"
        page.insert_text((36, y), statement, fontsize=12)
        y += 18
        for idx, option in enumerate(q.get('options', [])):
            label = chr(65 + idx)
            page.insert_text((52, y), f"{label}. {option}", fontsize=11)
            y += 16
        y += 10
        if y > 700:
            page = doc.new_page()
            y = 52
    buffer = io.BytesIO()
    doc.save(buffer)
    doc.close()
    return Response(buffer.getvalue(), media_type='application/pdf', headers={'Content-Disposition': 'attachment; filename="sample-exam-paper.pdf"'})


@app.delete("/api/exam-registrations/{registration_id}")
def delete_exam_registrations_api(registration_id: int):
    return delete_exam_registration(registration_id)


@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise HTTPException(400, f"unsupported file type: {ext or 'unknown'}")
    content = await file.read()
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(400, "file too large (max 10 MB)")
    mime = _source_mime(file.filename or "image.png", file.content_type)
    _validate_source(content, file.filename or "image.png", mime)
    name = f"{uuid.uuid4().hex}{ext}"
    with open(os.path.join(UPLOAD_DIR, name), "wb") as fh:
        fh.write(content)
    return {"url": f"/uploads/{name}"}


def _image_local(content: bytes, filename: str) -> dict:
    ext = Path(filename).suffix.lower()
    name = f"{uuid.uuid4().hex}{ext}"
    with open(os.path.join(UPLOAD_DIR, name), "wb") as fh:
        fh.write(content)
    url = f"/uploads/{name}"
    return {
        "questions": [{
            "number": 1, "page": 1, "statement": "", "options": [], "answer": "", "solution": "",
            "image": url, "source_bbox": [0, 0, 1, 1],
            "source_segments": [{"page": 1, "bbox": [0, 0, 1, 1], "image": url}],
            "garbled": True, "verification_status": "UNVERIFIED", "confidence": 0.0,
            "verification_issues": [], "uncertainties": [], "content_blocks": [], "visual_assets": [], "math_evidence": [],
        }],
        "warnings": ["Image loaded as source evidence. Configure Vertex AI to transcribe it automatically."],
        "pages": 1, "ocr_pages": [], "formula_pages": [], "mostly_garbled": True,
    }


def _split_question_blocks(text: str) -> list[str]:
    cleaned = text.replace('\r\n', '\n').replace('\r', '\n').strip()
    if not cleaned:
        return []
    pieces = re.split(r'\n\s*\n+', cleaned)
    blocks: list[str] = []
    for piece in pieces:
        candidate = piece.strip()
        if not candidate:
            continue
        if re.search(r'(?im)^\s*(?:Q(?:uestion)?\s*)?\d+\s*[:\.]?\s*', candidate):
            blocks.append(candidate)
        elif blocks:
            blocks[-1] = f"{blocks[-1]}\n\n{candidate}"
        else:
            blocks.append(candidate)
    if not blocks:
        return [cleaned]
    return blocks


def _parse_text_question_block(block: str) -> dict:
    lines = [line.strip() for line in block.replace('\r\n', '\n').split('\n') if line.strip()]
    if not lines:
        return {"statement": "", "options": [], "answer": "", "solution": ""}

    statement_lines: list[str] = []
    options: list[str] = []
    answer = ""
    solution = ""
    answer_seen = False

    def strip_question_prefix(s: str) -> str:
        return re.sub(r'^(?:Q(?:uestion)?\s*)?\d+\s*[:\.]?\s*', '', s, count=1, flags=re.I)

    for raw in lines:
        line = raw.strip()
        option_match = re.match(r'^(?:[A-F]|[A-Z])\s*([\)\.]|:|\-|\s)\s*(.+)$', line, flags=re.I)
        if option_match:
            options.append(option_match.group(2).strip())
            answer_seen = False
            continue
        answer_match = re.match(r'^(?:Answer|Ans|Correct(?:\s+option)?|Option)\s*[:\-]?\s*([A-F]|[A-Z]|\d+|[A-Z][A-Z0-9]*)\s*$', line, flags=re.I)
        if answer_match:
            answer = answer_match.group(1).strip().upper()
            answer_seen = True
            continue
        if answer_seen and line and not line.lower().startswith('solution'):
            solution = (solution + ('\n' if solution else '') + line).strip()
            continue
        if line.lower().startswith('solution'):
            remainder = re.sub(r'^solution\s*[:\-]?\s*', '', line, flags=re.I)
            if remainder:
                solution = remainder.strip()
            continue
        if not statement_lines and re.match(r'^(?:Q(?:uestion)?\s*)?\d+\s*[:\.]?\s*', line, flags=re.I):
            line = strip_question_prefix(line)
        statement_lines.append(line)

    statement = ' '.join(part for part in statement_lines if part).strip()
    if not statement and options:
        statement = ' '.join(options[:1])
    return {"statement": statement, "options": options, "answer": answer, "solution": solution}


def _text_local(filename: str, content: bytes) -> dict:
    text = _text_source_preview(filename, content).strip()
    if not text:
        text = "Uploaded text document loaded successfully."

    blocks = _split_question_blocks(text)
    parsed_questions: list[dict] = []
    if blocks:
        for idx, block in enumerate(blocks, start=1):
            item = _parse_text_question_block(block)
            statement = item["statement"].strip()
            options = [str(opt).strip() for opt in item["options"] if str(opt).strip()]
            answer = str(item["answer"]).strip().upper()
            if not statement and options:
                statement = options.pop(0)
            if statement or options:
                parsed_questions.append({
                    "number": idx,
                    "page": 1,
                    "statement": statement,
                    "options": options,
                    "answer": answer,
                    "solution": item["solution"],
                    "image": "",
                    "source_bbox": [0, 0, 1, 1],
                    "source_segments": [{"page": 1, "bbox": [0, 0, 1, 1], "text": statement}],
                    "garbled": False,
                    "verification_status": "UNVERIFIED",
                    "confidence": 0.0,
                    "verification_issues": [],
                    "uncertainties": [],
                    "content_blocks": [],
                    "visual_assets": [],
                    "math_evidence": [],
                })
    if not parsed_questions:
        parsed_questions = [{
            "number": 1,
            "page": 1,
            "statement": text,
            "options": [],
            "answer": "",
            "solution": "",
            "image": "",
            "source_bbox": [0, 0, 1, 1],
            "source_segments": [{"page": 1, "bbox": [0, 0, 1, 1], "text": text}],
            "garbled": False,
            "verification_status": "UNVERIFIED",
            "confidence": 0.0,
            "verification_issues": [],
            "uncertainties": [],
            "content_blocks": [],
            "visual_assets": [],
            "math_evidence": [],
        }]

    return {
        "questions": parsed_questions,
        "warnings": [f"{Path(filename).suffix.lower() or 'text'} file loaded as editable source text. Review the extracted content before importing."],
        "pages": 1,
        "ocr_pages": [],
        "formula_pages": [],
        "mostly_garbled": False,
    }


async def _parse_source(file: UploadFile, mode: str) -> dict:
    if mode not in {"auto", "text", "ocr", "llm"}:
        raise HTTPException(400, "mode must be auto, text, ocr or llm")
    filename = file.filename or "source"
    content = await file.read()
    if len(content) > MAX_SOURCE_BYTES:
        raise HTTPException(400, "file too large (max 50 MB)")
    mime = _source_mime(filename, file.content_type)
    _validate_source(content, filename, mime)

    is_pdf = mime == "application/pdf"
    if mode == "ocr" and is_pdf and not vision_status()["available"]:
        raise HTTPException(503, "page OCR is not configured — configure GCP Vision/Tesseract or use auto")

    text_like = Path(filename).suffix.lower() in ALLOWED_TEXT_EXT | {".doc", ".docx", ".odt", ".ppt", ".pptx", ".xls", ".xlsx"}
    try:
        if is_pdf:
            local = await run_in_threadpool(parse_pdf, content, UPLOAD_DIR, "auto" if mode == "llm" else mode)
            page_count = int(local.get("pages") or max([q.get("page", 0) for q in local.get("questions", [])] or [0]))
        elif text_like:
            page_count = 1
            local = await run_in_threadpool(_text_local, filename, content)
        else:
            page_count = 1
            local = await run_in_threadpool(_image_local, content, filename)

        source = _record_source(content, filename, mime, page_count)
        data = local
        provider, model, run_status = "local", "", "LOCAL"
        if mode == "llm" or (mode == "auto" and llm_status()["available"]):
            try:
                if is_pdf:
                    data = await run_in_threadpool(extract_pdf, content, local, UPLOAD_DIR)
                elif text_like:
                    text_content = _text_source_preview(filename, content).encode("utf-8")
                    data = await run_in_threadpool(extract_source, text_content, "text/plain", local, UPLOAD_DIR, 1)
                else:
                    data = await run_in_threadpool(extract_image, content, mime, local, UPLOAD_DIR)
            except Exception as exc:
                if mode == "llm" and not text_like:
                    if type(exc).__name__ in {"RefreshError", "DefaultCredentialsError"}:
                        raise HTTPException(503, "Google ADC login is missing/expired. Run: gcloud auth application-default login") from exc
                    raise HTTPException(502, f"GCP extraction failed: {type(exc).__name__}: {exc}") from exc
                data = local
                if text_like and isinstance(exc, ValueError) and "did not finish the structured response" in str(exc):
                    data.setdefault("warnings", []).append(
                        "Gemini could not finish a structured response for this text document; using local extraction instead."
                    )
                elif not text_like:
                    data.setdefault("warnings", []).append(
                        f"GCP extraction failed ({type(exc).__name__}): {exc}; showing local evidence instead."
                    )
            if data.get("llm"):
                provider = data["llm"].get("provider", "vertex-ai")
                model = data["llm"].get("model", "")
                run_status = "AI_COMPLETE"
        run_id = _record_run(source["id"], provider, model, run_status, data.get("usage", {}), data.get("warnings", []))
        _bind_extraction_prompts(run_id,data,model)
        return _decorate_drafts(data, source, run_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"could not read source: {exc}") from exc


@app.post("/api/source/parse")
async def parse_source(file: UploadFile = File(...), mode: str = Form("auto")):
    return await _parse_source(file, mode)


def _prepare_pdf_preview(content: bytes, filename: str) -> dict:
    import pymupdf
    _validate_source(content, filename, "application/pdf")
    try:
        with pymupdf.open(stream=content, filetype="pdf") as doc:
            if doc.needs_pass:
                raise HTTPException(400, "Please upload an unlocked PDF.")
            page_count = len(doc)
            if not 1 <= page_count <= 200:
                raise HTTPException(400, "PDF preview supports 1–200 pages per file.")
            dimensions = [{"width": p.rect.width, "height": p.rect.height} for p in doc]
        source = _record_source(content, filename, "application/pdf", page_count)
        return {"id": source["id"], "filename": filename, "page_count": page_count,
                "pages": [{"number": i + 1, **size,
                           "url": f"/api/sources/{source['id']}/pages/{i + 1}"}
                          for i, size in enumerate(dimensions)]}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, "This PDF could not be opened. Try re-saving the original file.") from exc


@app.post("/api/pdf/preview")
async def preview_pdf(file: UploadFile = File(...)):
    """Store and inspect a PDF without OCR, extraction, or cloud requests."""
    filename = file.filename or "document.pdf"
    if Path(filename).suffix.lower() != ".pdf":
        raise HTTPException(400, "Choose a PDF file to preview.")
    content = await file.read(MAX_SOURCE_BYTES + 1)
    if len(content) > MAX_SOURCE_BYTES:
        raise HTTPException(400, "file too large (max 50 MB)")
    return await run_in_threadpool(_prepare_pdf_preview, content, filename)


def _read_pdf_source(source):
    # Read through Python IO rather than MuPDF file mapping on a GCS FUSE mount.
    paths=[source['local_path'],os.path.join(SOURCE_DIR,os.path.basename(source['local_path']))]
    for path in dict.fromkeys(paths):
        try:
            with open(path,'rb') as fh:
                content=fh.read(MAX_SOURCE_BYTES+1)
            if not content or len(content)>MAX_SOURCE_BYTES: continue
            return content
        except FileNotFoundError: continue
    gcs_key=source.get('gcs_object') if hasattr(source,'get') else None
    if not gcs_key:
        with closing(connect()) as conn:
            link=conn.execute('SELECT gcs_object FROM program_documents WHERE source_document_id=?',(source['id'],)).fetchone()
            gcs_key=link['gcs_object'] if link else None
    if gcs_key and os.getenv('GCS_DATA_BUCKET'):
        try:
            from google.cloud import storage
            content=storage.Client().bucket(os.getenv('GCS_DATA_BUCKET')).blob(gcs_key).download_as_bytes()
            if content:return content
        except Exception:
            pass
    raise HTTPException(409,'The stored PDF is unavailable. Upload the original PDF again to restore its pages.')


@app.get("/api/sources/{source_id}/pages/{page_number}")
def preview_pdf_page(source_id: str, page_number: int):
    import pymupdf
    with closing(connect()) as conn:
        source = conn.execute("SELECT * FROM source_documents WHERE id = ?", (source_id,)).fetchone()
    if source is None or source["mime_type"] != "application/pdf":
        raise HTTPException(404, "PDF not found")
    try:
        with pymupdf.open(stream=_read_pdf_source(source), filetype="pdf") as doc:
            if not 1 <= page_number <= len(doc):
                raise HTTPException(404, "Page not found")
            page = doc[page_number - 1]
            scale = min(1.8, 2400 / max(1, page.rect.width, page.rect.height))
            png = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes("png")
        from fastapi.responses import Response
        return Response(png, media_type="image/png", headers={"Cache-Control": "private, no-store"})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, "This PDF page could not be rendered.") from exc


class PdfCropSelection(BaseModel):
    page: int = Field(ge=1)
    bbox: list[float] = Field(min_length=4, max_length=4)


class PdfCropRequest(BaseModel):
    page: int | None = Field(default=None, ge=1)
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)
    selections: list[PdfCropSelection] | None = None


def _normalise_crop_selections(req: PdfCropRequest) -> list[PdfCropSelection]:
    selections = list(req.selections or [])
    if req.page is not None and req.bbox is not None:
        selections.insert(0, PdfCropSelection(page=req.page, bbox=req.bbox))
    if not selections:
        raise HTTPException(400, "Select at least one region inside the PDF page.")
    return selections


def _render_pdf_crop(source_id: str, req: PdfCropRequest) -> tuple[dict, bytes]:
    import pymupdf
    x0, y0, x1, y1 = req.bbox
    if (not all(math.isfinite(v) and 0 <= v <= 1 for v in req.bbox)
            or x1 - x0 < .005 or y1 - y0 < .005):
        raise HTTPException(400, "Select a larger rectangular region inside the page.")
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM source_documents WHERE id = ?", (source_id,)).fetchone()
    if row is None or row["mime_type"] != "application/pdf":
        raise HTTPException(404, "PDF not found. Upload the document again.")
    source = dict(row)
    try:
        with pymupdf.open(stream=_read_pdf_source(source), filetype="pdf") as doc:
            if req.page > len(doc):
                raise HTTPException(404, "Page not found")
            page = doc[req.page - 1]
            rect = page.rect
            clip = pymupdf.Rect(rect.x0 + x0 * rect.width, rect.y0 + y0 * rect.height,
                                rect.x0 + x1 * rect.width, rect.y0 + y1 * rect.height)
            scale = min(4.2, 4200 / max(1, clip.width, clip.height))
            png = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip, alpha=False).tobytes("png")
        return source, png
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, "The selected PDF region could not be rendered.") from exc


def _map_crop_evidence(data: dict, source: dict, req: PdfCropRequest) -> dict:
    """Keep crop images while restoring coordinates to the original PDF page."""
    x0, y0, x1, y1 = req.bbox
    def map_region(region: dict) -> None:
        box = region.get("bbox") or [0, 0, 1, 1]
        if len(box) == 4:
            region["bbox"] = [x0 + box[0] * (x1 - x0), y0 + box[1] * (y1 - y0),
                              x0 + box[2] * (x1 - x0), y0 + box[3] * (y1 - y0)]
        region["page"] = req.page
    for question in data.get("questions", []):
        region = {"bbox": question.get("source_bbox")}
        map_region(region)
        question.update(source_bbox=region["bbox"], page=req.page, source_page=req.page,
                        source_document_id=source["id"], source_document_sha256=source["sha256"])
        for key in ("source_segments", "source_regions", "visual_assets", "visuals", "math_evidence"):
            question[key] = deepcopy(question.get(key, []))
            for item in question[key]:
                map_region(item)
        question["content_blocks"] = build_content_blocks(question.get("statement", ""), question.get("visual_assets", []))
    data["source_document"] = {k: source[k] for k in ("id", "filename", "sha256", "mime_type", "page_count")}
    data["selected_region"] = {"page": req.page, "bbox": req.bbox}
    return data


async def _digitise_single_crop(source_id: str, selection: PdfCropSelection):
    single = PdfCropRequest(page=selection.page, bbox=selection.bbox)
    source, png = await run_in_threadpool(_render_pdf_crop, source_id, single)
    crop = UploadFile(filename=f"page-{selection.page}-crop.png", file=io.BytesIO(png))
    try:
        data = await _parse_source(crop, "auto")
    finally:
        await crop.close()
    data = _map_crop_evidence(data, source, single)
    evidence_name = f"selected-{uuid.uuid4().hex}.png"
    await run_in_threadpool(Path(UPLOAD_DIR, evidence_name).write_bytes, png)
    evidence_url = f"/uploads/{evidence_name}"
    for question in data.get("questions", []):
        question.update(image=evidence_url, source_image=evidence_url, source_bbox=list(single.bbox),
                        source_segments=[{"page": selection.page, "bbox": list(single.bbox),
                                          "image": evidence_url, "provider": "user-selected-region"}])
    if data.get("extraction_run_id"):
        with closing(connect()) as conn:
            conn.execute("UPDATE extraction_runs SET source_document_id = ? WHERE id = ?",
                         (source_id, data["extraction_run_id"]))
            conn.commit()
    return data


@contextmanager
def _temporary_env(overrides: dict[str, str]):
    previous = {key: os.environ.get(key) for key in overrides}
    os.environ.update(overrides)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@app.post("/api/sources/{source_id}/digitise-crop")
async def digitise_pdf_crop(source_id: str, req: PdfCropRequest):
    selections = _normalise_crop_selections(req)
    combined = {"questions": [], "warnings": [], "llm": {"provider": "local", "model": "local"},
                "source_document": None, "selected_regions": []}
    async def _digitise_selected(selection: PdfCropSelection):
        with _temporary_env({"QB_VERIFY": "off"}):
            return await _digitise_single_crop(source_id, selection)
    per_selection = await asyncio.gather(*[
        _digitise_selected(selection) for selection in selections
    ])
    for selection, data in zip(selections, per_selection):
        combined["questions"].extend(data.get("questions", []))
        combined["warnings"].extend(data.get("warnings", []))
        combined["selected_regions"].append({"page": selection.page, "bbox": list(selection.bbox)})
        combined["source_document"] = data.get("source_document") or combined["source_document"]
        if data.get("llm"):
            combined["llm"] = data["llm"]
        if not combined.get("extraction_run_id") and data.get("extraction_run_id"):
            combined["extraction_run_id"] = data["extraction_run_id"]
    return combined


@app.post("/api/pdf/parse")
async def parse_pdf_paper(file: UploadFile = File(...), mode: str = Form("auto")):
    """Backward-compatible route used by the original UI/tests."""
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "expected a .pdf file")
    return await _parse_source(file, mode)


class OcrRequest(BaseModel):
    image: str
    box: list[float] | None = None


@app.get("/api/ocr/status")
def ocr_state():
    return {**ocr_status(), "cloud": vision_status(), "llm": llm_status()}


@app.post("/api/ocr")
def ocr_image(req: OcrRequest):
    name = os.path.basename(req.image)
    path = os.path.join(UPLOAD_DIR, name)
    if not os.path.isfile(path):
        raise HTTPException(404, "image not found")
    try:
        return {"text": ocr_to_latex(path, req.box)}
    except OcrUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"OCR failed: {exc}") from exc


@app.get("/api/system/status")
def system_status():
    return {"llm": llm_status(), "formula_ocr": ocr_status(), "page_ocr": vision_status(), "data_dir": DATA_DIR}


@app.get("/api/export")
def export_all():
    with closing(connect()) as conn:
        rows = conn.execute("SELECT * FROM questions ORDER BY id").fetchall()
    return JSONResponse(
        [row_to_dict(r) for r in rows],
        headers={"Content-Disposition": 'attachment; filename="question-bank.json"'},
    )


@app.post("/api/import")
def import_questions(items: list[Question]):
    """Transactional batch import: either the selected batch commits or none of it does."""
    if not items:
        return {"imported": []}
    now = time.time()
    cols = ", ".join(FIELDS)
    marks = ", ".join(["?"] * len(FIELDS))
    imported: list[int] = []
    with closing(connect()) as conn:
        try:
            conn.execute("BEGIN")
            for q in items:
                cur = conn.execute(
                    f"INSERT INTO questions ({cols}, created_at, updated_at) VALUES ({marks}, ?, ?)",
                    values_of(q) + [now, now],
                )
                imported.append(cur.lastrowid)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"imported": imported}


app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


@app.get("/sw.js", include_in_schema=False)
def mobile_service_worker():
    return FileResponse("static/sw.js", media_type="application/javascript", headers={"Cache-Control":"no-cache","Service-Worker-Allowed":"/"})

@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/api/health")
def public_health():
    # Cloud Run's frontend may intercept /healthz before it reaches the app.
    with closing(connect()) as conn:
        conn.execute('SELECT 1').fetchone()
    return {"status": "ok", "revision": os.getenv('K_REVISION', 'local')}


@app.get("/")
def index():
    # The marketing document is fully static so search engines receive the
    # complete copy without executing JavaScript.
    return FileResponse(os.path.join(BASE_DIR, "static", "home.html"), headers={"Cache-Control":"no-cache"})


@app.get("/app")
def workspace():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"), headers={"Cache-Control":"no-store"})


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    base = os.getenv("PUBLIC_BASE_URL") or os.getenv("APP_BASE_URL") or "https://meritiqra.com"
    return "\n".join(("User-agent: *", "Allow: /", "Disallow: /app", "Disallow: /admin", "Disallow: /student", "Disallow: /api/", "Disallow: /register/", f"Sitemap: {base.rstrip('/')}/sitemap.xml", ""))


@app.get("/sitemap.xml")
def sitemap():
    base = (os.getenv("PUBLIC_BASE_URL") or os.getenv("APP_BASE_URL") or "https://meritiqra.com").rstrip('/')
    paths = ("/",)
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(f'<url><loc>{base}{path}</loc></url>' for path in paths) + '</urlset>'
    return Response(xml, media_type="application/xml")


@app.get("/{public_path:path}", include_in_schema=False)
def public_page(public_path: str):
    public_routes = {"home", "practice-exams", "exams", "features", "ai-question-bank", "ai-question-generation", "online-exam-platform", "assessment-platform", "for-students", "for-schools", "for-organizations", "how-it-works", "about"}
    if public_path in public_routes:
        # Previously indexed marketing URLs keep resolving to the home document.
        return FileResponse(os.path.join(BASE_DIR, "static", "home.html"), headers={"Cache-Control":"no-cache"})
    if public_path == "mobile/callback":
        return FileResponse(os.path.join(BASE_DIR,"static","mobile-callback.html"),headers={"Cache-Control":"no-store"})
    if public_path.startswith("register/exam/"):
        return FileResponse(os.path.join(BASE_DIR, "static", "index.html"), headers={"Cache-Control":"no-store"})
    raise HTTPException(404, "Page not found")


@app.get("/register/exam/{token}")
def registration_page(token: str):
    """Serve the mobile-friendly SPA registration screen; the token is read client-side."""
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))
