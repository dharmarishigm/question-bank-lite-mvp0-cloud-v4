"""Question Bank Lite MVP-0 v3: fidelity-first local question digitization."""
from __future__ import annotations

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
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from llm_extract import extract_image, extract_pdf, extract_source, llm_status
from ocr import OcrUnavailable, ocr_status, ocr_to_latex, vision_status
from pdf_import import parse_pdf
from multimodal import build_content_blocks

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
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_questions_subject ON questions(subject);
CREATE INDEX IF NOT EXISTS idx_questions_chapter ON questions(chapter);

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
"""

# Additive migration map for databases created by the original ZIP.
QUESTION_MIGRATIONS = {
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
}

FIELDS = (
    "subject", "chapter", "topic", "exam", "year", "qtype", "difficulty",
    "marks", "statement", "options", "answer", "solution", "tags", "source_image",
    "source_segments", "source_document_id", "source_document_sha256", "source_page",
    "source_bbox", "extraction_run_id", "extraction_provider", "extraction_model",
    "verification_status", "confidence", "verification_issues", "uncertainties",
    "content_blocks", "visual_assets", "math_evidence",
)
JSON_FIELDS = {"options", "source_segments", "source_bbox", "verification_issues", "uncertainties", "content_blocks", "visual_assets", "math_evidence"}


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


with closing(connect()) as _conn:
    _conn.executescript(SCHEMA)
    columns = {r["name"] for r in _conn.execute("PRAGMA table_info(questions)")}
    for name, ddl in QUESTION_MIGRATIONS.items():
        if name not in columns:
            _conn.execute(f"ALTER TABLE questions ADD COLUMN {name} {ddl}")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_questions_source_document ON questions(source_document_id)")
    _conn.commit()


class Question(BaseModel):
    subject: str = ""
    chapter: str = ""
    topic: str = ""
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


app = FastAPI(title="Question Bank Lite MVP-0 v3", version="3.0.0")


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
            return dict(existing)
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
def update_question(qid: int, q: Question):
    assignments = ", ".join(f"{f} = ?" for f in FIELDS)
    with closing(connect()) as conn:
        if conn.execute("SELECT 1 FROM questions WHERE id=?", (qid,)).fetchone() is None:
            raise HTTPException(404, "question not found")
        _snapshot(conn, qid, "before edit")
        conn.execute(
            f"UPDATE questions SET {assignments}, updated_at = ? WHERE id = ?",
            values_of(q) + [time.time(), qid],
        )
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


@app.get("/api/sources/{source_id}/pages/{page_number}")
def preview_pdf_page(source_id: str, page_number: int):
    import pymupdf
    with closing(connect()) as conn:
        source = conn.execute("SELECT * FROM source_documents WHERE id = ?", (source_id,)).fetchone()
    if source is None or source["mime_type"] != "application/pdf":
        raise HTTPException(404, "PDF not found")
    try:
        with pymupdf.open(source["local_path"]) as doc:
            if not 1 <= page_number <= len(doc):
                raise HTTPException(404, "Page not found")
            page = doc[page_number - 1]
            scale = min(1.8, 2400 / max(1, page.rect.width, page.rect.height))
            png = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes("png")
        from fastapi.responses import Response
        return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})
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
        with pymupdf.open(source["local_path"]) as doc:
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


@app.post("/api/sources/{source_id}/digitise-crop")
async def digitise_pdf_crop(source_id: str, req: PdfCropRequest):
    selections = _normalise_crop_selections(req)
    combined = {"questions": [], "warnings": [], "llm": {"provider": "local", "model": "local"},
                "source_document": None, "selected_regions": []}
    for selection in selections:
        single = PdfCropRequest(page=selection.page, bbox=selection.bbox)
        source, png = await run_in_threadpool(_render_pdf_crop, source_id, single)
        crop = UploadFile(filename=f"page-{selection.page}-crop.png", file=io.BytesIO(png))
        try:
            data = await _parse_source(crop, "auto")
        finally:
            await crop.close()
        data = _map_crop_evidence(data, source, single)
        # The user's complete selection remains authoritative, even when the model
        # returns a smaller region for an individual question or visual.
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


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))
