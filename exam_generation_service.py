"""Metadata and blueprint driven exam selection."""
from __future__ import annotations

import hashlib, json, random, re
from collections import Counter
from pydantic import BaseModel, Field, model_validator


class QuestionSelectionFilter(BaseModel):
    grade: str | None = None
    subject: str | None = None
    chapter: str | None = None
    topic: str | None = None
    subtopic: str | None = None
    difficulty: str | None = None
    question_type: str | None = None
    tags: list[str] = Field(default_factory=list)
    source_types: list[str] = Field(default_factory=list)
    verification_statuses: list[str] = Field(default_factory=list)
    min_confidence: float | None = Field(default=None, ge=0, le=1)


class ExamBlueprintRule(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    count: int = Field(ge=1, le=200)
    filters: QuestionSelectionFilter = Field(default_factory=QuestionSelectionFilter)


class ExamBlueprint(BaseModel):
    exam_name: str = Field(min_length=1, max_length=200)
    exam_type: str = ""
    total_questions: int = Field(ge=1, le=200)
    duration_minutes: int = Field(default=30, ge=1, le=1440)
    prompt: str = Field(default="", max_length=4000)
    global_filters: QuestionSelectionFilter = Field(default_factory=QuestionSelectionFilter)
    rules: list[ExamBlueprintRule] = Field(min_length=1, max_length=100)
    allow_controlled_fallback: bool = False
    prefer_least_used: bool = True
    exclude_question_ids: list[int] = Field(default_factory=list)
    random_seed: int = 0

    @model_validator(mode="after")
    def counts_match(self):
        if sum(rule.count for rule in self.rules) != self.total_questions:
            raise ValueError("Blueprint rule counts must equal total questions")
        if len({rule.id for rule in self.rules}) != len(self.rules):
            raise ValueError("Blueprint rule IDs must be unique")
        return self


def norm(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower().replace("class ", "grade "))


def _json(value, default):
    try: return json.loads(value or "")
    except (TypeError, ValueError): return default


def public_question(row) -> dict:
    return {k: row.get(k) for k in ("id","subject","chapter","topic","subtopic","exam","qtype","difficulty","marks","statement","source_type","verification_status","confidence","tags")} | {"usage_count": int(row.get("usage_count") or 0)}


def structurally_valid(q: dict) -> bool:
    if not norm(q.get("statement")) or not norm(q.get("answer")): return False
    kind=norm(q.get("qtype"))
    if "mcq" in kind or "single" in kind or "multiple" in kind:
        options=_json(q.get("options"), [])
        cleaned=[norm(x) for x in options if norm(x)]
        if len(cleaned) < 2 or len(cleaned) != len(set(cleaned)): return False
        answer=norm(q.get("answer"))
        valid_letters={chr(97+i) for i in range(len(cleaned))}
        if not any(token in valid_letters for token in re.findall(r"[a-z]", answer)): return False
    return True


def _contains(actual, expected): return not expected or norm(expected) == norm(actual)


def matches(q: dict, filters: QuestionSelectionFilter, relax: str | None = None) -> bool:
    values=filters.model_dump()
    for field in ("subject","chapter","topic","subtopic","difficulty"):
        if field == relax: continue
        if values[field] and not _contains(q.get(field), values[field]): return False
    if values["question_type"] and not _contains(q.get("qtype"), values["question_type"]): return False
    if values["grade"]:
        grade_haystack=" ".join(str(q.get(k) or "") for k in ("exam","tags","generation_metadata"))
        if norm(values["grade"]) not in norm(grade_haystack): return False
    if values["source_types"] and norm(q.get("source_type")) not in {norm(x) for x in values["source_types"]}: return False
    if values["verification_statuses"] and norm(q.get("verification_status")) not in {norm(x) for x in values["verification_statuses"]}: return False
    if values["min_confidence"] is not None and float(q.get("confidence") or 0) < values["min_confidence"]: return False
    tags=norm(q.get("tags"))
    if any(norm(tag) not in tags for tag in values["tags"]): return False
    return True


def combined(global_filters: QuestionSelectionFilter, local: QuestionSelectionFilter) -> QuestionSelectionFilter:
    data=global_filters.model_dump()
    for key,value in local.model_dump().items():
        if value not in (None, "", []): data[key]=value
    return QuestionSelectionFilter(**data)


def load_candidates(conn, blueprint: ExamBlueprint) -> list[dict]:
    clauses=["q.statement<>''", "q.id NOT IN (SELECT question_id FROM exam_questions WHERE exam_id IN (SELECT id FROM exams WHERE status IN ('OPEN','PUBLISHED')))" if False else "1=1"]
    params=[]
    if blueprint.global_filters.subject:
        clauses.append("lower(q.subject)=lower(?)");params.append(blueprint.global_filters.subject)
    if blueprint.exclude_question_ids:
        clauses.append("q.id NOT IN (%s)" % ",".join("?" for _ in blueprint.exclude_question_ids));params.extend(blueprint.exclude_question_ids)
    sql=f"""SELECT q.*,COALESCE(u.usage_count,0) usage_count,COALESCE(u.last_used_at,0) last_used_at
      FROM questions q LEFT JOIN (SELECT question_id,COUNT(*) usage_count,MAX(created_at) last_used_at FROM exam_questions GROUP BY question_id) u ON u.question_id=q.id
      WHERE {' AND '.join(clauses)} ORDER BY q.id"""
    return [dict(row) for row in conn.execute(sql,tuple(params)).fetchall() if structurally_valid(dict(row))]


def availability(conn, blueprint: ExamBlueprint) -> dict:
    pool=load_candidates(conn,blueprint);rows=[]
    for rule in blueprint.rules:
        effective=combined(blueprint.global_filters,rule.filters)
        exact=[q for q in pool if matches(q,effective)]
        rows.append({"rule_id":rule.id,"label":" / ".join(x for x in (effective.chapter,effective.topic,effective.difficulty,effective.question_type) if x) or "All matching questions","requested":rule.count,"available":len(exact),"status":"READY" if len(exact)>=rule.count else "SHORTAGE"})
    return {"ready":all(x["status"]=="READY" for x in rows),"requested":blueprint.total_questions,"rules":rows}


def _fingerprint(statement: str) -> str:
    return hashlib.sha256(re.sub(r"\W+","",norm(statement)).encode()).hexdigest()


def generate(conn, blueprint: ExamBlueprint) -> dict:
    pool=load_candidates(conn,blueprint);chosen=[];used_ids=set();fingerprints=set();summaries=[];fallback_count=0
    prompt_terms={x for x in re.findall(r"[a-z0-9]+",norm(blueprint.prompt)) if len(x)>2}
    rng=random.Random(blueprint.random_seed)
    for rule in blueprint.rules:
        effective=combined(blueprint.global_filters,rule.filters)
        exact=[q for q in pool if matches(q,effective) and q["id"] not in used_ids and _fingerprint(q["statement"]) not in fingerprints]
        def rank(q):
            haystack=norm(" ".join(str(q.get(k) or "") for k in ("statement","chapter","topic","subtopic","tags","exam")))
            prompt_score=sum(term in haystack for term in prompt_terms)
            quality={"approved":3,"ai_validated":2,"verified":2}.get(norm(q.get("verification_status")),0)
            return (-quality,-float(q.get("confidence") or 0),q.get("usage_count",0),-prompt_score,rng.random())
        exact.sort(key=rank);selected=exact[:rule.count];fallback=[]
        if len(selected)<rule.count and blueprint.allow_controlled_fallback:
            for relaxed in ("subtopic","topic"):
                candidates=[q for q in pool if q["id"] not in used_ids and q not in selected and matches(q,effective,relaxed) and _fingerprint(q["statement"]) not in fingerprints]
                candidates.sort(key=rank)
                for q in candidates:
                    if len(selected)>=rule.count:break
                    selected.append(q);fallback.append(q["id"])
                if len(selected)>=rule.count:break
        if len(selected)<rule.count:
            raise ValueError(f"Only {len(selected)} matching questions are available for {rule.id}; {rule.count} were requested.")
        for q in selected: used_ids.add(q["id"]);fingerprints.add(_fingerprint(q["statement"]));chosen.append(public_question(q)|{"rule_id":rule.id,"fallback":q["id"] in fallback})
        fallback_count+=len(fallback);summaries.append({"rule_id":rule.id,"requested":rule.count,"selected":len(selected),"fallback":len(fallback)})
    return {"questions":chosen,"summary":{"requested":blueprint.total_questions,"selected":len(chosen),"exact_matches":len(chosen)-fallback_count,"fallback_matches":fallback_count,"rules":summaries,"difficulty":dict(Counter(q["difficulty"] or "Unspecified" for q in chosen)),"question_type":dict(Counter(q["qtype"] or "Unspecified" for q in chosen)),"chapter":dict(Counter(q["chapter"] or "Unspecified" for q in chosen))}}
