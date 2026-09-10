"""Rank ties, ownership/release boundaries, revocation and concern workflow."""
import json
import time
from unittest.mock import patch
import pymupdf
import pytest
import app
from tests.test_programs import clients


def attempt(admin,student,release='IMMEDIATE'):
    q=admin.post('/api/questions',json={'subject':'Science','statement':'What is two plus two?','options':['3','4','5','6'],'answer':'B','solution':'Two plus two is four.','marks':'2'}).json()
    exam=admin.post('/api/admin/exams',json={'name':'Science entrance practice','status':'OPEN','question_ids':[q['id']],'result_release_mode':release}).json()
    assert student.post(f'/api/exams/{exam["id"]}/enroll').status_code==200
    sid=student.post(f'/api/exams/{exam["id"]}/sessions').json()['session_id']
    assert student.put(f'/api/sessions/{sid}/answers/{q["id"]}',json={'selected_answer':'B'}).status_code==200
    assert student.post(f'/api/sessions/{sid}/submit').status_code==200
    return sid,q,exam


def test_rank_report_share_concern_permissions(clients):
    admin,student,anonymous=clients;sid,q,exam=attempt(admin,student)
    r=student.get(f'/api/exams/{exam["id"]}/leaderboard');assert r.status_code==200,r.text
    assert r.json()['entries'][0]['rank']==1 and r.json()['entries'][0]['is_you']
    assert 'email' not in r.text and 'question_set' not in r.text
    assert anonymous.get(f'/api/results/{sid}/report.pdf').status_code==401
    report=student.get(f'/api/results/{sid}/report').json();assert report['subjects'][0]['score']==1
    assert student.get(f'/api/results/{sid}/report.pdf').status_code==403
    pdf=admin.get(f'/api/results/{sid}/report.pdf');assert pdf.status_code==200 and pdf.content.startswith(b'%PDF')
    with pymupdf.open(stream=pdf.content,filetype='pdf') as doc:
        text=''.join(p.get_text() for p in doc)
        assert 'Individual exam report' in text and 'Science entrance practice' in text
        assert 'What is two plus two' not in text and 'student@example.test' not in text
    assert student.post(f'/api/results/{sid}/share').status_code==403
    shared=admin.post(f'/api/results/{sid}/share');assert shared.status_code==200,shared.text
    path='/reports/shared/'+shared.json()['url'].rsplit('/',1)[-1]
    assert anonymous.get(path).status_code==200
    assert student.delete(f'/api/results/{sid}/share').status_code==200
    assert anonymous.get(path).status_code==404
    payload={'question_id':q['id'],'session_id':sid,'category':'ANSWER','description':'Please check whether the answer should be option B.'}
    concern=student.post('/api/question-concerns',json=payload);assert concern.status_code==201,concern.text
    cid=concern.json()['id'];assert student.post('/api/question-concerns',json=payload).json()['already_reported']
    assert student.put(f'/api/question-concerns/{cid}',json={'status':'RESOLVED','resolution':'Reviewed and verified.','revision':1}).status_code==403
    assert admin.put(f'/api/question-concerns/{cid}',json={'status':'RESOLVED','resolution':'Verified using the worked solution.','revision':1}).status_code==200
    assert student.get('/api/question-concerns?status=RESOLVED').json()[0]['resolution']
    assert student.post('/api/question-concerns',json={**payload,'question_id':999}).status_code==404
    # An unrelated logged-in student cannot read or share this attempt.
    anonymous.post('/api/auth/mock',json={'email':'other@example.test'});anonymous.headers['X-CSRF-Token']=anonymous.cookies['qb_csrf']
    assert anonymous.get(f'/api/results/{sid}/report').status_code==404
    assert anonymous.post(f'/api/results/{sid}/share').status_code==403
    assert anonymous.get(f'/api/exams/{exam["id"]}/leaderboard').status_code==403
    assert anonymous.get('/api/question-concerns?status=ALL').json()==[]


def test_unreleased_results_and_expired_share(clients):
    admin,student,anonymous=clients;sid,q,exam=attempt(admin,student,'AFTER_EXAM_CLOSE')
    for path in [f'/api/results/{sid}/report',f'/api/results/{sid}/report.pdf',f'/api/exams/{exam["id"]}/leaderboard']:
        assert student.get(path).status_code==403
    assert admin.get(f'/api/results/{sid}/report').status_code==200
    assert admin.post(f'/api/results/{sid}/share').status_code==403
    assert student.post('/api/question-concerns',json={'question_id':q['id'],'session_id':sid,'description':'This question needs checking.'}).status_code==403
    with app.connect() as conn:conn.execute("UPDATE exams SET status='CLOSED' WHERE id=?",(exam['id'],));conn.commit()
    link=admin.post(f'/api/results/{sid}/share').json()['url']
    with app.connect() as conn:conn.execute('UPDATE result_report_links SET expires_at=?',(time.time()-1,));conn.commit()
    assert anonymous.get('/reports/shared/'+link.rsplit('/',1)[-1]).status_code==404


