from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from starlette.requests import Request
from fastapi import HTTPException
import app
from tests.test_programs import clients
from student_content_guard import protect

def request(method='GET',path='/api/my/results'):
 return Request({'type':'http','method':method,'path':path,'headers':[]})

def test_shared_read_quota_is_per_student_atomic_and_excludes_writes(clients):
 admin,student,_=clients;user=student.get('/api/auth/me').json()
 def call(_):
  try:protect(request(),user);return 200
  except HTTPException as e:return e.status_code
 with patch('student_content_guard.MINUTE_LIMIT',4):
  with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(call,range(12)))
  assert results.count(200)==4 and results.count(429)==8
  protect(request('PUT','/api/sessions/1/answers/1'),user)
  protect(request('POST','/api/sessions/1/submit'),user)
  protect(request(),admin.get('/api/auth/me').json())
  r=student.get('/api/my/results');assert r.status_code==429 and int(r.headers['Retry-After'])>0
 with app.connect() as conn:conn.execute('UPDATE student_content_reads SET read_at=read_at-61');conn.commit()
 assert student.get('/api/my/results').status_code==200
 assert student.get('/api/my/results').headers['Cache-Control']=='no-store, private'

def test_preexisting_student_share_no_longer_downloadable(clients):
 import hashlib,time
 from tests.test_result_features import attempt
 admin,student,anon=clients;sid,_,_=attempt(admin,student)
 uid=student.get('/api/auth/me').json()['id'];token='old-student-report-link'
 with app.connect() as conn:
  conn.execute('INSERT INTO result_report_links(session_id,token_hash,created_by,created_at,expires_at) VALUES(?,?,?,?,?)',(sid,hashlib.sha256(token.encode()).hexdigest(),uid,time.time(),time.time()+1000));conn.commit()
 assert anon.get('/reports/shared/'+token+'.pdf').status_code==404
 assert student.get(f'/api/results/{sid}/report.pdf').status_code==403
 assert student.post(f'/api/results/{sid}/share').status_code==403
 assert admin.get(f'/api/results/{sid}/report.pdf').status_code==200
