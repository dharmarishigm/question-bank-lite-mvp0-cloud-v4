"""History filtering beyond the first page and publication queue lifecycle."""
import app
from tests.test_programs import clients, create
from tests.test_program_exam import build


def test_history_filters_pagination_and_permissions(clients):
    admin,student,anonymous=clients
    with app.connect() as conn:
        for i in range(110):
            conn.execute('INSERT INTO ai_generation_runs(id,exam_name,subject,level,difficulty,topic,requested_count,generation_prompt,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                         (f'run-{i:03}', 'Navodaya' if i==0 else 'CAT', 'Maths' if i==0 else 'English', 'VI' if i==0 else 'Graduate', 'easy' if i==0 else 'hard', 'Fractions', 5,'Original questions','SAVED' if i==0 else 'REVIEW_REQUIRED',i))
        conn.commit()
    path='/api/ai/runs'
    assert anonymous.get(path).status_code==401
    assert student.get(path).status_code==403
    first=admin.get(path,params={'limit':25});assert first.headers['X-Total-Count']=='110'
    assert first.json()[0]['id']=='run-109'
    last=admin.get(path,params={'offset':100,'limit':25});assert len(last.json())==10
    assert last.json()[-1]['id']=='run-000'
    found=admin.get(path,params={'q':'navodaya','subject':'maths','level':'vi','difficulty':'easy','status':'saved'})
    assert found.headers['X-Total-Count']=='1' and found.json()[0]['id']=='run-000'
    assert admin.get(path,params={'q':"' OR 1=1 --"}).json()==[]
    assert admin.get(path,params={'offset':-1}).status_code==422


def test_queue_review_draft_publish_and_isolation(clients):
    admin,student,anonymous=clients;pid=create(admin)['id'];job=build(admin,pid)
    path='/api/programs/papers/review-queue';detail=f'/api/programs/{pid}/exam-papers/{job["id"]}'
    assert student.get(path).status_code==403 and anonymous.get(path).status_code==401
    assert student.get(detail).status_code==403
    assert admin.get(f'/api/programs/{pid+99}/exam-papers/{job["id"]}').status_code==404
    item=admin.get(path).json()['items'][0]
    assert item['question_count']==2 and item['status']=='REVIEW_REQUIRED'
    assert 'questions' not in item and 'result' not in item
    assert admin.get(detail).json()['result']['questions']
    assert admin.post(detail+'/approve',json={'reviewed':False,'publish':True}).status_code==422
    assert admin.post(detail+'/approve',json={'reviewed':True,'publish':False}).status_code==200
    assert admin.get(path).json()['items'][0]['status']=='DRAFT'
    assert admin.post(detail+'/approve',json={'reviewed':True,'publish':True}).status_code==200
    assert admin.get(path).json()=={'items':[],'total':0}


def test_archived_program_papers_are_not_publishable_queue_items(clients):
    admin,_,_=clients;pid=create(admin)['id'];build(admin,pid)
    revision=admin.get(f'/api/programs/{pid}').json()['revision']
    assert admin.delete(f'/api/programs/{pid}?revision={revision}').status_code==200
    assert admin.get('/api/programs/papers/review-queue').json()['total']==0
