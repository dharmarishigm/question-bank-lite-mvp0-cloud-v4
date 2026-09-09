"""Programs and immutable blueprint workflows using existing session/CSRF authorization."""
from contextlib import closing
import json
import time

from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import Field, ValidationError
from typing import Literal

from platform_api import _auth, db, require_admin
from blueprint_domain import Contract, ProgramInput, canonical, content_hash, validate_payload, effective_profiles, compile_slots

router = APIRouter(prefix='/api/programs', tags=['Programs'])


def audit(conn, user, program, action, entity, details=None):
    conn.execute('INSERT INTO blueprint_audit_events(program_id,actor_id,action,entity_id,details_json,created_at) VALUES(?,?,?,?,?,?)',
                 (program, user['id'], action, entity, canonical(details or {}), time.time()))


def program_row(conn, pid, active=False):
    row = conn.execute('SELECT * FROM programs WHERE id=?', (pid,)).fetchone()
    if not row:
        raise HTTPException(404, 'Program not found')
    if active and row['status'] == 'ARCHIVED':
        raise HTTPException(409, 'Restore this program before editing it')
    return dict(row)


def unpack(row):
    result = dict(row)
    for key in list(result):
        if key.endswith('_json'):
            result[key[:-5]] = json.loads(result.pop(key))
    return result


@router.get('')
def programs(request: Request, q: str = Query('', max_length=200), status: str = '', offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100), sort: Literal['name','code','updated_at'] = 'name', direction: Literal['asc','desc'] = 'asc'):
    user = _auth(request)
    clauses, params = ['(LOWER(name) LIKE ? OR LOWER(code) LIKE ?)'], ['%' + q.lower() + '%'] * 2
    if user['role'] != 'ADMIN':
        clauses.append("status='ACTIVE'")
    elif status:
        clauses.append('status=?')
        params.append(status)
    where = ' AND '.join(clauses)
    with closing(db()) as conn:
        total = conn.execute('SELECT COUNT(*) n FROM programs WHERE ' + where, params).fetchone()['n']
        rows = conn.execute('SELECT * FROM programs WHERE ' + where + ' ORDER BY ' + sort + ' ' + direction + ',id LIMIT ? OFFSET ?', (*params, limit, offset)).fetchall()
        items = []
        for row in rows:
            item = unpack(row)
            item['blueprint_counts'] = {r['kind']: r['n'] for r in conn.execute('SELECT kind,COUNT(*) n FROM blueprints WHERE program_id=? GROUP BY kind', (row['id'],)).fetchall()}
            item['published_count'] = conn.execute("SELECT COUNT(*) n FROM blueprint_versions v JOIN blueprints b ON b.id=v.blueprint_id WHERE b.program_id=? AND v.status='PUBLISHED'", (row['id'],)).fetchone()['n']
            items.append(item)
        return {'items': items, 'total': total, 'offset': offset, 'limit': limit}


@router.post('', status_code=201)
def create_program(data: ProgramInput, request: Request):
    user = require_admin(_auth(request, True))
    with closing(db()) as conn:
        now = time.time()
        cur = conn.execute('INSERT INTO programs(code,name,payload_json,status,created_by,updated_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(code) DO NOTHING',
                           (data.code, data.name, canonical(data), data.status, user['id'], user['id'], now, now))
        if not cur.rowcount:
            raise HTTPException(409, 'Program code already exists')
        audit(conn, user, cur.lastrowid, 'PROGRAM_CREATED', cur.lastrowid)
        result = unpack(program_row(conn, cur.lastrowid))
        conn.commit()
        return result


@router.get('/contracts/all')
def contracts(request: Request):
    require_admin(_auth(request))
    from blueprint_domain import CONTRACTS, QuestionProfile, Difficulty
    schemas = {kind: contract.model_json_schema() for kind, contract in CONTRACTS.items()}
    question = schemas['QUESTION_GENERATOR']
    profile = QuestionProfile.model_json_schema()
    profile.pop('required', None)
    for prop in profile['properties'].values():
        prop.pop('default', None)
    question['properties']['overrides'] = {'type': 'object', 'properties': {d.value: profile for d in Difficulty}}
    exam = schemas['EXAM_GENERATOR']
    exam['$defs']['SlotRule']['properties']['difficulty'] = {'type': 'object', 'required': [d.value for d in Difficulty], 'properties': {d.value: {'type': 'number', 'minimum': 0, 'maximum': 100, 'default': 100 if d.value == 'MEDIUM' else 0} for d in Difficulty}}
    for name, contract in {'Evidence':EvidenceInput, 'EvidenceReview':EvidenceReview, 'Curriculum':CurriculumInput, 'Node':NodeInput, 'HistoricalObservation':HistoricalObservation, 'ClassificationReview':ClassificationReview, 'Profile':ProfileInput, 'Prompt':PromptInput, 'Refine':RefineInput, 'Inventory':InventoryInput, 'InventoryReview':InventoryReview, 'Run':RunInput, 'GenerateGap':GenerateGapInput}.items():
        schemas[name] = contract.model_json_schema()
    return schemas


@router.get('/{pid}')
def get_program(pid: int, request: Request):
    user = _auth(request)
    with closing(db()) as conn:
        row = program_row(conn, pid)
        if user['role'] != 'ADMIN' and row['status'] != 'ACTIVE':
            raise HTTPException(404, 'Program not found')
        return unpack(row)


@router.put('/{pid}')
def update_program(pid: int, data: ProgramInput, request: Request, revision: int = Query(..., ge=1)):
    user = require_admin(_auth(request, True))
    with closing(db()) as conn:
        old = program_row(conn, pid, True)
        if data.code != old['code']:
            raise HTTPException(422, 'Program code is a stable identity and cannot be changed')
        cur = conn.execute("UPDATE programs SET name=?,payload_json=?,status=?,revision=revision+1,updated_by=?,updated_at=? WHERE id=? AND revision=? AND status<>'ARCHIVED'",
                           (data.name, canonical(data), data.status, user['id'], time.time(), pid, revision))
        if not cur.rowcount:
            raise HTTPException(409, 'Program changed. Reload before saving')
        audit(conn, user, pid, 'PROGRAM_UPDATED', pid)
        result = unpack(program_row(conn, pid))
        conn.commit()
        return result


def program_state(pid, request, revision, status):
    user = require_admin(_auth(request, True))
    with closing(db()) as conn:
        program_row(conn, pid)
        cur = conn.execute('UPDATE programs SET status=?,revision=revision+1,updated_by=?,updated_at=? WHERE id=? AND revision=?',
                           (status, user['id'], time.time(), pid, revision))
        if not cur.rowcount:
            raise HTTPException(409, 'Program changed. Reload before saving')
        audit(conn, user, pid, 'PROGRAM_' + status, pid)
        conn.commit()
    return {'status': status}


@router.delete('/{pid}')
def archive(pid: int, request: Request, revision: int = Query(..., ge=1)):
    return program_state(pid, request, revision, 'ARCHIVED')


@router.post('/{pid}/restore')
def restore(pid: int, request: Request, revision: int = Query(..., ge=1)):
    return program_state(pid, request, revision, 'ACTIVE')


class BlueprintInput(Contract):
    kind: str
    name: str = Field(min_length=1, max_length=200)
    payload: dict
    summary: str = Field(default='Initial version', max_length=2000)


class VersionInput(Contract):
    revision: int = Field(ge=1)
    payload: dict
    summary: str = Field(min_length=1, max_length=2000)


