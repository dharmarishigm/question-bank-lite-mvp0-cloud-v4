from decimal import Decimal

import pytest

from blueprint_domain import Difficulty, ExamPattern, allocate, content_hash, effective_profiles, compile_slots


def pattern():
    """Small non-production Navodaya-like fixture, not an official pattern."""
    return dict(variant='JNVST_CLASS_6', edition='SAMPLE', authority='Fixture', level='VI',
                languages=['English'], delivery='OMR', presented=4, attempted=4, marks='5', seconds=240,
                sample_only=True, sections=[dict(code='MAT', name='Mental ability', presented=4, attempted=4, marks='5',
                blocks=[dict(code='A', subject='Mental Ability', presented=4, attempted=4, qtype='SINGLE_CORRECT',
                             scoring={'positive': '1.25'})])])


def test_decimal_marks_and_totals():
    assert ExamPattern.model_validate(pattern()).marks == Decimal('5')
    invalid = pattern()
    invalid['marks'] = '5.0001'
    with pytest.raises(ValueError, match='Section marks'):
        ExamPattern.model_validate(invalid)


def test_optional_numerical_negative_marks_and_timer():
    data = pattern()
    data.update(presented=6, attempted=4, seconds=240)
    section = data['sections'][0]
    section.update(presented=6, seconds=240)
    section['blocks'][0].update(presented=6, attempted=4, choice_group='choose-four', qtype='NUMERICAL', options=0,
                                scoring={'positive': '1.25', 'negative': '0.25'})
    assert ExamPattern.model_validate(data).presented == 6
    section['blocks'][0]['choice_group'] = ''
    with pytest.raises(ValueError, match='choice group'):
        ExamPattern.model_validate(data)


@pytest.mark.parametrize('count', [0, 1, 4, 17, 80, 101])
def test_exact_difficulty_allocation(count):
    weights = dict(zip(Difficulty, [10, 25, 40, 20, 5]))
    assert sum(allocate(count, weights).values()) == count
    assert allocate(count, weights) == allocate(count, weights)
    with pytest.raises(ValueError):
        allocate(count, {'MEDIUM': 100})


def test_inheritance_and_typed_override():
    chain = [{'scope': 'PROGRAM', 'overrides': {'EASY': {'seconds': 30}}},
             {'scope': 'TOPIC', 'overrides': {'EASY': {'reasoning_steps': 3}}}]
    result = effective_profiles(chain)
    assert result['EASY']['seconds'] == 30
    assert result['EASY']['reasoning_steps'] == 3
    assert result['HARD']['seconds'] == 60
    with pytest.raises(ValueError):
        effective_profiles([{'scope': 'PROGRAM', 'overrides': {'EASY': {'human_review_required': False}}}])


def test_slot_compilation_and_hash():
    generator = {'pattern_version_id': 1, 'rules': [{'section': 'MAT', 'block': 'A', 'language': 'English',
                  'seconds': 60, 'question_blueprint_version_id': 2, 'difficulty': dict(zip(Difficulty, [10, 25, 40, 20, 5]))}]}
    slots = compile_slots(pattern(), generator)
    assert len(slots) == 4
    assert slots[0]['scoring']['positive'] == '1.25'
    assert content_hash({'a': 1, 'b': 2}) == content_hash({'b': 2, 'a': 1})
    generator['rules'][0]['language'] = 'French'
    with pytest.raises(ValueError, match='language'):
        compile_slots(pattern(), generator)
