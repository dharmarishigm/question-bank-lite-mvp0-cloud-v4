"""Deterministic, evidence-only historical statistics."""
from collections import Counter
from decimal import Decimal
from typing import Literal
from pydantic import Field
from blueprint_domain import Contract, Difficulty, content_hash


class HistoricalObservation(Contract):
    source_id: int = Field(gt=0)
    source_question_ref: str = Field(min_length=1, max_length=200)
    year: int = Field(ge=1900, le=2200)
    subject: str = Field(min_length=1, max_length=200)
    topic: str = Field(min_length=1, max_length=200)
    difficulty: Difficulty
    qtype: Literal['SINGLE_CORRECT', 'MULTIPLE_CORRECT', 'NUMERICAL']
    cognitive_skill: str = Field(default='', max_length=200)
    language: str = Field(min_length=1, max_length=100)
    estimated_seconds: int = Field(gt=0, le=86400)
    origin: Literal['IMPORTED'] = 'IMPORTED'
    confidence: Decimal = Field(ge=0, le=1)
    classification_reason: str = Field(min_length=1, max_length=2000)


def aggregate(observations, reference_year, half_life=5):
    """Input must already be scoped to reviewed, included historical evidence."""
    if half_life <= 0:
        raise ValueError('Half life must be positive')
    counts = {key: Counter() for key in ('subject', 'topic', 'difficulty', 'qtype', 'language', 'cognitive_skill')}
    weighted = {key: Counter() for key in counts}
    seen = set()
    for row in observations:
        item = HistoricalObservation.model_validate(row)
        identity = (item.source_id, item.source_question_ref)
        if identity in seen:
            raise ValueError('Duplicate historical question reference')
        if item.year > reference_year:
            raise ValueError('Reference year precedes an observation')
        seen.add(identity)
        weight = 2 ** (-(reference_year-item.year)/half_life)
        for key in counts:
            value = str(getattr(item, key).value if isinstance(getattr(item, key), Difficulty) else getattr(item, key))
            counts[key][value] += 1
            weighted[key][value] += weight
    total = len(observations)
    warnings = []
    if total < 30:
        warnings.append('Low sample size: fewer than 30 reviewed questions; do not infer official rules.')
    if len({r['source_id'] for r in observations}) < 3:
        warnings.append('Limited source diversity: fewer than three historical papers.')
    return {'sample_size': total, 'counts': counts, 'recency_weighted_counts': weighted,
            'reference_year': reference_year, 'half_life_years': half_life,
            'confidence': 'LOW' if warnings else 'MODERATE', 'warnings': warnings,
            'evidence_hash': content_hash(observations), 'algorithm': 'reviewed-history-v1'}