def validated(kind, payload):
    try:
        return validate_payload(kind, payload)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, str(exc)) from exc


def blueprint_row(conn, pid, bid):
    row = conn.execute('SELECT * FROM blueprints WHERE id=? AND program_id=?', (bid, pid)).fetchone()
    if not row:
        raise HTTPException(404, 'Blueprint not found')
    return dict(row)


def dependency(conn, pid, vid, kind=None, published=False):
    row = conn.execute('SELECT v.*,b.kind,b.program_id FROM blueprint_versions v JOIN blueprints b ON b.id=v.blueprint_id WHERE v.id=? AND b.program_id=?', (vid, pid)).fetchone()
    if not row or (kind and row['kind'] != kind):
        raise HTTPException(422, 'Blueprint dependency must exist in this program and have the correct type')
    if published and row['status'] != 'PUBLISHED':
        raise HTTPException(422, 'Publish referenced blueprint versions first')
    return unpack(row)


def validate_dependencies(conn, pid, kind, payload, publishing=False):
    for sid in payload.get('official_source_ids', []) + payload.get('historical_source_ids', []):
        if not conn.execute('SELECT id FROM blueprint_sources WHERE id=? AND program_id=?', (sid, pid)).fetchone():
            raise HTTPException(422, 'Evidence references must exist in this program')
    curriculum_id = payload.get('curriculum_version_id')
    if curriculum_id:
        curriculum = conn.execute('SELECT * FROM curriculum_versions WHERE id=? AND program_id=?', (curriculum_id, pid)).fetchone()
        if not curriculum or (publishing and curriculum['status'] != 'PUBLISHED'):
            raise HTTPException(422, 'Curriculum must belong to the program and be published before use')
    nodes = [payload.get('curriculum_node_id')] + [r.get('curriculum_node_id') for r in payload.get('rules', [])]
    for node in filter(None, nodes):
        if not conn.execute('SELECT n.id FROM curriculum_nodes n JOIN curriculum_versions v ON v.id=n.version_id WHERE n.id=? AND v.program_id=?', (node, pid)).fetchone():
            raise HTTPException(422, 'Curriculum node must belong to this program')
    if payload.get('prompt_version_id') and not conn.execute('SELECT id FROM blueprint_prompts WHERE id=? AND program_id=?', (payload['prompt_version_id'], pid)).fetchone():
        raise HTTPException(422, 'Prompt version must exist in this program')
    if payload.get('historical_profile_id') and not conn.execute('SELECT id FROM historical_profiles WHERE id=? AND program_id=?', (payload['historical_profile_id'], pid)).fetchone():
        raise HTTPException(422, 'Historical profile must exist in this program')
    if kind == 'EXAM_GENERATOR':
        pattern = dependency(conn, pid, payload['pattern_version_id'], 'EXAM_PATTERN', publishing)
        for rule in payload['rules']:
            dependency(conn, pid, rule['question_blueprint_version_id'], 'QUESTION_GENERATOR', publishing)
            node_id = rule.get('curriculum_node_id')
            if node_id and not conn.execute('SELECT id FROM curriculum_nodes WHERE id=? AND version_id=?', (node_id, pattern['payload'].get('curriculum_version_id'))).fetchone():
                raise HTTPException(422, 'Slot curriculum node must belong to the exact pattern curriculum version')
        try:
            compile_slots(pattern['payload'], payload)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    if kind == 'QUESTION_GENERATOR' and payload.get('parent_version_id'):
        seen, vid = set(), payload['parent_version_id']
        order = ['GLOBAL','PROGRAM','EXAM','SUBJECT','CHAPTER','TOPIC','SUBTOPIC']
        child_scope = payload['scope']
        while vid:
            if vid in seen or len(seen) > 20:
                raise HTTPException(422, 'Circular or excessive inheritance')
            seen.add(vid)
            parent = dependency(conn, pid, vid, kind, publishing)
            if order.index(parent['payload']['scope']) >= order.index(child_scope):
                raise HTTPException(422, 'Parent blueprint must be a higher inheritance scope')
            child_scope = parent['payload']['scope']
            vid = parent['payload'].get('parent_version_id')
    if publishing and kind == 'EXAM_PATTERN':
        if payload['sample_only']:
            raise HTTPException(422, 'Sample patterns cannot be published for production')
        if not payload['official_source_ids']:
            raise HTTPException(422, 'Store and approve official evidence before publishing an exam pattern')
        for sid in payload['official_source_ids']:
            source = conn.execute("SELECT id FROM blueprint_sources WHERE id=? AND program_id=? AND included=1 AND review_status='APPROVED' AND kind IN ('OFFICIAL_NOTIFICATION','OFFICIAL_SYLLABUS','OFFICIAL_SAMPLE_PAPER')", (sid, pid)).fetchone()
            if not source:
                raise HTTPException(422, 'Official evidence must be included and approved in this program')


