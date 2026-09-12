"""Cache, question revision, and released-result boundaries for AI explanations."""
from unittest.mock import patch
import time

import pytest

import app
from tests.test_programs import clients


def completed_attempt(admin, student, release='IMMEDIATE'):
    question = admin.post('/api/questions', json={
        'statement': 'What is two plus two?', 'options': ['3', '4'], 'answer': 'B',
        'solution': 'Two plus two is four.',
    }).json()
    response = admin.post('/api/admin/exams', json={
        'name': 'Explanation review', 'status': 'OPEN', 'question_ids': [question['id']],
        'result_release_mode': release, 'exam_start_at': time.time() - 60,
    })
    assert response.status_code == 200, response.text
    exam = response.json()
    enrolled = student.post(f'/api/exams/{exam["id"]}/enroll')
    assert enrolled.status_code == 200, enrolled.text
    started = student.post(f'/api/exams/{exam["id"]}/sessions', json={'consent': True})
    assert started.status_code == 200, started.text
    sid = started.json()['session_id']
    assert student.post(f'/api/sessions/{sid}/submit').status_code == 200
    return question, exam, sid


def lesson(language='en'):
    return app.StructuredExplanation(
        title='Addition' if language == 'en' else 'కూడిక', summary='Combine equal groups.',
        concept='Addition counts the total.', steps=['Count two.', 'Add two more.'],
        correct_answer='B is four.', distractors=[{'option': 'A', 'reason': 'Three is too small.'}],
        background='Counting is the prerequisite.', memory_tip='Count each item once.', references=[],
    )


def paths(question, sid):
    return [f'/api/student/results/{sid}/questions/{question["id"]}/explain',
            f'/api/student/questions/{question["id"]}/explain']


def test_cache_miss_is_saved_once_per_language_and_reused_by_all_learners(clients):
    admin, student, other = clients
    question, exam, sid = completed_attempt(admin, student)
    with patch('app.llm_status', return_value={'available': True}), \
         patch('blueprint_gemini.structured_call', return_value=(lesson(), {})) as model:
        first = student.get(paths(question, sid)[0])
        assert first.status_code == 200, first.text
        assert first.json()['cached'] is False
        assert student.get(paths(question, sid)[1]).json()['cached'] is True
        assert model.call_count == 1
        assert app.get_cached_question_explanation(question['id'], 'en')['liked'] is True
        model.return_value = lesson('te'), {}
        assert student.get(paths(question, sid)[1] + '?language=te').json()['cached'] is False
        assert student.get(paths(question, sid)[0] + '?language=te').json()['cached'] is True
        assert model.call_count == 2
    other.post('/api/auth/mock', json={'email': 'other-explanation@example.test'})
    other.headers['X-CSRF-Token'] = other.cookies['qb_csrf']
    other.post(f'/api/exams/{exam["id"]}/enroll')
    other_sid = other.post(f'/api/exams/{exam["id"]}/sessions', json={'consent': True}).json()['session_id']
    other.post(f'/api/sessions/{other_sid}/submit')
    with patch('blueprint_gemini.structured_call') as model, patch('explanation_quota.reserve_explanation_call') as quota:
        response = other.get(paths(question, other_sid)[0])
        assert response.json()['cached'] is True
        model.assert_not_called()
        quota.assert_not_called()


def test_unreleased_explanations_are_blocked_even_when_cached(clients):
    admin, student, _ = clients
    question, exam, sid = completed_attempt(admin, student, 'AFTER_EXAM_CLOSE')
    app.save_question_explanation(question['id'], 'Stored answer B.')
    with patch('app._generate_question_explanation') as generate:
        for path in paths(question, sid):
            assert student.get(path).status_code == 404
        generate.assert_not_called()
    with app.connect() as conn:
        conn.execute("UPDATE exams SET status='CLOSED' WHERE id=?", (exam['id'],))
        conn.commit()
    for path in paths(question, sid):
        assert student.get(path).json()['cached'] is True


@pytest.mark.parametrize('route_index', [0, 1])
def test_new_active_exam_blocks_explanation_response_after_provider_call(clients, route_index):
    admin, student, _ = clients
    question, _, sid = completed_attempt(admin, student)

    def start_assessment(*args, **kwargs):
        with app.connect() as conn:
            conn.execute("UPDATE exam_sessions SET status='IN_PROGRESS' WHERE id=?", (sid,))
            conn.commit()
        return {'explanation': 'Do not release this answer.'}

    with patch('app._generate_question_explanation', side_effect=start_assessment):
        response = student.get(paths(question, sid)[route_index])
    assert response.status_code == 409
    assert 'Do not release' not in response.text


def test_edit_during_generation_cannot_resurrect_previous_explanation(clients):
    admin, student, _ = clients
    question, _, sid = completed_attempt(admin, student)

    def changed(*args, **kwargs):
        with app.connect() as conn:
            conn.execute("UPDATE questions SET statement='A different question' WHERE id=?", (question['id'],))
            conn.commit()
        return lesson(), {}

    with patch('app.llm_status', return_value={'available': True}), patch('blueprint_gemini.structured_call', side_effect=changed):
        response = student.get(paths(question, sid)[0])
    assert response.status_code == 409
    assert app.get_cached_question_explanation(question['id']) is None


def test_failed_explanation_does_not_cache_or_expose_provider_details(clients):
    admin, student, _ = clients
    question, _, sid = completed_attempt(admin, student)
    with patch('app.llm_status', return_value={'available': True}), \
         patch('blueprint_gemini.structured_call', side_effect=ValueError('private-provider-secret')):
        response = student.get(paths(question, sid)[0])
    assert response.status_code == 502
    assert 'Support reference' in response.text
    assert 'private-provider-secret' not in response.text
    assert app.get_cached_question_explanation(question['id']) is None
