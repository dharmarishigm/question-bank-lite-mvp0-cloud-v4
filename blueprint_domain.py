"""Versioned contracts for the additive Programs workspace.

These contracts do not alter the legacy exam generator or its scoring model.
Authoritative marks use Decimal; persisted JSON uses decimal strings.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Difficulty(str, Enum):
    VERY_EASY = 'VERY_EASY'
    EASY = 'EASY'
    MEDIUM = 'MEDIUM'
    HARD = 'HARD'
    VERY_HARD = 'VERY_HARD'


DEFAULT_DISTRIBUTIONS = dict(zip(Difficulty, (
    (50, 30, 15, 5, 0), (25, 45, 20, 10, 0), (10, 25, 40, 20, 5),
    (5, 10, 25, 40, 20), (0, 5, 15, 30, 50),
)))


def canonical(value):
    if isinstance(value, BaseModel):
        value = value.model_dump(mode='json')
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def content_hash(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def allocate(total: int, weights: dict[str, Decimal]) -> dict[str, int]:
    """Largest remainder, with canonical difficulty order as the tie breaker."""
    if total < 0 or set(weights) != set(Difficulty):
        raise ValueError('Specify all five difficulty levels and a nonnegative count')
    values = [Decimal(str(weights[d])) for d in Difficulty]
    if any(not x.is_finite() or x < 0 for x in values) or sum(values) != 100:
        raise ValueError('Difficulty percentages must be nonnegative and total 100')
    exact = [total * x / 100 for x in values]
    counts = [int(x) for x in exact]
    for i in sorted(range(5), key=lambda i: (-(exact[i] - counts[i]), i))[:total - sum(counts)]:
        counts[i] += 1
    return dict(zip(Difficulty, counts))


class ProgramInput(Contract):
    code: str = Field(pattern=r'^[A-Z][A-Z0-9_]{1,63}$')
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=4000)
    authority: str = Field(default='', max_length=200)
    region: str = Field(default='', max_length=200)
    category: str = Field(default='', max_length=100)
    levels: list[str] = Field(default_factory=list, max_length=100)
    languages: list[str] = Field(default_factory=list, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=100)
    status: Literal['ACTIVE', 'INACTIVE'] = 'ACTIVE'


class Scoring(Contract):
    positive: Decimal = Field(gt=0, max_digits=10, decimal_places=4)
    negative: Decimal = Field(default=Decimal(0), ge=0, max_digits=10, decimal_places=4)
    partial: Decimal = Field(default=Decimal(0), ge=0, max_digits=10, decimal_places=4)
    unattempted: Decimal = Field(default=Decimal(0), max_digits=10, decimal_places=4)

    @model_validator(mode='after')
    def compatible(self):
        if self.partial > self.positive or self.unattempted != 0:
            raise ValueError('Partial credit cannot exceed full credit; unattempted marks must be zero')
        return self


class Block(Contract):
    code: str = Field(min_length=1, max_length=100)
    subject: str = Field(min_length=1, max_length=200)
    presented: int = Field(ge=1, le=1000)
    attempted: int = Field(ge=1, le=1000)
    qtype: Literal['SINGLE_CORRECT', 'MULTIPLE_CORRECT', 'NUMERICAL']
    options: int = Field(default=4, ge=0, le=12)
    scoring: Scoring
    stimulus_size: int = Field(default=1, ge=1, le=100)
    choice_group: str = ''

    @model_validator(mode='after')
    def valid(self):
        if self.attempted > self.presented:
            raise ValueError('Attempt count exceeds presented count')
        if self.attempted < self.presented and not self.choice_group:
            raise ValueError('Optional blocks require an explicit choice group')
        if self.presented % self.stimulus_size:
            raise ValueError('Presented count must contain complete stimulus groups')
        if (self.qtype == 'NUMERICAL' and self.options != 0) or (self.qtype != 'NUMERICAL' and self.options < 2):
            raise ValueError('Option count is incompatible with question type')
        if self.qtype != 'MULTIPLE_CORRECT' and self.scoring.partial:
            raise ValueError('Partial marks require multiple-correct questions')
        return self


class Section(Contract):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    presented: int = Field(ge=1)
    attempted: int = Field(ge=1)
    marks: Decimal = Field(gt=0, max_digits=12, decimal_places=4)
    seconds: int | None = Field(default=None, gt=0)
    blocks: list[Block] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def totals(self):
        if len({b.code for b in self.blocks}) != len(self.blocks):
            raise ValueError('Block codes must be unique within a section')
        if sum(b.presented for b in self.blocks) != self.presented or sum(b.attempted for b in self.blocks) != self.attempted:
            raise ValueError('Block counts must equal section totals')
        if sum(b.attempted * b.scoring.positive for b in self.blocks) != self.marks:
            raise ValueError('Block marks must equal section marks')
        return self


class ExamPattern(Contract):
    schema_version: Literal[1] = 1
    variant: str = Field(min_length=1, max_length=100)
    edition: str = Field(min_length=1, max_length=100)
    effective_from: str = Field(default='', pattern=r'^(|\d{4}-\d{2}-\d{2})$')
    effective_to: str = Field(default='', pattern=r'^(|\d{4}-\d{2}-\d{2})$')
    authority: str = Field(min_length=1, max_length=200)
    level: str = Field(min_length=1, max_length=100)
    languages: list[str] = Field(min_length=1, max_length=30)
    delivery: Literal['OMR', 'PBT', 'CBT', 'HYBRID']
    presented: int = Field(ge=1, le=1000)
    attempted: int = Field(ge=1, le=1000)
    marks: Decimal = Field(gt=0, max_digits=12, decimal_places=4)
    seconds: int = Field(gt=0, le=86400)
    curriculum_version_id: int | None = Field(default=None, gt=0)
    official_source_ids: list[int] = Field(default_factory=list, max_length=100)
    historical_source_ids: list[int] = Field(default_factory=list, max_length=100)
    sample_only: bool = False
    sections: list[Section] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def totals(self):
        from datetime import date
        dates = [date.fromisoformat(d) for d in (self.effective_from, self.effective_to) if d]
        if len(dates) == 2 and dates[1] < dates[0]:
            raise ValueError('Effective end must not precede effective start')
        if len({s.code for s in self.sections}) != len(self.sections):
            raise ValueError('Section codes must be unique')
        if sum(s.presented for s in self.sections) != self.presented or sum(s.attempted for s in self.sections) != self.attempted:
            raise ValueError('Section counts must equal paper totals')
        if sum(s.marks for s in self.sections) != self.marks:
            raise ValueError('Section marks must equal paper marks')
        timers = [s.seconds for s in self.sections if s.seconds is not None]
        if timers and (len(timers) != len(self.sections) or sum(timers) != self.seconds):
            raise ValueError('Section timers must all be supplied and sum to duration')
        return self


class SlotRule(Contract):
    section: str
    block: str
    curriculum_node_id: int | None = Field(default=None, gt=0)
    topic: str = ''
    language: str = Field(min_length=1)
    cognitive_skill: str = ''
    visual_required: bool = False
    seconds: int = Field(gt=0)
    question_blueprint_version_id: int = Field(gt=0)
    difficulty: dict[Difficulty, Decimal]

    @field_validator('difficulty')
    @classmethod
    def distribution(cls, value):
        allocate(100, value)
        return value


class ExamGenerator(Contract):
    schema_version: Literal[1] = 1
    pattern_version_id: int = Field(gt=0)
    historical_profile_id: int | None = Field(default=None, gt=0)
    mode: Literal['RETRIEVAL_ONLY', 'RETRIEVAL_THEN_GENERATE_GAPS', 'GENERATE_ONLY'] = 'RETRIEVAL_THEN_GENERATE_GAPS'
    exposure_limit: int = Field(default=10, ge=1)
    rules: list[SlotRule] = Field(min_length=1, max_length=100)


class QuestionProfile(Contract):
    qtype: Literal['SINGLE_CORRECT', 'MULTIPLE_CORRECT', 'NUMERICAL'] = 'SINGLE_CORRECT'
    options: int = Field(default=4, ge=0, le=12)
    seconds: int = Field(default=60, gt=0)
    reasoning_steps: int = Field(default=2, ge=1, le=30)
    stem_max_words: int = Field(default=120, ge=1, le=2000)
    distractor_strategy: str = 'Plausible misconceptions; unique and unambiguous options'
    solution_format: str = 'Step-by-step reasoning followed by the answer'
    language: str = 'English'
    prohibited_patterns: list[str] = Field(default_factory=list)
    cognitive_skill: str = ''
    readability_level: str = ''
    numerical_complexity: str = ''
    learning_outcome: str = ''
    answer_format: str = 'Option letters for select questions; a numeric value for numerical questions'
    explanation_depth: str = 'Explain the essential reasoning and likely misconceptions'
    age_class_guidance: str = ''
    formula_unit_constraints: list[str] = Field(default_factory=list, max_length=100)
    chemistry_constraints: list[str] = Field(default_factory=list, max_length=100)
    historical_example_policy: str = 'Use reviewed evidence for style; never copy source questions'
    originality_threshold: Decimal = Field(default=Decimal('0.85'), ge=0, le=1)
    deterministic_validators: list[str] = Field(default_factory=lambda: ['schema', 'options', 'answer_agreement', 'slot_compatibility'])
    human_review_required: Literal[True] = True


class QuestionGenerator(Contract):
    schema_version: Literal[1] = 1
    parent_version_id: int | None = Field(default=None, gt=0)
    scope: Literal['GLOBAL', 'PROGRAM', 'EXAM', 'SUBJECT', 'CHAPTER', 'TOPIC', 'SUBTOPIC']
    subject: str = ''
    chapter: str = ''
    topic: str = ''
    curriculum_node_id: int | None = Field(default=None, gt=0)
    prompt_version_id: int | None = Field(default=None, gt=0)
    overrides: dict[Difficulty, dict] = Field(default_factory=dict)

    @field_validator('overrides')
    @classmethod
    def typed_overrides(cls, value):
        for overrides in value.values():
            # Validate overrides against the complete default profile without storing defaults.
            QuestionProfile.model_validate({**QuestionProfile().model_dump(), **overrides})
        return value


CONTRACTS = {'EXAM_PATTERN': ExamPattern, 'EXAM_GENERATOR': ExamGenerator, 'QUESTION_GENERATOR': QuestionGenerator}


def validate_payload(kind, payload):
    if kind not in CONTRACTS:
        raise ValueError('Unknown blueprint type')
    return CONTRACTS[kind].model_validate(payload).model_dump(mode='json')


def effective_profiles(chain):
    result = {d.value: QuestionProfile().model_dump(mode='json') for d in Difficulty}
    for payload in chain:
        parsed = QuestionGenerator.model_validate(payload)
        for difficulty, overrides in parsed.overrides.items():
            result[difficulty.value].update(overrides)
    return {key: QuestionProfile.model_validate(value).model_dump(mode='json') for key, value in result.items()}


def compile_slots(pattern_payload, generator_payload):
    pattern = ExamPattern.model_validate(pattern_payload)
    generator = ExamGenerator.model_validate(generator_payload)
    blocks = {(s.code, b.code): b for s in pattern.sections for b in s.blocks}
    rules = {(r.section, r.block): r for r in generator.rules}
    if len(rules) != len(generator.rules) or set(rules) != set(blocks):
        raise ValueError('Every pattern block must have exactly one generator rule')
    slots = []
    for key, block in blocks.items():
        rule = rules[key]
        if rule.language not in pattern.languages:
            raise ValueError('Slot language is not in the exam pattern')
        block_position = 0
        for difficulty, count in allocate(block.presented, rule.difficulty).items():
            for _ in range(count):
                position = len(slots) + 1
                block_position += 1
                slots.append({'position': position, 'section': key[0], 'block': key[1],
                              'subject': block.subject, 'qtype': block.qtype, 'options': block.options,
                              'difficulty': difficulty.value, 'scoring': block.scoring.model_dump(mode='json'),
                              'topic': rule.topic, 'language': rule.language, 'seconds': rule.seconds,
                              'visual_required': rule.visual_required, 'curriculum_node_id': rule.curriculum_node_id,
                              'question_blueprint_version_id': rule.question_blueprint_version_id,
                              'cognitive_skill': rule.cognitive_skill,
                              'stimulus_group': f'{key[0]}/{key[1]}/{(block_position-1)//block.stimulus_size}',
                              'stimulus_position': (block_position-1)%block.stimulus_size+1,
                              'stimulus_size': block.stimulus_size, 'choice_group': block.choice_group})
    return slots