def save_version(conn, user, pid, bid, payload, summary, expected):
    bp = blueprint_row(conn, pid, bid)
    payload = validated(bp['kind'], payload)
    validate_dependencies(conn, pid, bp['kind'], payload)
    cur = conn.execute('UPDATE blueprints SET revision=revision+1 WHERE id=? AND revision=?', (bid, expected))
    if not cur.rowcount:
        raise HTTPException(409, 'Blueprint changed. Reload before saving')
    parent = conn.execute('SELECT id FROM blueprint_versions WHERE blueprint_id=? ORDER BY version_number DESC LIMIT 1', (bid,)).fetchone()
    version = conn.execute('INSERT INTO blueprint_versions(blueprint_id,version_number,parent_version_id,payload_json,payload_hash,origin,summary,validation_json,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                           (bid, expected + 1, parent['id'] if parent else None, canonical(payload), content_hash(payload), 'MANUAL', summary, '{"valid":true}', user['id'], time.time()))
    audit(conn, user, pid, 'BLUEPRINT_VERSION_CREATED', version.lastrowid, {'hash': content_hash(payload)})
    return unpack(conn.execute('SELECT * FROM blueprint_versions WHERE id=?', (version.lastrowid,)).fetchone())


@router.get('/{pid}/blueprints')
def list_blueprints(pid: int, request: Request):
    user = _auth(request)
    with closing(db()) as conn:
        program_row(conn, pid)
        if user['role'] == 'ADMIN':
            rows = conn.execute('SELECT * FROM blueprints WHERE program_id=? ORDER BY id DESC', (pid,)).fetchall()
        else:
            rows = conn.execute("SELECT b.* FROM blueprints b JOIN programs p ON p.id=b.program_id WHERE b.program_id=? AND p.status='ACTIVE' AND EXISTS(SELECT 1 FROM blueprint_versions v WHERE v.blueprint_id=b.id AND v.status='PUBLISHED') ORDER BY b.id DESC", (pid,)).fetchall()
        return [dict(r) for r in rows]


@router.post('/{pid}/blueprints', status_code=201)
def create_blueprint(pid: int, data: BlueprintInput, request: Request):
    user = require_admin(_auth(request, True))
    validated(data.kind, data.payload)
    with closing(db()) as conn:
        program_row(conn, pid, True)
        bid = conn.execute('INSERT INTO blueprints(program_id,kind,name,created_by,created_at) VALUES(?,?,?,?,?)',
                           (pid, data.kind, data.name, user['id'], time.time())).lastrowid
        version = save_version(conn, user, pid, bid, data.payload, data.summary, 0)
        conn.commit()
        return {'id': bid, 'version': version}


@router.get('/{pid}/blueprints/{bid}/versions')
def versions(pid: int, bid: int, request: Request):
    user = _auth(request)
    with closing(db()) as conn:
        program = program_row(conn, pid)
        if user['role'] != 'ADMIN' and program['status'] != 'ACTIVE':
            raise HTTPException(404, 'Program not found')
        blueprint_row(conn, pid, bid)
        where = '' if user['role'] == 'ADMIN' else " AND status='PUBLISHED'"
        return [unpack(r) for r in conn.execute('SELECT * FROM blueprint_versions WHERE blueprint_id=?' + where + ' ORDER BY version_number DESC', (bid,)).fetchall()]


@router.post('/{pid}/blueprints/{bid}/versions', status_code=201)
def new_version(pid: int, bid: int, data: VersionInput, request: Request):
    user = require_admin(_auth(request, True))
    with closing(db()) as conn:
        program_row(conn, pid, True)
        result = save_version(conn, user, pid, bid, data.payload, data.summary, data.revision)
        conn.commit()
        return result


@router.get('/{pid}/blueprints/{bid}/effective/{vid}')
def effective(pid: int, bid: int, vid: int, request: Request):
    require_admin(_auth(request))
    with closing(db()) as conn:
        root = dependency(conn, pid, vid, 'QUESTION_GENERATOR')
        if root['blueprint_id'] != bid:
            raise HTTPException(404, 'Version does not belong to this blueprint')
        chain, seen = [], set()
        while vid:
            if vid in seen or len(seen) > 20:
                raise HTTPException(422, 'Circular or excessive inheritance')
            seen.add(vid)
            row = dependency(conn, pid, vid, 'QUESTION_GENERATOR')
            chain.append(row['payload'])
            vid = row['payload'].get('parent_version_id')
        return {'effective': effective_profiles(reversed(chain)), 'overrides': root['payload']['overrides']}


@router.get('/{pid}/audit')
def audit_history(pid: int, request: Request):
    require_admin(_auth(request))
    with closing(db()) as conn:
        program_row(conn, pid)
        return [unpack(r) for r in conn.execute('SELECT * FROM blueprint_audit_events WHERE program_id=? ORDER BY id DESC LIMIT 200', (pid,)).fetchall()]


class Transition(Contract):
    status: Literal['IN_REVIEW', 'PUBLISHED', 'RETIRED']
    expected_status: Literal['DRAFT', 'IN_REVIEW', 'PUBLISHED']
    reason: str = Field(min_length=1, max_length=2000)


@router.post('/{pid}/blueprints/{bid}/versions/{vid}/transition')
def transition(pid: int, bid: int, vid: int, data: Transition, request: Request):
    user = require_admin(_auth(request, True))
    allowed = {('DRAFT', 'IN_REVIEW'), ('IN_REVIEW', 'PUBLISHED'), ('PUBLISHED', 'RETIRED')}
    if (data.expected_status, data.status) not in allowed:
        raise HTTPException(422, 'Submit a draft for review before publishing; published versions can only be retired')
    with closing(db()) as conn:
        program_row(conn, pid, True)
        row = dependency(conn, pid, vid)
        if row['blueprint_id'] != bid:
            raise HTTPException(404, 'Version not found')
        if data.status == 'PUBLISHED':
            validated(row['kind'], row['payload'])
            validate_dependencies(conn, pid, row['kind'], row['payload'], True)
        cur = conn.execute('UPDATE blueprint_versions SET status=? WHERE id=? AND status=?', (data.status, vid, data.expected_status))
        if not cur.rowcount:
            raise HTTPException(409, 'Version changed. Reload before reviewing')
        audit(conn, user, pid, 'VERSION_' + data.status, vid, {'reason': data.reason})
        conn.commit()
    return {'id': vid, 'status': data.status}


@router.post('/{pid}/blueprints/{bid}/clone')
def clone(pid: int, bid: int, request: Request, version_id: int, name: str = Query(..., min_length=1, max_length=200)):
    user = require_admin(_auth(request, True))
    with closing(db()) as conn:
        program_row(conn, pid, True)
        source = dependency(conn, pid, version_id)
        if source['blueprint_id'] != bid:
            raise HTTPException(404, 'Version not found')
        cloned = conn.execute('INSERT INTO blueprints(program_id,kind,name,created_by,created_at) VALUES(?,?,?,?,?)',
                              (pid, source['kind'], name, user['id'], time.time())).lastrowid
        version = save_version(conn, user, pid, cloned, source['payload'], 'Cloned from version ' + str(version_id), 0)
        conn.execute("UPDATE blueprint_versions SET origin='CLONED' WHERE id=?", (version['id'],))
        audit(conn, user, pid, 'BLUEPRINT_CLONED', cloned, {'source_version_id': version_id})
        conn.commit()
        return {'id': cloned, 'version': version}


@router.get('/{pid}/blueprints/{bid}/compare')
def compare(pid: int, bid: int, request: Request, left: int, right: int):
    require_admin(_auth(request))
    with closing(db()) as conn:
        versions = [dependency(conn, pid, v) for v in (left, right)]
        if any(v['blueprint_id'] != bid for v in versions):
            raise HTTPException(404, 'Versions must belong to this blueprint')
        def differences(a, b, path=''):
            if isinstance(a, dict) and isinstance(b, dict):
                return [change for key in sorted(set(a) | set(b)) for change in differences(a.get(key), b.get(key), path + '/' + key)]
            return [] if a == b else [{'path': path, 'old': a, 'new': b}]
        return {'left': versions[0], 'right': versions[1], 'changes': differences(versions[0]['payload'], versions[1]['payload'])}


@router.post('/{pid}/blueprints/{bid}/versions/{vid}/validate')
def validate_version(pid: int, bid: int, vid: int, request: Request):
    require_admin(_auth(request, True))
    with closing(db()) as conn:
        row = dependency(conn, pid, vid)
        if row['blueprint_id'] != bid:
            raise HTTPException(404, 'Version not found')
        validated(row['kind'], row['payload'])
        validate_dependencies(conn, pid, row['kind'], row['payload'])
        return {'valid': True, 'payload_hash': content_hash(row['payload'])}


class EvidenceInput(Contract):
    kind: Literal['OFFICIAL_NOTIFICATION','OFFICIAL_SYLLABUS','OFFICIAL_SAMPLE_PAPER','HISTORICAL_QUESTION_PAPER','INTERNAL_QUESTION_BANK','OTHER_REFERENCE']
    uri: str = Field(pattern=r'^(https://|gs://)', max_length=2000)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    filename: str = Field(min_length=1, max_length=250)
    mime_type: str = Field(min_length=1, max_length=100)
    authority: str = Field(min_length=1, max_length=250)
    edition: str = Field(min_length=1, max_length=100)
    language: str = Field(min_length=1, max_length=100)
    page_references: list[str] = Field(default_factory=list, max_length=100)
    authorized_use: Literal[True]


@router.post('/{pid}/sources', status_code=201)
def register_evidence(pid: int, data: EvidenceInput, request: Request):
    user = require_admin(_auth(request, True))
    with closing(db()) as conn:
        program_row(conn, pid, True)
        sid = conn.execute('INSERT INTO blueprint_sources(program_id,kind,payload_json,sha256,created_by,created_at) VALUES(?,?,?,?,?,?)',
                           (pid, data.kind, canonical(data), data.sha256, user['id'], time.time())).lastrowid
        audit(conn, user, pid, 'EVIDENCE_REGISTERED', sid)
        conn.commit()
        return {'id': sid, 'review_status': 'IN_REVIEW', 'checksum_verified': False}


@router.get('/{pid}/sources')
def list_evidence(pid: int, request: Request):
    require_admin(_auth(request))
    with closing(db()) as conn:
        program_row(conn, pid)
        return [unpack(r) for r in conn.execute('SELECT * FROM blueprint_sources WHERE program_id=? ORDER BY id DESC', (pid,)).fetchall()]


class EvidenceReview(Contract):
    status: Literal['APPROVED','REJECTED']
    included: bool
    reason: str = Field(min_length=1, max_length=2000)
    checksum_checked: Literal[True]


@router.post('/{pid}/sources/{sid}/review')
def review_evidence(pid: int, sid: int, data: EvidenceReview, request: Request):
    user = require_admin(_auth(request, True))
    with closing(db()) as conn:
        program_row(conn, pid, True)
        cur = conn.execute('UPDATE blueprint_sources SET included=?,review_status=? WHERE id=? AND program_id=?', (int(data.included), data.status, sid, pid))
        if not cur.rowcount:
            raise HTTPException(404, 'Source not found')
        audit(conn, user, pid, 'EVIDENCE_REVIEWED', sid, data.model_dump())
        conn.commit()
        return {'id': sid, 'status': data.status}


class CurriculumInput(Contract):
    name: str = Field(min_length=1, max_length=200)


class NodeInput(Contract):
    parent_id: int | None = Field(default=None, gt=0)
    kind: Literal['SUBJECT','CHAPTER','TOPIC','SUBTOPIC','LEARNING_OUTCOME']
    name: str = Field(min_length=1, max_length=200)
    learning_outcome: str = Field(default='', max_length=2000)


@router.post('/{pid}/curricula', status_code=201)
def create_curriculum(pid: int, data: CurriculumInput, request: Request):
    user = require_admin(_auth(request, True))
    with closing(db()) as conn:
        program_row(conn, pid, True)
        vid = conn.execute('INSERT INTO curriculum_versions(program_id,name,created_by,created_at) VALUES(?,?,?,?)', (pid, data.name, user['id'], time.time())).lastrowid
        audit(conn, user, pid, 'CURRICULUM_CREATED', vid)
        conn.commit()
        return {'id': vid, 'status': 'DRAFT'}


@router.get('/{pid}/curricula')
def curricula(pid: int, request: Request):
    require_admin(_auth(request))
    with closing(db()) as conn:
        program_row(conn, pid)
        rows = [dict(r) for r in conn.execute('SELECT * FROM curriculum_versions WHERE program_id=? ORDER BY id DESC', (pid,)).fetchall()]
        for row in rows:
            row['nodes'] = [dict(n) for n in conn.execute('SELECT * FROM curriculum_nodes WHERE version_id=? ORDER BY id', (row['id'],)).fetchall()]
        return rows


@router.post('/{pid}/curricula/{vid}/nodes', status_code=201)
def curriculum_node(pid: int, vid: int, data: NodeInput, request: Request):
    user = require_admin(_auth(request, True))
    with closing(db()) as conn:
        program_row(conn, pid, True)
        # Lock against concurrent publication without changing the curriculum payload.
        lock = conn.execute("UPDATE curriculum_versions SET status=status WHERE id=? AND program_id=? AND status='DRAFT'", (vid, pid))
        if not lock.rowcount:
            raise HTTPException(409, 'Curriculum not found or already published')
        order = ['SUBJECT','CHAPTER','TOPIC','SUBTOPIC','LEARNING_OUTCOME']
        if data.parent_id:
            parent = conn.execute('SELECT * FROM curriculum_nodes WHERE id=? AND version_id=?', (data.parent_id, vid)).fetchone()
            if not parent or order.index(parent['kind']) >= order.index(data.kind):
                raise HTTPException(422, 'Parent must be a higher scope in this curriculum')
        elif data.kind != 'SUBJECT':
            raise HTTPException(422, 'A non-subject node requires a parent')
        nid = conn.execute('INSERT INTO curriculum_nodes(version_id,parent_id,kind,name,learning_outcome) VALUES(?,?,?,?,?)', (vid, data.parent_id, data.kind, data.name, data.learning_outcome)).lastrowid
        audit(conn, user, pid, 'CURRICULUM_NODE_CREATED', nid)
        conn.commit()
        return {'id': nid}


@router.post('/{pid}/curricula/{vid}/publish')
def publish_curriculum(pid: int, vid: int, request: Request):
    user = require_admin(_auth(request, True))
    with closing(db()) as conn:
        program_row(conn, pid, True)
        cur = conn.execute("UPDATE curriculum_versions SET status='PUBLISHED' WHERE id=? AND program_id=? AND status='DRAFT'", (vid, pid))
        if not cur.rowcount:
            raise HTTPException(409, 'Curriculum not found or already published')
        if not conn.execute('SELECT id FROM curriculum_nodes WHERE version_id=? LIMIT 1', (vid,)).fetchone():
            raise HTTPException(422, 'Add curriculum nodes before publishing')
        audit(conn, user, pid, 'CURRICULUM_PUBLISHED', vid)
        conn.commit()
        return {'status': 'PUBLISHED'}


from blueprint_history import HistoricalObservation, aggregate


@router.post('/{pid}/historical-observations', status_code=201)
def add_observation(pid: int, data: HistoricalObservation, request: Request):
    user = require_admin(_auth(request, True))
    with closing(db()) as conn:
        program_row(conn, pid, True)
        source = conn.execute("SELECT id FROM blueprint_sources WHERE id=? AND program_id=? AND kind='HISTORICAL_QUESTION_PAPER' AND included=1 AND review_status='APPROVED'", (data.source_id, pid)).fetchone()
        if not source:
            raise HTTPException(422, 'Use an included, approved historical paper from this program')
        cur = conn.execute('INSERT INTO historical_observations(program_id,source_id,source_question_ref,payload_json,created_by,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(source_id,source_question_ref) DO NOTHING',
                           (pid, data.source_id, data.source_question_ref, canonical(data), user['id'], time.time()))
        if not cur.rowcount:
            raise HTTPException(409, 'This paper question already has a classification')
        audit(conn, user, pid, 'HISTORICAL_CLASSIFICATION_CREATED', cur.lastrowid)
        conn.commit()
        return {'id': cur.lastrowid, 'review_status': 'IN_REVIEW'}


@router.get('/{pid}/historical-observations')
def observations(pid: int, request: Request):
    require_admin(_auth(request))
    with closing(db()) as conn:
        program_row(conn, pid)
        return [unpack(r) for r in conn.execute('SELECT * FROM historical_observations WHERE program_id=? ORDER BY id', (pid,)).fetchall()]


class ClassificationReview(Contract):
    status: Literal['APPROVED', 'REJECTED']
    reason: str = Field(min_length=1, max_length=2000)


@router.post('/{pid}/historical-observations/{oid}/review')
def review_observation(pid: int, oid: int, data: ClassificationReview, request: Request):
    user = require_admin(_auth(request, True))
    with closing(db()) as conn:
        program_row(conn, pid, True)
        cur = conn.execute('UPDATE historical_observations SET review_status=? WHERE id=? AND program_id=?', (data.status, oid, pid))
        if not cur.rowcount:
            raise HTTPException(404, 'Classification not found')
        audit(conn, user, pid, 'HISTORICAL_CLASSIFICATION_REVIEWED', oid, data.model_dump())
        conn.commit()
        return {'id': oid, 'status': data.status}


class ProfileInput(Contract):
    reference_year: int = Field(ge=1900, le=2200)
    half_life_years: int = Field(default=5, ge=1, le=100)


@router.post('/{pid}/historical-profiles', status_code=201)
def create_profile(pid: int, data: ProfileInput, request: Request):
    user = require_admin(_auth(request, True))
    with closing(db()) as conn:
        program_row(conn, pid, True)
        rows = conn.execute("SELECT h.*,s.sha256,s.payload_json source_payload_json FROM historical_observations h JOIN blueprint_sources s ON s.id=h.source_id WHERE h.program_id=? AND h.review_status='APPROVED' AND s.included=1 AND s.review_status='APPROVED' AND s.kind='HISTORICAL_QUESTION_PAPER' ORDER BY h.id", (pid,)).fetchall()
        if not rows:
            raise HTTPException(422, 'Approve historical classifications and include their reviewed papers first')
        evidence = [unpack(r) for r in rows]
        try:
            payload = aggregate([r['payload'] for r in evidence], data.reference_year, data.half_life_years)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        cur = conn.execute('INSERT INTO historical_profiles(program_id,payload_json,evidence_json,payload_hash,created_by,created_at) VALUES(?,?,?,?,?,?)',
                           (pid, canonical(payload), canonical(evidence), content_hash({'profile': payload, 'evidence': evidence}), user['id'], time.time()))
        audit(conn, user, pid, 'HISTORICAL_PROFILE_CREATED', cur.lastrowid)
        conn.commit()
        return {'id': cur.lastrowid, 'payload': payload}


@router.get('/{pid}/historical-profiles')
def profiles(pid: int, request: Request):
    require_admin(_auth(request))
    with closing(db()) as conn:
        program_row(conn, pid)
        return [unpack(r) for r in conn.execute('SELECT * FROM historical_profiles WHERE program_id=? ORDER BY id DESC', (pid,)).fetchall()]


from fastapi import BackgroundTasks
from blueprint_gemini import PURPOSES, Proposal, apply_proposal, structured_call


class PromptInput(Contract):
    purpose: str
    template: str = Field(min_length=1, max_length=20000)
    expected_version: int = Field(default=0, ge=0)


@router.get('/{pid}/prompts')
def prompts(pid: int, request: Request):
    require_admin(_auth(request))
    with closing(db()) as conn:
        program_row(conn, pid)
        return {'purposes': PURPOSES, 'items': [dict(r) for r in conn.execute('SELECT * FROM blueprint_prompts WHERE program_id=? ORDER BY id DESC', (pid,)).fetchall()]}


@router.post('/{pid}/prompts', status_code=201)
def add_prompt(pid: int, data: PromptInput, request: Request):
    user = require_admin(_auth(request, True))
    if data.purpose not in PURPOSES:
        raise HTTPException(422, 'Unknown prompt purpose')
    with closing(db()) as conn:
        program_row(conn, pid, True)
        # Serialize writers on the program for monotonic immutable prompt versions.
        conn.execute('UPDATE programs SET revision=revision WHERE id=?', (pid,))
        number = conn.execute('SELECT COALESCE(MAX(version_number),0) n FROM blueprint_prompts WHERE program_id=? AND purpose=?', (pid, data.purpose)).fetchone()['n']
        if number != data.expected_version:
            raise HTTPException(409, 'Prompt changed. Reload its latest version')
        cur = conn.execute('INSERT INTO blueprint_prompts(program_id,purpose,version_number,template,payload_hash,created_by,created_at) VALUES(?,?,?,?,?,?,?)',
                           (pid, data.purpose, number+1, data.template, content_hash(data.template), user['id'], time.time()))
        audit(conn, user, pid, 'PROMPT_VERSION_CREATED', cur.lastrowid)
        conn.commit()
        return {'id': cur.lastrowid, 'version_number': number+1}


def run_refinement(rid):
    """Persisted state machine; a failed request never edits the source version."""
    with closing(db()) as conn:
        cur = conn.execute("UPDATE blueprint_refinements SET status='RUNNING',updated_at=? WHERE id=? AND status='QUEUED'", (time.time(), rid))
        if not cur.rowcount:
            return
        row = dict(conn.execute('SELECT * FROM blueprint_refinements WHERE id=?', (rid,)).fetchone())
        version = dependency(conn, row['program_id'], row['blueprint_version_id'])
        prompt = dict(conn.execute('SELECT * FROM blueprint_prompts WHERE id=?', (row['prompt_id'],)).fetchone())
        evidence = [unpack(r) for r in conn.execute("SELECT * FROM blueprint_sources WHERE program_id=? AND included=1 AND review_status='APPROVED'", (row['program_id'],)).fetchall()]
        conn.commit()
    try:
        proposal, telemetry = structured_call('BLUEPRINT_REFINEMENT', prompt['template'],
            {'kind':version['kind'], 'payload':version['payload'], 'evidence':[{'id':r['id'], 'kind':r['kind'], 'metadata':r['payload']} for r in evidence],
             'allowed_fields':'Question overrides: seconds, reasoning_steps, stem_max_words, distractor_strategy, solution_format, prohibited_patterns. Exam rules: seconds, cognitive_skill. All other fields are immutable.'}, Proposal)
        allowed_sources = {r['id'] for r in evidence}
        if any(set(p.evidence_source_ids)-allowed_sources for p in proposal.patches):
            raise ValueError('Proposal cites unapproved or nonexistent evidence')
        apply_proposal(version['kind'], version['payload'], proposal, list(range(len(proposal.patches))))
        telemetry['prompt_id'] = prompt['id']
        with closing(db()) as conn:
            conn.execute("UPDATE blueprint_refinements SET status='READY',proposal_json=?,telemetry_json=?,updated_at=? WHERE id=? AND status='RUNNING' AND updated_at=?", (canonical(proposal), canonical(telemetry), time.time(), rid, row['updated_at']))
            audit(conn, {'id':row['created_by']}, row['program_id'], 'GEMINI_REFINEMENT_READY', rid, telemetry)
            conn.commit()
    except Exception as exc:
        # No prompts, credentials, student records or provider stack traces in errors.
        with closing(db()) as conn:
            conn.execute("UPDATE blueprint_refinements SET status='FAILED',error=?,updated_at=? WHERE id=? AND status='RUNNING' AND updated_at=?", (type(exc).__name__ + ': Gemini proposal failed validation or delivery. Check configuration and retry.', time.time(), rid, row['updated_at']))
            audit(conn, {'id':row['created_by']}, row['program_id'], 'GEMINI_REFINEMENT_FAILED', rid, {'error_type':type(exc).__name__})
            conn.commit()


class RefineInput(Contract):
    version_id: int = Field(gt=0)
    prompt_id: int = Field(gt=0)


@router.post('/{pid}/refinements', status_code=202)
def refine(pid: int, data: RefineInput, request: Request, tasks: BackgroundTasks):
    user = require_admin(_auth(request, True))
    with closing(db()) as conn:
        program_row(conn, pid, True)
        version = dependency(conn, pid, data.version_id)
        if version['kind'] == 'EXAM_PATTERN':
            raise HTTPException(422, 'Official exam facts cannot be refined by Gemini')
        if not conn.execute("SELECT id FROM blueprint_prompts WHERE id=? AND program_id=? AND purpose='BLUEPRINT_REFINEMENT'", (data.prompt_id, pid)).fetchone():
            raise HTTPException(422, 'Select a blueprint-refinement prompt version from this program')
        cur = conn.execute('INSERT INTO blueprint_refinements(program_id,blueprint_version_id,prompt_id,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?)', (pid, data.version_id, data.prompt_id, user['id'], time.time(), time.time()))
        audit(conn, user, pid, 'GEMINI_REFINEMENT_REQUESTED', cur.lastrowid)
        conn.commit()
        tasks.add_task(run_refinement, cur.lastrowid)
        return {'id':cur.lastrowid, 'status':'QUEUED'}


@router.get('/{pid}/refinements')
def refinements(pid: int, request: Request):
    require_admin(_auth(request))
    with closing(db()) as conn:
        program_row(conn, pid)
        return [unpack(r) for r in conn.execute('SELECT * FROM blueprint_refinements WHERE program_id=? ORDER BY id DESC', (pid,)).fetchall()]


class AcceptProposal(Contract):
    accepted_indices: list[int] = Field(max_length=100)
    revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)
    training_eligible: bool = False


