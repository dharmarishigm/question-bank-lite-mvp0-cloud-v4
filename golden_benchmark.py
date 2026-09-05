"""Live golden-corpus regression runner for Question Bank MVP-0.

This is intentionally separate from unit tests because it calls paid GCP services.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import tempfile
from pathlib import Path

import pymupdf

from llm_extract import extract_image, extract_pdf
from pdf_import import parse_pdf
from verification import signature


def normalized(s: str) -> str:
    return "".join((s or "").split())


def compare(expected: dict, actual: dict) -> dict:
    exp = expected.get("questions", [])
    got = actual.get("questions", [])
    by_key = {(q.get("page"), q.get("number")): q for q in got}
    exact_statements = exact_options = exact_answers = high_risk = 0
    missing = 0
    silent_verified_errors = 0

    for e in exp:
        a = by_key.get((e.get("page"), e.get("number")))
        if not a:
            missing += 1
            continue
        statement_ok = normalized(e.get("statement", "")) == normalized(a.get("statement", ""))
        options_ok = [normalized(x) for x in e.get("options", [])] == [normalized(x) for x in a.get("options", [])]
        answer_ok = normalized(e.get("answer", "")) == normalized(a.get("answer", ""))
        risk_ok = signature(e.get("statement", "")) == signature(a.get("statement", ""))
        exact_statements += int(statement_ok)
        exact_options += int(options_ok)
        exact_answers += int(answer_ok)
        high_risk += int(risk_ok)
        if (not statement_ok or not options_ok or not risk_ok) and a.get("verification_status") == "VERIFIED":
            silent_verified_errors += 1

    total = max(1, len(exp))
    return {
        "expected_questions": len(exp),
        "actual_questions": len(got),
        "missing_questions": missing,
        "statement_exact_rate": exact_statements / total,
        "option_exact_rate": exact_options / total,
        "answer_exact_rate": exact_answers / total,
        "high_risk_signature_rate": high_risk / total,
        "silent_verified_errors": silent_verified_errors,
    }


def run_case(case: Path) -> dict:
    sources = [p for p in case.iterdir() if p.name.startswith("source.")]
    if not sources or not (case / "expected.json").exists():
        raise ValueError("case needs source.<pdf/png/jpg/webp> and expected.json")
    source = sources[0]
    content = source.read_bytes()
    expected = json.loads((case / "expected.json").read_text())
    mime = "application/pdf" if source.suffix.lower() == ".pdf" else (mimetypes.guess_type(source.name)[0] or "image/png")
    with tempfile.TemporaryDirectory() as upload_dir:
        if mime == "application/pdf":
            local = parse_pdf(content, upload_dir, "auto")
            actual = extract_pdf(content, local, upload_dir)
        else:
            # Full-image local evidence used only to give Gemini/verifier immutable source.
            url = "/uploads/source.png"
            (Path(upload_dir) / "source.png").write_bytes(content)
            local = {"questions": [{"number": 1, "page": 1, "statement": "", "options": [],
                                     "image": url, "source_bbox": [0, 0, 1, 1],
                                     "source_segments": [{"page": 1, "bbox": [0, 0, 1, 1], "image": url}]}],
                     "warnings": [], "pages": 1}
            actual = extract_image(content, mime, local, upload_dir)
    return compare(expected, actual)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path, nargs="?", default=Path("tests/golden"))
    args = parser.parse_args()
    cases = [p for p in args.root.iterdir() if p.is_dir()]
    if not cases:
        print("No golden cases found. See tests/golden/README.md")
        return 0
    failures = 0
    for case in cases:
        metrics = run_case(case)
        print(case.name, json.dumps(metrics, indent=2))
        if metrics["missing_questions"] or metrics["silent_verified_errors"]:
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
