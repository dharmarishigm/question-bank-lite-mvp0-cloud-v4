from unittest.mock import patch

from tests.test_programs import clients, create
from blueprint_setup import SetupProposal
from blueprint_domain import Difficulty


def proposal():
    return SetupProposal(description='Practice preparation for Navodaya entrance learning.',authority='Suggested authority',region='India',category='Entrance preparation',level='VI',variant='JNVST_CLASS_VI',
        subjects=[{'name':'Arithmetic','chapters':[{'name':'Numbers','topics':['Fractions']}]}],
        sections=[{'name':'Arithmetic practice','subject':'Arithmetic','question_count':5,'seconds_per_question':60}],
        profiles=[{'difficulty':d,'reasoning_steps':i+1,'stem_max_words':80,'distractor_strategy':'Common arithmetic misconceptions','solution_format':'Explain each reasoning step'} for i,d in enumerate(Difficulty)],
        assumptions=['Class VI inferred from program name; confirm before use.'],evidence_needed=['Obtain the official syllabus and notification.','Upload authentic prior-year papers for historical analysis.'])


def start(admin,pid,key='setup-test-001'):
    with patch('blueprint_setup.structured_call',return_value=(proposal(),{'model':'mock-model','outcome':'SUCCEEDED'})):
        r=admin.post(f'/api/programs/{pid}/setup',json={'request_key':key})
    assert r.status_code==202,r.text
    return r.json()['id']


def test_minimal_setup_all_tabs_and_replay(clients):
    admin,student,_=clients;pid=create(admin)['id'];root=f'/api/programs/{pid}'
    assert student.post(root+'/setup',json={'request_key':'student-001'}).status_code==403
    jid=start(admin,pid)
    assert admin.get(root+'/setup').json()[0]['status']=='READY'
    assert admin.get(root+'/blueprints').json()==[]  # Proposals do not mutate workspace.
    assert start(admin,pid)==jid
    result=admin.post(root+f'/setup/{jid}/apply')
    assert result.status_code==200,result.text
    ids=result.json()
    assert admin.get(root).json()['payload']['description']==proposal().description
    curricula=admin.get(root+'/curricula').json()
    assert curricula[0]['status']=='DRAFT' and len(curricula[0]['nodes'])==3
    bps=admin.get(root+'/blueprints').json()
    assert {b['kind'] for b in bps}=={'EXAM_PATTERN','EXAM_GENERATOR','QUESTION_GENERATOR'}
    for bp in bps:
        v=admin.get(root+f"/blueprints/{bp['id']}/versions").json()[0]
        assert v['status']=='DRAFT'
        if bp['kind']=='EXAM_PATTERN':assert v['payload']['sample_only'] and v['payload']['official_source_ids']==[]
    assert len(admin.get(root+'/prompts').json()['items'])==10
    run=admin.get(root+'/paper-runs').json()[0]
    assert run['id']==ids['paper_run_id'] and run['payload']['sample_preview'] and len(run['payload']['gaps'])==5
    assert admin.get(root+'/sources').json()==[]
    assert admin.get(root+'/historical-profiles').json()==[]
    assert admin.post(root+f'/setup/{jid}/apply').status_code==409
    assert len(admin.get(root+'/curricula').json())==1
    assert admin.get(root+'/audit').json()[0]['action']=='PROGRAM_SETUP_APPLIED'


def test_setup_stale_edit_and_atomic_failure(clients):
    admin,_,_=clients;pid=create(admin)['id'];root=f'/api/programs/{pid}';jid=start(admin,pid)
    with patch('blueprint_setup.feasibility_data',side_effect=ValueError('Synthetic failure')):
        try:admin.post(root+f'/setup/{jid}/apply')
        except ValueError:pass
    assert admin.get(root+'/setup').json()[0]['status']=='READY'
    assert admin.get(root+'/blueprints').json()==[] and admin.get(root+'/curricula').json()==[]
    assert admin.get(root).json()['revision']==1
    admin.put(root+'?revision=1',json={'code':'NAVODAYA','name':'Navodaya updated'})
    assert admin.post(root+f'/setup/{jid}/apply').status_code==409
    assert admin.get(root+'/blueprints').json()==[]


def test_setup_failed_provider_is_safe_and_retryable(clients):
    admin,_,_=clients;pid=create(admin)['id'];root=f'/api/programs/{pid}'
    with patch('blueprint_setup.structured_call',side_effect=TimeoutError('secret diagnostic')):
        jid=admin.post(root+'/setup',json={'request_key':'failure-001'}).json()['id']
    failed=admin.get(root+'/setup').json()[0]
    assert failed['status']=='FAILED' and 'secret' not in failed['error']
    assert admin.get(root+'/blueprints').json()==[]
    with patch('blueprint_setup.structured_call',return_value=(proposal(),{'model':'mock'})):
        assert admin.post(root+f'/setup/{jid}/retry').status_code==202
    assert admin.get(root+'/setup').json()[0]['status']=='READY'
