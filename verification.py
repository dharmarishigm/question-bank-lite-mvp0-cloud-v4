"""Deterministic verification helpers for high-risk scientific notation."""
from __future__ import annotations

import re
from typing import Iterable

# Tokens whose changes commonly alter mathematical/scientific meaning.
NUMBER = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?(?:\s*[×x]\s*10\s*\^?\s*[-+]?\d+|[eE][-+]?\d+)?")
RELATION = re.compile(r"<=|>=|!=|==|≤|≥|≠|≈|=|<|>")
POWER = re.compile(r"\^\s*\{?\s*[-+]?\d+\s*\}?|[⁰¹²³⁴⁵⁶⁷⁸⁹]+")
CHEM_CHARGE = re.compile(r"(?:\^\s*\{?\s*\d*[+-]\s*\}?|[⁰¹²³⁴⁵⁶⁷⁸⁹]*[⁺⁻])")
UNIT = re.compile(r"\b(?:m|cm|mm|km|s|ms|kg|g|N|J|W|Pa|Hz|V|A|C|K|mol|M|L|mL|eV)(?:\s*/\s*(?:s|m|kg)(?:\^?\s*\d+)?)?\b")


def _norm(s: str) -> str:
    value = (s or "").replace("\\left", "").replace("\\right", "")
    for old, new in (("\\leq", "≤"), ("\\le", "≤"), ("\\geq", "≥"), ("\\ge", "≥"),
                     ("\\neq", "≠"), ("\\ne", "≠"), ("\\times", "×"), ("\\cdot", "·")):
        value = value.replace(old, new)
    return re.sub(r"\s+", "", value)


def signature(text: str) -> dict[str, list[str]]:
    text = text or ""
    return {
        "numbers": NUMBER.findall(text),
        "relations": RELATION.findall(text),
        "powers": POWER.findall(text),
        "charges": CHEM_CHARGE.findall(text),
        "units": UNIT.findall(text),
    }


def formula_matches_candidate(formula: str, candidate: str) -> bool:
    f = _norm(formula).strip("$ ")
    c = _norm(candidate)
    if not f:
        return True
    if f in c:
        return True
    fs, cs = signature(formula), signature(candidate)
    # Conservative: only claim a mismatch when the formula carries multiple
    # high-risk invariants and none of that invariant set appears in candidate.
    evidence = sum(len(v) for v in fs.values())
    if evidence < 2:
        return True
    return all(not v or any(_norm(x) in _norm(" ".join(cs[k])) for x in v) for k, v in fs.items())


def bbox_overlap(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != 4 or len(b) != 4:
        return 0.0
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    area = max(1e-9, (a[2] - a[0]) * (a[3] - a[1]))
    return inter / area


def formulas_for_question(docai: dict | None, page: int, bbox: list[float] | None) -> list[dict]:
    if not docai:
        return []
    page_formulas = [f for f in docai.get("formulas", []) if int(f.get("page", -1)) == int(page)]
    if not bbox:
        return page_formulas
    return [f for f in page_formulas if bbox_overlap(f.get("bbox"), bbox) > 0.15]


def deterministic_issues(candidate_text: str, formulas: Iterable[dict]) -> list[dict]:
    issues: list[dict] = []
    for formula in formulas:
        latex = str(formula.get("latex", ""))
        if latex and not formula_matches_candidate(latex, candidate_text):
            issues.append({
                "field": "statement",
                "issue_type": "math_ocr_disagreement",
                "severity": "warning",
                "message": "Document AI Math OCR found a formula whose high-risk tokens do not clearly match the transcription.",
                "source_excerpt": latex,
                "candidate_excerpt": "",
            })
    return issues


def confidence_score(verifier_score: float | None, issues: list[dict], uncertainties: list[str], quality: float | None = None) -> float:
    score = 0.97 if verifier_score is None else max(0.0, min(1.0, verifier_score))
    for issue in issues:
        sev = issue.get("severity", "warning")
        score -= {"critical": 0.30, "warning": 0.08, "info": 0.02}.get(sev, 0.05)
    score -= min(0.20, 0.04 * len(uncertainties or []))
    if quality is not None and quality < 0.5:
        score -= min(0.15, (0.5 - quality) * 0.3)
    return round(max(0.0, min(1.0, score)), 4)


def status_from(score: float, issues: list[dict]) -> str:
    if any(i.get("severity") == "critical" for i in issues) or score < 0.90:
        return "FAILED"
    if score < 0.985 or issues:
        return "REVIEW"
    return "VERIFIED"