@router.post('/{pid}/refinements/{rid}/accept')
def accept_refinement(pid: int, rid: int, data: AcceptProposal, request: Request):
    user = require_admin(_auth(request, True))
    with closing(db()) as conn:
        program_row(conn, pid, True)
        cur = conn.execute("UPDATE blueprint_refinements SET status='ACCEPTED',decisions_json=?,updated_at=? WHERE id=? AND program_id=? AND status='READY'", (canonical(data), time.time(), rid, pid))
        if not cur.rowcount:
            raise HTTPException(409, 'Proposal is not ready or has already been reviewed')
        row = unpack(conn.execute('SELECT * FROM blueprint_refinements WHERE id=?', (rid,)).fetchone())
        version = dependency(conn, pid, row['blueprint_version_id'])
        bp = blueprint_row(conn, pid, version['blueprint_id'])
        if version['version_number'] != bp['revision']:
            raise HTTPException(409, 'A newer draft exists; request refinement from the latest version')
        try:
            payload = apply_proposal(version['kind'], version['payload'], Proposal.model_validate(row['proposal']), data.accepted_indices)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        result = save_version(conn, user, pid, bp['id'], payload, data.reason, data.revision)
        conn.execute("UPDATE blueprint_versions SET origin='GEMINI_REFINEMENT' WHERE id=?", (result['id'],))
        audit(conn, user, pid, 'GEMINI_PROPOSAL_REVIEWED', rid, {'new_version_id': result['id'], **data.model_dump()})
        conn.commit()
        return {**result, 'origin':'GEMINI_REFINEMENT'}


