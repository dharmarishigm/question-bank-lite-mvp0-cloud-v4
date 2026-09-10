"""Exact, bounded paper selection over immutable academically reviewed snapshots."""
from typing import Literal
import hashlib
import unicodedata
from pydantic import Field, model_validator
from blueprint_domain import Contract, Difficulty, Scoring, content_hash


class Candidate(Contract):
    subject: str = Field(min_length=1, max_length=200)
    topic: str = Field(default='', max_length=200)
    curriculum_node_id: int | None = Field(default=None, gt=0)
    variant: str = Field(min_length=1, max_length=100)
    difficulty: Difficulty
    qtype: Literal['SINGLE_CORRECT','MULTIPLE_CORRECT','NUMERICAL']
    language: str = Field(min_length=1, max_length=100)
    scoring: Scoring
    seconds: int = Field(gt=0, le=86400)
    cognitive_skill: str = Field(default='', max_length=200)
    visual_required: bool = False
    semantic_cluster: str = Field(min_length=1, max_length=200)
    stimulus_id: str = Field(default='', max_length=200)
    stimulus_position: int = Field(default=1, ge=1, le=100)
    stimulus_size: int = Field(default=1, ge=1, le=100)
    statement: str = Field(min_length=1, max_length=20000)
    options: list[str] = Field(default_factory=list, max_length=12)
    answers: list[str] = Field(min_length=1, max_length=12)
    solution: str = Field(min_length=1, max_length=20000)

    @model_validator(mode='after')
    def validate_content(self):
        clean = [unicodedata.normalize('NFKC', s).strip().casefold() for s in self.options]
        if any(not s for s in clean) or len(set(clean)) != len(clean):
            raise ValueError('Options must be nonempty and distinct')
        if self.qtype == 'NUMERICAL':
            from decimal import Decimal, InvalidOperation
            try:
                valid = not self.options and len(self.answers) == 1 and Decimal(self.answers[0]).is_finite()
            except InvalidOperation:
                valid = False
            if not valid:
                raise ValueError('Numerical questions need one finite numeric answer and no options')
        else:
            labels = [chr(65+i) for i in range(len(self.options))]
            if len(labels) < 2 or len(set(self.answers)) != len(self.answers) or not set(self.answers) <= set(labels):
                raise ValueError('Answers must identify distinct available option letters')
            if self.qtype == 'SINGLE_CORRECT' and len(self.answers) != 1:
                raise ValueError('Single-select questions require exactly one correct answer')
        if self.stimulus_position > self.stimulus_size or (self.stimulus_size > 1 and not self.stimulus_id):
            raise ValueError('Stimulus questions need a group identity and valid position')
        return self


def normalized_stem(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def compatible(slot, row, variant, exposure_limit):
    q = row['payload']
    return (row['academic_status'] == 'APPROVED' and row['transcription_status'] == 'APPROVED'
        and row.get('exposure', 0) < exposure_limit and q['variant'] == variant
        and all(q[k] == slot[k] for k in ('subject','qtype','difficulty','language','scoring','curriculum_node_id','stimulus_size'))
        and (not slot['topic'] or q['topic'] == slot['topic'])
        and (not slot.get('cognitive_skill') or q['cognitive_skill'] == slot['cognitive_skill'])
        and (not slot['visual_required'] or q['visual_required'])
        and len(q['options']) == slot['options'] and q['seconds'] <= slot['seconds']
        and q['stimulus_position'] == slot.get('stimulus_position', 1))


def select(slots, candidates, variant, exposure_limit, seed, budget=200000):
    pools = {s['position']: [r for r in candidates if compatible(s,r,variant,exposure_limit)] for s in slots}
    for rows in pools.values():
        rows.sort(key=lambda r: hashlib.sha256(f"{seed}:{r['id']}:{r['payload_hash']}".encode()).hexdigest())
    # Tightest-first search with explicit group constraints. Exhaustion is an error,
    # never a claim that inventory is insufficient.
    ordered = sorted(slots, key=lambda s:(len(pools[s['position']]),s['position']))
    assigned, used, clusters, stems, groups = {}, set(), set(), set(), {}
    steps = 0
    best = {}
    def solve(index):
        nonlocal steps, best
        steps += 1
        if steps > budget:
            raise ValueError('Exact selection search limit reached; narrow the candidate pool or blueprint')
        if index == len(ordered):
            complete = dict(assigned)
            for slot in slots:
                if slot['stimulus_size'] > 1:
                    group_slots = [s['position'] for s in slots if s['stimulus_group'] == slot['stimulus_group']]
                    if not all(p in complete for p in group_slots):
                        for p in group_slots: complete.pop(p, None)
            if len(complete) > len(best): best = complete
            return len(best) == len(slots)
        if len(assigned) + len(ordered) - index <= len(best):
            return False
        slot = ordered[index]
        group = slot.get('stimulus_group') if slot['stimulus_size'] > 1 else None
        for row in pools[slot['position']]:
            q = row['payload']; cluster = q['semantic_cluster']; stem = normalized_stem(q['statement'])
            if row['id'] in used or cluster in clusters or stem in stems:
                continue
            if group and ((group in groups and groups[group] != q['stimulus_id']) or any(g != group and v == q['stimulus_id'] for g,v in groups.items())):
                continue
            prior = groups.get(group)
            if group: groups[group] = q['stimulus_id']
            used.add(row['id']); clusters.add(cluster); stems.add(stem); assigned[slot['position']] = row
            if solve(index+1): return True
            used.remove(row['id']); clusters.remove(cluster); stems.remove(stem); assigned.pop(slot['position'])
            if group and prior is None: groups.pop(group)
        return solve(index+1)
    feasible = solve(0)
    assigned = best
    matrix = [{'position':s['position'], 'scope':f"{s['section']}/{s['block']}/{s['difficulty']}",
               'required':1, 'approved_available':len(pools[s['position']]), 'missing':int(s['position'] not in assigned),
               'action':'GENERATE_DRAFT' if s['position'] not in assigned else 'SELECT_REVIEWED'} for s in slots]
    return {'feasible':feasible, 'matrix':matrix, 'selected':[{'slot':s,'question':assigned[s['position']]} for s in slots if s['position'] in assigned],
            'gaps':[{'position':s['position'], 'slot':s, 'reason':'No eligible reviewed question' if not pools[s['position']] else 'No complete assignment satisfying uniqueness and stimulus constraints'} for s in slots if s['position'] not in assigned],
            'candidate_pool_hash':content_hash(candidates), 'algorithm':'exact-backtracking-v1', 'seed':seed}
