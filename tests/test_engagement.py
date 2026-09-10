import time
from unittest.mock import patch
import pymupdf
import app
from tests.test_programs import clients
from tests.test_flag import private_storage,pdf_bytes,xlsx_bytes

def enquiry(client):
    c=client.get('/api/enquiries/challenge').json()
    words=c['question'].split()
    return {'name':'Interested learner','email':'learner@example.test','message':'Please share subscription details.',
            'interest':'FLAG','consent':True,'challenge_id':c['id'],'answer':str(int(words[2])+int(words[4].rstrip('?')))}

def test_enquiry_verification_permissions_followup(clients):
    admin,student,anon=clients
    data=enquiry(anon)
    assert anon.post('/api/enquiries',json={**data,'answer':'999'}).status_code==422
    r=anon.post('/api/enquiries',json=data);assert r.status_code==201,r.text
    assert anon.post('/api/enquiries',json=data).status_code==422
    assert student.get('/api/admin/enquiries').status_code==403
    assert anon.get('/api/admin/enquiries').status_code==401
    row=admin.get('/api/admin/enquiries').json()['items'][0]
    update={'status':'CONTACTED','admin_notes':'Called learner','updated_at':row['updated_at']}
    assert admin.put(f'/api/admin/enquiries/{row["id"]}',json=update).status_code==200
    assert admin.put(f'/api/admin/enquiries/{row["id"]}',json=update).status_code==409
    assert admin.get('/api/admin/enquiries?status=NEW').json()['total']==0
    assert admin.get('/api/admin/enquiries?status=CONTACTED').json()['total']==1
    assert 'admin@meritiqra.com' in anon.get('/enquiry').text

def test_trials_cannot_unlock_flag(clients):
    admin,student,anon=clients
    assert anon.post('/api/flag/trial').status_code==401
    assert student.get('/api/flag/access').json()['trial_available'] is False
    assert student.post('/api/flag/trial').status_code==403
    assert student.get('/api/flag/materials').status_code==403
    with app.connect() as conn:
        uid=student.get('/api/auth/me').json()['id']
        conn.execute('INSERT INTO flag_trials(user_id,started_at,expires_at) VALUES(?,?,?)',(uid,time.time(),time.time()+86400));conn.commit()
    assert student.get('/api/flag/access').json()['allowed'] is False
    assert admin.put('/api/flag/members',json={'email':'student@example.test'}).status_code==200
    assert student.get('/api/flag/access').json()['allowed'] is True

def test_marketing_export_admin_only_and_snapshot(clients):
    admin,student,anon=clients
    q=admin.post('/api/questions',json={'statement':'Compute $2+2$.','options':['3','4'],'answer':'B','solution':'Four'}).json()
    exam=admin.post('/api/admin/exams',json={'name':'Marketing example','status':'OPEN','question_ids':[q['id']]}).json()
    path=f'/api/admin/exams/{exam["id"]}/marketing-pdf'
    assert student.post(path,json={}).status_code==403
    assert anon.post(path,json={}).status_code==401
    assert admin.post(path,json={},headers={'X-CSRF-Token':''}).status_code==403
    from pathlib import Path
    import json
    captured={}
    def worker(args,**kwargs):
        captured.update(json.loads(Path(args[2]).read_text()))
        Path(args[3]).write_bytes(b'%PDF-test')
        from unittest.mock import Mock
        return Mock(returncode=0,communicate=Mock(return_value=(b'',b'')))
    with patch('marketing_pdf.subprocess.Popen',side_effect=worker):
        r=admin.post(path,json={});assert r.status_code==200
        assert captured['data']['questions'][0]['statement']=='Compute $2+2$.'
        assert captured['options']['contact'].endswith('admin@meritiqra.com')
    with app.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM exam_sessions').fetchone()[0]==0