from blueprint_papers import Candidate, select


class InventoryInput(Contract):
    question_id: int | None = Field(default=None, gt=0)
    question_version_id: int | None = Field(default=None, gt=0)
    payload: Candidate
    provenance_note: str = Field(min_length=1, max_length=2000)


@router.post('/{pid}/inventory', status_code=201)
def add_inventory(pid: int, data: InventoryInput, request: Request):
    user = require_admin(_auth(request, True))
    with closing(db()) as conn:
        program_row(conn, pid, True)
        provenance = {'note':data.provenance_note}
        if bool(data.question_id) != bool(data.question_version_id):
            raise HTTPException(422, 'Link both the question and its exact version, or create a manual draft')
        if data.question_id:
            row = conn.execute('SELECT * FROM question_versions WHERE id=? AND question_id=?', (data.question_version_id, data.question_id)).fetchone()
            if not row:
                raise HTTPException(422, 'Question version does not exist')
            frozen = json.loads(row['payload_json'])
            # Taxonomy is mapped explicitly; source text, options and solution stay exact.
            if any(frozen.get(key) != getattr(data.payload, key) for key in ('statement','options','solution')):
                raise HTTPException(422, 'Imported content must match the original question version exactly')
            expected_answer = str(frozen.get('answer', '')).strip()
            if ','.join(data.payload.answers) != expected_answer:
                raise HTTPException(422, 'Answer must match the original version; ambiguous answer mappings require source review')
            provenance['source_snapshot'] = frozen
        cur = conn.execute('INSERT INTO blueprint_question_snapshots(program_id,question_id,question_version_id,payload_json,payload_hash,provenance_json,origin,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
            (pid,data.question_id,data.question_version_id,canonical(data.payload),content_hash(data.payload),canonical(provenance),'IMPORTED' if data.question_id else 'MANUAL',user['id'],time.time()))
        audit(conn,user,pid,'INVENTORY_DRAFT_CREATED',cur.lastrowid)
        conn.commit()
        return {'id':cur.lastrowid,'academic_status':'IN_REVIEW','transcription_status':'IN_REVIEW'}


