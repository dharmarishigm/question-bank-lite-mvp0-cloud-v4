from contextlib import closing
import time
import app
from tests.test_programs import clients


def test_exam_program_context_uses_persisted_link_not_name(clients):
    admin,student,anon=clients
    p=admin.post('/api/programs',json={'code':'JEE_MAIN_BTECH','name':'IIT JEE Main','status':'ACTIVE'}).json()
    q=admin.post('/api/questions',json={'statement':'2+2?','options':['3','4'],'answer':'B'}).json()
    e=admin.post('/api/admin/exams',json={'name':'Unrelated paper title','status':'OPEN','question_ids':[q['id']]}).json()
    other=admin.post('/api/admin/exams',json={'name':'IIT JEE Main but not linked','status':'OPEN','question_ids':[q['id']]}).json()
    uid=admin.get('/api/auth/me').json()['id']
    with closing(app.connect()) as conn:
        conn.execute("INSERT INTO program_exam_jobs(program_id,request_key,input_json,created_by,created_at,updated_at,exam_id) VALUES(?,?,?,?,?,?,?)",(p['id'],'context-test','{}',uid,time.time(),time.time(),e['id']));conn.commit()
    student.post(f'/api/exams/{e["id"]}/enroll')
    for client,path in [(anon,'/api/public/exams'),(student,'/api/exams'),(student,'/api/my/exams')]:
        response=client.get(path);assert response.status_code==200,response.text
        items=response.json();linked=next(r for r in items if r['id']==e['id'])
        assert linked['program_code']=='JEE_MAIN_BTECH' and linked['question_count']==1
        assert all('program_code' not in r for r in items if r['id']==other['id'])
    assert student.get(f'/api/exams/{e["id"]}').json()['program_code']=='JEE_MAIN_BTECH'
