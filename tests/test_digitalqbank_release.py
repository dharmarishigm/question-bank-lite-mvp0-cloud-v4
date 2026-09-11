"""Regression coverage for the document-library and page-status release paths."""
from tests.test_programs import clients, create
from tests.test_grand_tests import pdf


def test_library_availability_and_direct_access(clients):
    admin, operator, student = clients
    pid = create(admin)['id']
    email = operator.get('/api/auth/me').json()['email']
    uid = operator.get('/api/auth/me').json()['id']
    assert admin.post('/api/admin/operator-allowlist', json={'email': email}).status_code == 200
    assert admin.put(f'/api/admin/users/{uid}/role', json={'role': 'OPERATOR'}).status_code == 200
    result = admin.post(f'/api/grand-tests/documents?program_id={pid}&subject=Physics', files={'file': ('paper.pdf', pdf(), 'application/pdf')})
    assert result.status_code == 201, result.text
    doc = result.json()
    assert doc['subject'] == 'Physics'
    assert doc['created_by'] == doc['updated_by']
    assert not doc['available_for_digitisation']
    assert operator.get(f'/api/grand-tests/documents/available?program_id={pid}').json() == []
    body = {'program_id': pid, 'name': 'Operator paper', 'document_id': doc['id']}
    assert operator.post('/api/grand-tests', json=body).status_code == 403
    path = f"/api/grand-tests/admin/documents/{doc['id']}/availability"
    assert operator.put(path, json={'available': True}).status_code == 403
    assert admin.put(path, json={'available': True}).status_code == 200
    assert len(operator.get(f'/api/grand-tests/documents/available?program_id={pid}').json()) == 1
    assert operator.get('/api/grand-tests/documents/available?program_id=99999').json() == []
    work = operator.post('/api/grand-tests', json=body)
    assert work.status_code == 201, work.text
    gid = work.json()['id']
    assert operator.get(f'/api/grand-tests/{gid}/pages/1').status_code == 200
    library = admin.get('/api/grand-tests/admin/document-library').json()
    assert library[0]['pending'] == 2
    assert admin.put(path, json={'available': False}).status_code == 200
    assert operator.get(f'/api/grand-tests/{gid}').status_code == 404
    assert operator.get(f'/api/grand-tests/{gid}/pages/1').status_code == 404
    assert admin.get(f'/api/grand-tests/{gid}/pages/1').status_code == 200


def test_page_status_revision_and_counts(clients):
    admin, _, _ = clients
    assert admin.get('/api/health').json()['status'] == 'ok'
    pid = create(admin)['id']
    work = admin.post('/api/grand-tests', json={'program_id': pid, 'name': 'Status test'}).json()
    path = f"/api/grand-tests/{work['id']}"
    upload = admin.post(path + '/pdf', params={'revision': work['revision']}, files={'file': ('paper.pdf', pdf(), 'application/pdf')})
    work = upload.json()
    body = {'revision': work['revision'], 'page': 1, 'status': 'Not Applicable'}
    result = admin.put(path + '/page-status', json=body)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data['counts']['Not Applicable'] == 1
    assert data['remaining'] == 1
    assert admin.put(path + '/page-status', json=body).status_code == 409
    assert admin.get(path + '/page-status').json()['counts']['Not Applicable'] == 1


def test_save_selected_and_all_without_duplicates(clients):
    from unittest.mock import patch
    from tests.test_grand_tests import build, extracted
    admin, _, student = clients
    first = extracted()['questions'][0]
    second = {**first, 'number': 2, 'statement': 'Find 3 + 3.'}
    with patch('tests.test_grand_tests.extracted', return_value={'questions': [first, second]}):
        path, work = build(admin, create(admin)['id'])
    ids = [q['id'] for q in work['questions']]
    assert len(ids) == 2
    assert admin.post(path+'/save-questions', json={'revision':work['revision'],'question_ids':ids}).status_code == 422
    for q in work['questions']: q['reviewed'] = True
    work = admin.put(path+'/questions', json={'revision':work['revision'],'questions':work['questions']}).json()
    assert student.post(path+'/save-questions', json={'revision':work['revision'],'question_ids':ids}).status_code == 401
    result = admin.post(path+'/save-questions', json={'revision':work['revision'],'question_ids':ids[:1]})
    assert result.status_code == 200, result.text
    work = result.json()
    assert work['questions'][0]['saved_question_id']
    assert not work['questions'][1].get('saved_question_id')
    result = admin.post(path+'/save-questions', json={'revision':work['revision'],'question_ids':ids})
    assert result.status_code == 200, result.text
    work = result.json()
    assert admin.get('/api/questions').json()['total'] == 2
    work = admin.post(path+'/save-questions', json={'revision':work['revision'],'question_ids':ids}).json()
    assert admin.get('/api/questions').json()['total'] == 2
    work = admin.post(path+'/finalize', json={'revision':work['revision']}).json()
    result = admin.post(path+'/generate', json={'revision':work['revision']})
    assert result.status_code == 200, result.text
    assert admin.get('/api/questions').json()['total'] == 2
