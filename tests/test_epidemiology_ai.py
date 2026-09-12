from unittest.mock import patch

import epidemiology_model
from tests.test_programs import clients


def test_uncited_forecast_suggestion_cannot_claim_reference_alignment(clients):
    admin, student, anonymous = clients
    path = '/api/flag/epidemiology/suggest'
    payload = {'disease': 'Example condition', 'region': 'Example region'}
    assert anonymous.post(path, json=payload).status_code == 401
    assert student.post(path, json=payload).status_code == 403
    assert admin.put('/api/flag/members', json={'email': 'student@example.test'}).status_code == 200
    proposed = epidemiology_model.ForecastSuggestion(**payload,
        evidence_status='REFERENCE_ALIGNED', rationale='Illustrative assumptions to validate locally.')
    with patch('epidemiology_model.structured_call', return_value=(proposed, {'model': 'test-model'})) as call:
        response = student.post(path, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()['evidence_status'] == 'ASSUMPTION_REQUIRED'
    assert call.call_args.args[2] == payload
    assert response.json()['model'] == 'test-model'


def test_invalid_inputs_and_failed_provider_leave_forecast_inputs_unchanged(clients):
    admin, _, _ = clients
    path = '/api/flag/epidemiology/suggest'
    payload = {'disease': 'Example condition', 'region': 'Example region'}
    with patch('epidemiology_model.structured_call') as call:
        assert admin.post(path, json={}).status_code == 422
        call.assert_not_called()
    with patch('epidemiology_model.structured_call', side_effect=TimeoutError('private diagnostic')):
        response = admin.post(path, json=payload)
    assert response.status_code == 502
    assert 'private diagnostic' not in response.text
    assert 'have not been replaced' in response.text
