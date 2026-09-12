"""Every saved authoring surface resolves corrected bank content."""
import json
import time
from unittest.mock import patch

import app
from tests.test_programs import clients,create
from tests.test_question_correction import fields


def test_saved_workspaces_and_legacy_views_override_corrected_content(clients):
    admin,_,_=clients
    pid=create(admin)['id']
    question=admin.post('/api/questions',json={'statement':'Original stem','options':['one','two'],
        'answer':'A','solution':'Original solution','verification_status':'APPROVED'}).json()
    workspace=admin.post('/api/grand-tests',json={'program_id':pid,'name':'Saved source'}).json()
    path=f'/api/grand-tests/{workspace["id"]}'
    old={'id':'source-region-1','saved_question_id':question['id'],**fields(question),
         'explanation_en':'stale teaching text','reviewed':True,'source_page':7}
    unsaved={'id':'unsaved-region','statement':'Unsaved work stays unchanged','options':['a','b']}
    with app.connect() as conn:
        conn.execute('UPDATE grand_tests SET questions_json=? WHERE id=?',(json.dumps([old,unsaved]),workspace['id']));conn.commit()
    corrected={**fields(question),'statement':'Corrected stem','options':['two','one'],'answer':'B','solution':'Corrected solution'}
    response=admin.put(f'/api/admin/question-corrections/{question["id"]}',json={'original':fields(question),'question':corrected,'reviewed':True})
    assert response.status_code==200,response.text
    visible=admin.get(path).json()
    assert visible['revision']==workspace['revision']+1
    assert visible['questions'][1]==unsaved
    assert visible['questions'][0]['id']=='source-region-1'
    assert visible['questions'][0]['source_page']==7
    for key,value in corrected.items():assert visible['questions'][0][key]==value
    assert visible['questions'][0]['explanation_en']==''
    with app.connect() as conn:
        stored=json.loads(conn.execute('SELECT questions_json FROM grand_tests WHERE id=?',(workspace['id'],)).fetchone()['questions_json'])
        assert stored[0]['statement']=='Corrected stem' and stored[1]==unsaved
        # Simulate a saved copy from before correction propagation was deployed.
        conn.execute('UPDATE grand_tests SET questions_json=? WHERE id=?',(json.dumps([old,unsaved]),workspace['id']));conn.commit()
    detail=admin.get(path).json()
    listing=next(item for item in admin.get('/api/grand-tests').json() if item['id']==workspace['id'])
    for view in (detail,listing):
        assert view['questions'][0]['statement']=='Corrected stem'
        assert view['questions'][0]['options']==['two','one']
        assert view['questions'][1]==unsaved
    assert admin.get(f'/api/questions/{question["id"]}').json()['solution']=='Corrected solution'


def test_noop_review_keeps_bilingual_cache(clients):
    admin,_,_=clients
    question=admin.post('/api/questions',json={'statement':'Reviewed stem','options':['one','two'],
        'answer':'A','solution':'Reviewed solution','verification_status':'APPROVED'}).json()
    now=time.time()
    with app.connect() as conn:
        for language,text in [('en','Reviewed English'),('te','సమీక్షించిన వివరణ')]:
            conn.execute('INSERT INTO question_explanation_translations(question_id,language,explanation,liked,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                         (question['id'],language,text,1,now,now))
        conn.commit()
        before=[dict(row) for row in conn.execute('SELECT * FROM question_explanation_translations ORDER BY id').fetchall()]
    with patch('explanation_jobs.generate_bilingual',side_effect=AssertionError('No-op review must not regenerate')):
        response=admin.put(f'/api/admin/question-corrections/{question["id"]}',json={'original':fields(question),'question':fields(question),'reviewed':True})
        assert response.status_code==200,response.text
    with app.connect() as conn:
        assert [dict(row) for row in conn.execute('SELECT * FROM question_explanation_translations ORDER BY id').fetchall()]==before