@router.get('/{pid}/inventory')
def inventory(pid: int, request: Request):
    require_admin(_auth(request))
    with closing(db()) as conn:
        program_row(conn,pid)
        return inventory_rows(conn,pid)


def inventory_rows(conn,pid):
    return [unpack(r) for r in conn.execute('SELECT q.*,(SELECT COUNT(*) FROM paper_question_exposure e WHERE e.snapshot_id=q.id) exposure FROM blueprint_question_snapshots q WHERE program_id=? ORDER BY q.id', (pid,)).fetchall()]


class InventoryReview(Contract):
    academic_status: Literal['APPROVED','REJECTED']
    transcription_status: Literal['APPROVED','REJECTED']
    reason: str = Field(min_length=1,max_length=2000)
    checked_answer_solution: Literal[True]
    checked_source_fidelity: Literal[True]
    checked_curriculum_age_language: Literal[True]
    checked_duplicates_and_visuals: Literal[True]


@router.post('/{pid}/inventory/{qid}/review')
def review_inventory(pid: int,qid: int,data: InventoryReview,request: Request):
    user=require_admin(_auth(request,True))
    with closing(db()) as conn:
        program_row(conn,pid,True)
        row=conn.execute('SELECT * FROM blueprint_question_snapshots WHERE id=? AND program_id=?',(qid,pid)).fetchone()
        if not row: raise HTTPException(404,'Snapshot not found')
        if row['origin']=='GEMINI_GENERATED' and data.academic_status=='APPROVED':
            provenance=json.loads(row['provenance_json'])
            if not provenance.get('verification',{}).get('passed'):
                raise HTTPException(422,'Independent verification must pass before approval')
        conn.execute('UPDATE blueprint_question_snapshots SET academic_status=?,transcription_status=? WHERE id=?',(data.academic_status,data.transcription_status,qid))
        audit(conn,user,pid,'INVENTORY_REVIEWED',qid,data.model_dump())
        conn.commit()
        return {'id':qid,'academic_status':data.academic_status}


class RunInput(Contract):
    blueprint_version_id: int = Field(gt=0)
    seed: int = Field(default=1,ge=0,le=2147483647)
    sample_preview: bool = False