def test_competition_ties_and_best_attempt_only(clients):
    admin,student,_=clients;sid,q,exam=attempt(admin,student)
    from result_features import ranked_attempts
    with app.connect() as conn:
        s=dict(conn.execute('SELECT * FROM exam_sessions WHERE id=?',(sid,)).fetchone());columns=[k for k in s if k!='id']
        # Same learner's lower retake must not replace the original best.
        s.update(attempt_number=2,score=0,percentage=0)
        conn.execute(f'INSERT INTO exam_sessions ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})',[s[k] for k in columns])
        for index,score in [(1,1),(2,0)]:
            uid=conn.execute("INSERT INTO users(google_sub,email,display_name,role,status,created_at,updated_at,last_login_at) VALUES(?,?,?,'STUDENT','ACTIVE',?,?,?)",(f'tie:{index}',f'tie{index}@example.test',f'Candidate {index}',time.time(),time.time(),time.time())).lastrowid
            s.update(user_id=uid,attempt_number=1,score=score,percentage=score*100,submitted_at=time.time())
            conn.execute(f'INSERT INTO exam_sessions ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})',[s[k] for k in columns])
        conn.commit();rows=ranked_attempts(conn,exam['id'])
        assert [r['rank'] for r in rows]==[1,1,3]
        assert rows[0]['id']==sid and len(rows)==3

def test_flag_question_during_active_exam_without_releasing_answers(clients):
    admin,student,anonymous=clients
    q=admin.post('/api/questions',json={'statement':'Two plus two?','options':['3','4'],'answer':'B'}).json()
    other=admin.post('/api/questions',json={'statement':'Unrelated','options':['1','2'],'answer':'A'}).json()
    exam=admin.post('/api/admin/exams',json={'name':'Flag active exam','status':'OPEN','question_ids':[q['id']],'result_release_mode':'AFTER_EXAM_CLOSE'}).json()
    student.post(f'/api/exams/{exam["id"]}/enroll');sid=student.post(f'/api/exams/{exam["id"]}/sessions').json()['session_id']
    payload={'question_id':q['id'],'session_id':sid,'category':'QUESTION','description':'Equation appears to be missing a symbol.'}
    r=student.post('/api/question-concerns',json=payload);assert r.status_code==201,r.text
    assert student.post('/api/question-concerns',json=payload).json()['already_reported']
    assert student.post('/api/question-concerns',json={**payload,'question_id':other['id']}).status_code==404
    flags=student.get(f'/api/sessions/{sid}/question-flags');assert flags.json()==[{'question_id':q['id'],'status':'OPEN'}]
    assert anonymous.get(f'/api/sessions/{sid}/question-flags').status_code==401
    assert student.get(f'/api/results/{sid}/report').status_code==409
    assert student.get(f'/api/sessions/{sid}').json()['session']['status']=='IN_PROGRESS'
    student.post('/api/auth/mock',json={'email':'another@example.test'});student.headers['X-CSRF-Token']=student.cookies['qb_csrf']
    assert student.post('/api/question-concerns',json=payload).status_code==404
    assert student.get(f'/api/sessions/{sid}/question-flags').status_code==404

def test_full_exam_subject_and_section_marks_use_attempt_snapshot(clients):
    admin,student,_=clients
    questions=[admin.post('/api/questions',json={'subject':subject,'statement':f'{i}: 2+2?','options':['3','4'],'answer':'B'}).json() for i,subject in enumerate(['Physics','Physics','Chemistry','Mathematics'])]
    exam=admin.post('/api/admin/exams',json={'name':'Full syllabus','status':'DRAFT','question_ids':[q['id'] for q in questions]}).json()
    with app.connect() as conn:
        for q,section in zip(questions,['Mechanics','Optics','Chemistry','Mathematics']):conn.execute('UPDATE exam_questions SET section_name=?,marks=4,negative_marks=1 WHERE exam_id=? AND question_id=?',(section,exam['id'],q['id']))
        conn.commit()
    assert admin.put(f'/api/admin/exams/{exam["id"]}/state',json={'status':'OPEN'}).status_code==200
    student.post(f'/api/exams/{exam["id"]}/enroll');sid=student.post(f'/api/exams/{exam["id"]}/sessions').json()['session_id']
    for q,answer in zip(questions,['B','A','B']):student.put(f'/api/sessions/{sid}/answers/{q["id"]}',json={'selected_answer':answer})
    student.post(f'/api/sessions/{sid}/submit')
    # Later edits cannot change historical classification or marks.
    with app.connect() as conn:conn.execute("UPDATE questions SET subject='Changed later' WHERE id=?",(questions[0]['id'],));conn.commit()
    report=student.get(f'/api/results/{sid}/report').json();subjects={r['subject']:r for r in report['subjects']};sections={r['subject']:r for r in report['sections']}
    assert subjects['Physics']['score']==3 and subjects['Physics']['max_score']==8 and subjects['Physics']['percentage']==37.5
    assert subjects['Physics']['correct']==1 and subjects['Physics']['incorrect']==1
    assert subjects['Mathematics']['unanswered']==1
    assert sections['Optics']['score']==-1 and sections['Optics']['percentage']==-25
    assert sum(r['score'] for r in report['subjects'])==report['session']['score']==7
    assert sum(r['max_score'] for r in report['sections'])==report['session']['max_score']==16
