"""Public, unauthenticated marketing and exam-discovery endpoints.

Only published examinations and non-sensitive metadata are exposed. Question
content, answers, solutions, proctor codes and student data never leave this
module.
"""
from __future__ import annotations

import os
import time
from contextlib import closing

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/public")

PUBLIC_EXAM_STATUSES = ("PUBLISHED", "OPEN")
PUBLIC_EXAM_FIELDS = (
    "id", "name", "description", "exam_type", "subject", "level", "status",
    "duration_minutes", "total_marks", "max_attempts", "proctor_required",
    "exam_start_at", "exam_end_at", "question_count", "allow_self_registration",
)


def db():
    from app import connect
    return connect()


def _flag(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def config() -> dict:
    return {
        "brand_name": os.getenv("BRAND_NAME", "Question Bank"),
        "brand_tagline": os.getenv("BRAND_TAGLINE", "Practice smarter. Master every exam."),
        "support_email": os.getenv("SUPPORT_EMAIL", ""),
        "show_marketing_home": _flag("SHOW_MARKETING_HOME"),
        "show_public_exam_catalog": _flag("SHOW_PUBLIC_EXAM_CATALOG"),
        "show_ai_explanation_marketing": _flag("SHOW_AI_EXPLANATION_MARKETING"),
    }


def _public_exam(row) -> dict:
    data = dict(row)
    exam = {key: data.get(key) for key in PUBLIC_EXAM_FIELDS}
    exam["proctor_required"] = bool(data.get("proctor_required"))
    exam["allow_self_registration"] = bool(data.get("allow_self_registration", 1))
    exam["mode"] = "PROCTORED" if exam["proctor_required"] else "PRACTICE"
    exam["attempt_count"] = int(data.get("attempt_count") or 0)
    badges, seen = [], set()
    for badge in (exam["mode"].title(), exam.get("exam_type"), exam.get("level"), exam.get("subject")):
        key = (badge or "").strip().casefold()
        if key and key not in seen:
            seen.add(key)
            badges.append(badge.strip())
    exam["badges"] = badges
    return exam


def _select_exams(conn, where: str = "", params: tuple = (), limit: int = 24, order: str = "recent"):
    clause = " AND " + where if where else ""
    ranking = {
        "trending": "attempt_count DESC, question_count DESC, e.created_at DESC",
        "recent": "e.created_at DESC",
        "name": "e.name COLLATE NOCASE",
    }.get(order, "e.created_at DESC")
    sql = (
        "SELECT e.*, "
        "(SELECT COUNT(*) FROM exam_questions q WHERE q.exam_id=e.id) question_count, "
        "(SELECT COUNT(*) FROM exam_sessions s WHERE s.exam_id=e.id) attempt_count "
        f"FROM exams e WHERE e.status IN {PUBLIC_EXAM_STATUSES}{clause} "
        f"ORDER BY {ranking} LIMIT ?"
    )
    return conn.execute(sql, (*params, limit)).fetchall()


def _categories(conn) -> list[dict]:
    categories: dict[tuple[str, str], int] = {}
    rows = conn.execute(
        f"SELECT exam_type, subject, level FROM exams WHERE status IN {PUBLIC_EXAM_STATUSES}"
    ).fetchall()
    for row in rows:
        for kind, value in (("exam_type", row["exam_type"]), ("subject", row["subject"]), ("level", row["level"])):
            value = (value or "").strip()
            if value:
                categories[(kind, value)] = categories.get((kind, value), 0) + 1
    ordered = sorted(categories.items(), key=lambda item: (-item[1], item[0][1].lower()))
    return [{"kind": kind, "value": value, "count": count} for (kind, value), count in ordered[:12]]


@router.get("/config")
def public_config():
    return config()


@router.get("/home")
def public_home():
    settings = config()
    if not settings["show_marketing_home"]:
        raise HTTPException(404, "Marketing home is disabled")
    with closing(db()) as conn:
        catalog = settings["show_public_exam_catalog"]
        trending = [_public_exam(r) for r in _select_exams(conn, limit=6, order="trending")] if catalog else []
        recent = [_public_exam(r) for r in _select_exams(conn, limit=6, order="recent")] if catalog else []
        categories = _categories(conn) if catalog else []
        published = conn.execute(
            f"SELECT COUNT(*) n FROM exams WHERE status IN {PUBLIC_EXAM_STATUSES}"
        ).fetchone()["n"]
        subjects = conn.execute(
            f"SELECT COUNT(DISTINCT subject) n FROM exams WHERE status IN {PUBLIC_EXAM_STATUSES} AND subject<>''"
        ).fetchone()["n"]
        questions = conn.execute("SELECT COUNT(*) n FROM questions").fetchone()["n"]
    has_attempt_data = any(exam["attempt_count"] for exam in trending)
    return {
        **settings,
        "trending_label": "Trending practice exams" if has_attempt_data else "Explore practice exams",
        "trending_is_ranked": has_attempt_data,
        "trending_exams": trending,
        "recent_exams": recent,
        "categories": categories,
        "stats": {"published_exams": published, "subjects": subjects, "question_bank_size": questions},
        "server_time": time.time(),
    }


@router.get("/exams")
def public_exams(q: str = "", subject: str = "", level: str = "", exam_type: str = "", limit: int = 48):
    if not config()["show_public_exam_catalog"]:
        raise HTTPException(404, "Public exam catalog is disabled")
    filters, params = [], []
    if q:
        filters.append("(e.name LIKE ? OR e.description LIKE ? OR e.subject LIKE ?)")
        params += [f"%{q}%"] * 3
    for column, value in (("subject", subject), ("level", level), ("exam_type", exam_type)):
        if value:
            filters.append(f"e.{column}=?")
            params.append(value)
    with closing(db()) as conn:
        rows = _select_exams(conn, " AND ".join(filters), tuple(params), max(1, min(limit, 100)), "trending")
        categories = _categories(conn)
    return {"exams": [_public_exam(r) for r in rows], "categories": categories}


@router.get("/exams/{exam_id}")
def public_exam_detail(exam_id: int):
    if not config()["show_public_exam_catalog"]:
        raise HTTPException(404, "Public exam catalog is disabled")
    with closing(db()) as conn:
        rows = _select_exams(conn, "e.id=?", (exam_id,), 1)
    if not rows:
        raise HTTPException(404, "Exam not found")
    return _public_exam(rows[0])