def feasibility_data(conn,pid,data):
    generator=dependency(conn,pid,data.blueprint_version_id,'EXAM_GENERATOR',not data.sample_preview)
    pattern=dependency(conn,pid,generator['payload']['pattern_version_id'],'EXAM_PATTERN',not data.sample_preview)
    validate_dependencies(conn,pid,'EXAM_GENERATOR',generator['payload'],not data.sample_preview)
    slots=compile_slots(pattern['payload'],generator['payload'])
    pool=inventory_rows(conn,pid)
    try:
        result=select(slots,[] if generator['payload']['mode']=='GENERATE_ONLY' else pool,pattern['payload']['variant'],generator['payload']['exposure_limit'],data.seed)
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc
    profiles={}
    for slot in slots:
        vid=slot['question_blueprint_version_id']
        if str(vid) in profiles: continue
        chain=[]
        while vid:
            item=dependency(conn,pid,vid,'QUESTION_GENERATOR');chain.append(item);vid=item['payload'].get('parent_version_id')
        profiles[str(slot['question_blueprint_version_id'])]={'versions':chain,'effective':effective_profiles([v['payload'] for v in reversed(chain)])}
    curriculum_id=pattern['payload'].get('curriculum_version_id')
    curriculum=None
    if curriculum_id:
        curriculum={'version':dict(conn.execute('SELECT * FROM curriculum_versions WHERE id=?',(curriculum_id,)).fetchone()),'nodes':[dict(r) for r in conn.execute('SELECT * FROM curriculum_nodes WHERE version_id=? ORDER BY id',(curriculum_id,)).fetchall()]}
    history_id=generator['payload'].get('historical_profile_id')
    history=unpack(conn.execute('SELECT * FROM historical_profiles WHERE id=?',(history_id,)).fetchone()) if history_id else None
    sources=[unpack(conn.execute('SELECT * FROM blueprint_sources WHERE id=?',(sid,)).fetchone()) for sid in pattern['payload'].get('official_source_ids',[])+pattern['payload'].get('historical_source_ids',[])]
    result.update(curriculum=curriculum,historical_profile=history,evidence_sources=sources)
    return {**result,'generator':generator,'pattern':pattern,'question_blueprints':profiles,'sample_preview':data.sample_preview,'slots':slots}


@router.post('/{pid}/paper-feasibility')
def feasibility(pid: int,data: RunInput,request: Request):
    require_admin(_auth(request,True))
    with closing(db()) as conn:
        program_row(conn,pid)
        return feasibility_data(conn,pid,data)


@router.post('/{pid}/paper-runs',status_code=201)
def create_paper_run(pid: int,data: RunInput,request: Request):
    user=require_admin(_auth(request,True))
    with closing(db()) as conn:
        program_row(conn,pid,True)
        payload=feasibility_data(conn,pid,data)
        cur=conn.execute('INSERT INTO paper_generation_runs(program_id,blueprint_version_id,payload_json,payload_hash,created_by,created_at) VALUES(?,?,?,?,?,?)',
            (pid,data.blueprint_version_id,canonical(payload),content_hash(payload),user['id'],time.time()))
        audit(conn,user,pid,'PAPER_RUN_CREATED',cur.lastrowid,{'hash':content_hash(payload),'feasible':payload['feasible']})
        conn.commit()
        return {'id':cur.lastrowid,'status':'DRAFT','payload':payload}


@router.get('/{pid}/paper-runs')
def paper_runs(pid: int,request: Request):
    require_admin(_auth(request))
    with closing(db()) as conn:
        program_row(conn,pid)
        return [unpack(r) for r in conn.execute('SELECT * FROM paper_generation_runs WHERE program_id=? ORDER BY id DESC',(pid,)).fetchall()]


@router.post('/{pid}/paper-runs/{rid}/approve')
def approve_paper(pid: int,rid: int,data: ClassificationReview,request: Request):
    user=require_admin(_auth(request,True))
    with closing(db()) as conn:
        program_row(conn,pid,True)
        # Serialize approvals and exposure checks across runs in this program.
        conn.execute('UPDATE programs SET revision=revision WHERE id=?',(pid,))
        row=conn.execute('SELECT * FROM paper_generation_runs WHERE id=? AND program_id=?',(rid,pid)).fetchone()
        if not row: raise HTTPException(404,'Paper run not found')
        payload=json.loads(row['payload_json'])
        if data.status=='APPROVED':
            if payload['sample_preview'] or not payload['feasible']:
                raise HTTPException(422,'Sample previews or runs with gaps cannot be approved')
            if content_hash(payload)!=row['payload_hash']: raise HTTPException(409,'Snapshot integrity check failed')
            current={r['id']:r for r in inventory_rows(conn,pid)}
            for selected in payload['selected']:
                q=current.get(selected['question']['id'])
                if not q or q['academic_status']!='APPROVED' or q['transcription_status']!='APPROVED' or q['payload_hash']!=selected['question']['payload_hash'] or q['exposure']>=payload['generator']['payload']['exposure_limit']:
                    raise HTTPException(409,'A selected question changed approval or exceeded exposure; create a new run')
        cur=conn.execute("UPDATE paper_generation_runs SET status=? WHERE id=? AND status='DRAFT'",(data.status,rid))
        if not cur.rowcount: raise HTTPException(409,'Paper already reviewed')
        if data.status=='APPROVED':
            for selected in payload['selected']:
                conn.execute('INSERT INTO paper_question_exposure(run_id,snapshot_id) VALUES(?,?) RETURNING snapshot_id',(rid,selected['question']['id']))
        audit(conn,user,pid,'PAPER_RUN_'+data.status,rid,{'reason':data.reason})
        conn.commit()
        return {'id':rid,'status':data.status}


class GenerateGapInput(Contract):
    slot_position: int = Field(gt=0)
    author_prompt_id: int = Field(gt=0)
    verifier_prompt_id: int = Field(gt=0)


@router.post('/{pid}/paper-runs/{rid}/generate-missing',status_code=202)
def generate_gap(pid: int,rid: int,data: GenerateGapInput,request: Request,tasks: BackgroundTasks):
    user=require_admin(_auth(request,True))
    with closing(db()) as conn:
        program_row(conn,pid,True)
        row=conn.execute("SELECT * FROM paper_generation_runs WHERE id=? AND program_id=? AND status='DRAFT'",(rid,pid)).fetchone()
        if not row: raise HTTPException(404,'Draft paper run not found')
        run=json.loads(row['payload_json'])
        if run['generator']['payload']['mode']=='RETRIEVAL_ONLY': raise HTTPException(422,'This blueprint allows retrieval only')
        gap=next((g for g in run['gaps'] if g['position']==data.slot_position),None)
        if not gap: raise HTTPException(422,'Only missing slots can generate drafts')
        if gap['slot']['stimulus_size']>1 or gap['slot']['visual_required']:
            raise HTTPException(422,'Grouped passages and exact visual questions require a reviewed manual/imported group; automated authoring is not enabled for these slots')
        for prompt_id,purpose in [(data.author_prompt_id,'QUESTION_AUTHORING'),(data.verifier_prompt_id,'INDEPENDENT_SOLVING')]:
            if not conn.execute('SELECT id FROM blueprint_prompts WHERE id=? AND program_id=? AND purpose=?',(prompt_id,pid,purpose)).fetchone(): raise HTTPException(422,'Choose the correct program prompt versions')
        cur=conn.execute('INSERT INTO blueprint_generation_jobs(program_id,run_id,slot_position,author_prompt_id,verifier_prompt_id,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(run_id,slot_position) DO NOTHING',
            (pid,rid,data.slot_position,data.author_prompt_id,data.verifier_prompt_id,user['id'],time.time(),time.time()))
        if not cur.rowcount: raise HTTPException(409,'A generation job already exists for this run slot')
        audit(conn,user,pid,'GAP_GENERATION_REQUESTED',cur.lastrowid)
        conn.commit();tasks.add_task(run_gap_generation,cur.lastrowid)
        return {'id':cur.lastrowid,'status':'QUEUED'}


