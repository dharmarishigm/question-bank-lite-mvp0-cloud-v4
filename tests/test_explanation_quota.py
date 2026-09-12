from concurrent.futures import ThreadPoolExecutor
import time
from unittest.mock import patch
import pytest
from fastapi import HTTPException
import app
from explanation_quota import reserve_explanation_call
from tests.test_programs import clients


def test_rolling_quota_concurrent_and_per_user(clients):
    admin,student,other=clients
    other.post("/api/auth/mock",json={"email":"other-quota@example.test","name":"Other"})
    uid=student.get('/api/auth/me').json()['id'];other_id=other.get('/api/auth/me').json()['id']
    def reserve(_):
        try:reserve_explanation_call(uid);return 200
        except HTTPException as exc:return exc.status_code
    with patch('explanation_quota.time.time',return_value=10000):
        with ThreadPoolExecutor(max_workers=12) as pool:results=list(pool.map(reserve,range(20)))
        assert results.count(200)==10 and results.count(429)==10
        reserve_explanation_call(other_id)
    with patch('explanation_quota.time.time',return_value=13599):
        with pytest.raises(HTTPException) as exc:reserve_explanation_call(uid)
        assert exc.value.headers['Retry-After']=='1'
    with patch('explanation_quota.time.time',return_value=13600):reserve_explanation_call(uid)


def test_student_routes_queue_without_ai_or_quota_and_cache_is_free(clients):
    admin,student,other=clients
    other.post("/api/auth/mock",json={"email":"other-quota@example.test","name":"Other"})
    q=admin.post('/api/questions',json={'statement':'2+2?','options':['3','4'],'answer':'B'}).json()
    exam=admin.post('/api/admin/exams',json={'name':'Quota Exam','status':'OPEN','question_ids':[q['id']],'exam_start_at':time.time()-60}).json()
    student.post(f'/api/exams/{exam["id"]}/enroll')
    sid=student.post(f'/api/exams/{exam["id"]}/sessions',json={'consent':True}).json()['session_id']
    student.post(f'/api/sessions/{sid}/submit')
    paths=[f'/api/student/questions/{q["id"]}/explain',f'/api/student/results/{sid}/questions/{q["id"]}/explain']
    with patch('app.get_cached_question_explanation',return_value=None),patch('app.llm_status',return_value={'available':True}),patch('blueprint_gemini.structured_call',side_effect=RuntimeError('Provider failure')) as model:
        for i in range(12):
            result=student.get(paths[i%2]);assert result.status_code==200 and result.json()['pending']
        assert student.get(paths[1]+'?language=te').json()['pending']
        assert model.call_count==0
        assert student.get(f'/api/questions/{q["id"]}/explain').status_code==403
        assert other.get(paths[0]).status_code==404
    with patch('app.get_cached_question_explanation',return_value={'liked':True,'structured':{'title':'Saved'},'explanation':'Saved explanation'}):
        assert student.get(paths[0]).json()['cached'] is True