def run_gap_generation(jid):
    from blueprint_gemini import IndependentSolution
    from blueprint_papers import normalized_stem, compatible
    with closing(db()) as conn:
        cur=conn.execute("UPDATE blueprint_generation_jobs SET status='RUNNING',updated_at=? WHERE id=? AND status='QUEUED'",(time.time(),jid))
        if not cur.rowcount:return
        job=dict(conn.execute('SELECT * FROM blueprint_generation_jobs WHERE id=?',(jid,)).fetchone())
        run=json.loads(conn.execute('SELECT payload_json FROM paper_generation_runs WHERE id=?',(job['run_id'],)).fetchone()['payload_json'])
        slot=next(g['slot'] for g in run['gaps'] if g['position']==job['slot_position'])
        prompts=[dict(conn.execute('SELECT * FROM blueprint_prompts WHERE id=?',(job[k],)).fetchone()) for k in ('author_prompt_id','verifier_prompt_id')]
        chain=[];vid=slot['question_blueprint_version_id']
        while vid:
            version=dependency(conn,job['program_id'],vid,'QUESTION_GENERATOR');chain.append(version['payload']);vid=version['payload'].get('parent_version_id')
        effective=effective_profiles(reversed(chain))[slot['difficulty']]
        conn.commit()
    try:
        context={'slot':slot,'profile':effective,'variant':run['pattern']['payload']['variant'],'level':run['pattern']['payload']['level']}
        authored,author_telemetry=structured_call('QUESTION_AUTHORING',prompts[0]['template'],context,Candidate)
        candidate=authored.model_dump(mode='json')
        probe={'payload':candidate,'academic_status':'APPROVED','transcription_status':'APPROVED'}
        if not compatible(slot,probe,context['variant'],1):raise ValueError('Generated question violates slot requirements')
        # Independent call excludes both author answer AND author solution.
        blind={k:v for k,v in candidate.items() if k not in ('answers','solution','semantic_cluster')}
        verified,verifier_telemetry=structured_call('INDEPENDENT_SOLVING',prompts[1]['template'],{'question':blind,'scope':context},IndependentSolution)
        gates=['curriculum_match','age_appropriate','plausible_distractors','unambiguous','units_valid','difficulty_supported','language_valid']
        passed=set(verified.answers)==set(authored.answers) and all(getattr(verified,k) for k in gates) and not verified.issues and verified.estimated_seconds<=slot['seconds']
        provenance={'run_id':job['run_id'],'slot':slot,'effective_profile':effective,'author_prompt_id':prompts[0]['id'],'verifier_prompt_id':prompts[1]['id'],
            'author':author_telemetry,'verifier':verifier_telemetry,'verification':{'passed':passed,**verified.model_dump(mode='json')}}
        with closing(db()) as conn:
            lease=conn.execute("UPDATE blueprint_generation_jobs SET status=status WHERE id=? AND status='RUNNING' AND updated_at=?",(jid,job['updated_at']))
            if not lease.rowcount:return
            pool=inventory_rows(conn,job['program_id'])
            if any(normalized_stem(r['payload']['statement'])==normalized_stem(authored.statement) for r in pool):
                passed=False;provenance['verification']['passed']=False;provenance['verification']['issues'].append('Duplicate statement in program inventory')
            qid=conn.execute('INSERT INTO blueprint_question_snapshots(program_id,payload_json,payload_hash,provenance_json,origin,transcription_status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)',
                (job['program_id'],canonical(candidate),content_hash(candidate),canonical(provenance),'GEMINI_GENERATED','IN_REVIEW',job['created_by'],time.time())).lastrowid
            conn.execute("UPDATE blueprint_generation_jobs SET status='DRAFT_READY',result_json=?,updated_at=? WHERE id=?",(canonical({'snapshot_id':qid,'verification_passed':passed,'telemetry':provenance}),time.time(),jid))
            audit(conn,{'id':job['created_by']},job['program_id'],'GEMINI_QUESTION_DRAFT_CREATED',qid,{'job_id':jid,'verification_passed':passed})
            conn.commit()
    except Exception as exc:
        with closing(db()) as conn:
            conn.execute("UPDATE blueprint_generation_jobs SET status='FAILED',error=?,updated_at=? WHERE id=? AND status='RUNNING' AND updated_at=?",(type(exc).__name__+': Draft generation failed. Check configuration and slot requirements.',time.time(),jid,job['updated_at']))
            audit(conn,{'id':job['created_by']},job['program_id'],'GAP_GENERATION_FAILED',jid,{'error_type':type(exc).__name__})
            conn.commit()


@router.get('/{pid}/generation-jobs')
def generation_jobs(pid: int,request: Request):
    require_admin(_auth(request))
    with closing(db()) as conn:
        program_row(conn,pid)
        return [unpack(r) for r in conn.execute('SELECT * FROM blueprint_generation_jobs WHERE program_id=? ORDER BY id DESC',(pid,)).fetchall()]


@router.post('/{pid}/jobs/{kind}/{jid}/retry',status_code=202)
def retry_job(pid: int,kind: Literal['refinement','generation'],jid: int,request: Request,tasks: BackgroundTasks):
    user=require_admin(_auth(request,True))
    table='blueprint_refinements' if kind=='refinement' else 'blueprint_generation_jobs'
    with closing(db()) as conn:
        program_row(conn,pid,True)
        cur=conn.execute(f"UPDATE {table} SET status='QUEUED',error='',updated_at=? WHERE id=? AND program_id=? AND (status='FAILED' OR (status IN ('QUEUED','RUNNING') AND updated_at<?))",(time.time(),jid,pid,time.time()-600))
        if not cur.rowcount:raise HTTPException(409,'Only failed jobs or jobs stalled for over ten minutes can be retried')
        audit(conn,user,pid,'JOB_RETRY_REQUESTED',jid,{'kind':kind})
        conn.commit();tasks.add_task(run_refinement if kind=='refinement' else run_gap_generation,jid)
        return {'id':jid,'status':'QUEUED'}


@router.get('/{pid}/training-export')
def training_export(pid: int,request: Request):
    """Explicitly opted-in, accepted soft-configuration pairs; no users or source text."""
    from fastapi.responses import Response
    import re
    require_admin(_auth(request))
    with closing(db()) as conn:
        program_row(conn,pid)
        lines=[]
        for row in conn.execute("SELECT * FROM blueprint_refinements WHERE program_id=? AND status='ACCEPTED' ORDER BY id",(pid,)).fetchall():
            item=unpack(row)
            if not item['decisions'].get('training_eligible'):continue
            version=dependency(conn,pid,item['blueprint_version_id'])
            proposal=Proposal.model_validate(item['proposal'])
            after=apply_proposal(version['kind'],version['payload'],proposal,item['decisions']['accepted_indices'])
            # Restrict records to configuration, never evidence, identities or review prose.
            record={'kind':version['kind'],'input':version['payload'].get('overrides',version['payload'].get('rules',[])),
                    'approved_result':after.get('overrides',after.get('rules',[])),
                    'accepted_indices':item['decisions']['accepted_indices'],'prompt_version_id':item['prompt_id'],'model':item['telemetry'].get('model')}
            encoded=canonical(record)
            encoded=re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}','[REDACTED_EMAIL]',encoded)
            encoded=re.sub(r'(?<!\w)\+?\d[\d ()-]{8,}\d(?!\w)','[REDACTED_NUMBER]',encoded)
            lines.append(encoded)
        return Response('\n'.join(lines)+ ('\n' if lines else ''),media_type='application/x-ndjson',headers={'Content-Disposition':'attachment; filename="approved-blueprint-evaluation.jsonl"'})
