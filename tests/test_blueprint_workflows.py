from copy import deepcopy
from unittest.mock import patch
import pytest
from tests.test_programs import clients, create
from tests.test_blueprint_domain import pattern
from blueprint_domain import Difficulty, compile_slots, content_hash
from blueprint_papers import Candidate, select
from blueprint_gemini import Proposal, apply_proposal, IndependentSolution
from blueprint_history import aggregate


def candidate(i,slot):
    return {'id':i,'payload_hash':str(i),'academic_status':'APPROVED','transcription_status':'APPROVED','exposure':0,
        'payload':Candidate(subject=slot['subject'],variant='JNVST_CLASS_6',difficulty=slot['difficulty'],qtype='SINGLE_CORRECT',language='English',scoring={'positive':'1.25'},seconds=60,
            semantic_cluster=str(i),statement=f'Question {i}',options=['One','Two','Three','Four'],answers=['A'],solution='Reasoning').model_dump(mode='json')}


def slots():
    return compile_slots(pattern(),{'pattern_version_id':1,'rules':[{'section':'MAT','block':'A','language':'English','seconds':60,'question_blueprint_version_id':2,'difficulty':{d.value:100 if d==Difficulty.MEDIUM else 0 for d in Difficulty}}]})


def test_exact_selection_partial_gaps_exposure_and_clusters():
    spec=slots();pool=[candidate(i,spec[0]) for i in range(4)]
    result=select(spec,pool,'JNVST_CLASS_6',2,17)
    assert result['feasible'] and len(result['selected'])==4
    assert result==select(spec,pool,'JNVST_CLASS_6',2,17)
    pool[0]['exposure']=2
    result=select(spec,pool,'JNVST_CLASS_6',2,17)
    assert not result['feasible'] and len(result['gaps'])==1 and len(result['selected'])==3
    pool[1]['payload']['semantic_cluster']=pool[2]['payload']['semantic_cluster']
    assert len(select(spec,pool,'JNVST_CLASS_6',2,17)['gaps'])==2
    pool[3]['academic_status']='IN_REVIEW'
    assert len(select(spec,pool,'JNVST_CLASS_6',2,17)['selected'])==1


def test_stimulus_integrity_and_duplicate_stems():
    spec=slots()[:2]
    for i,s in enumerate(spec):s.update(stimulus_size=2,stimulus_position=i+1,stimulus_group='passage')
    pool=[candidate(i,s) for i,s in enumerate(spec)]
    for i,q in enumerate(pool):q['payload'].update(stimulus_size=2,stimulus_position=i+1,stimulus_id='paperA')
    assert select(spec,pool,'JNVST_CLASS_6',10,1)['feasible']
    pool[1]['payload']['stimulus_id']='paperB'
    assert len(select(spec,pool,'JNVST_CLASS_6',10,1)['gaps'])==2


def test_refinement_allowlist_and_original_immutability():
    source={'scope':'PROGRAM','overrides':{'MEDIUM':{'seconds':60}}}
    proposal=Proposal(patches=[{'path':'/overrides/MEDIUM/seconds','old':60,'new':75,'reason':'More steps','confidence':0.8,'impact':'Longer solve time'}])
    result=apply_proposal('QUESTION_GENERATOR',source,proposal,[0])
    assert result['overrides']['MEDIUM']['seconds']==75 and source['overrides']['MEDIUM']['seconds']==60
    proposal.patches[0].path='/seconds'
    with pytest.raises(ValueError,match='cannot change'):apply_proposal('EXAM_PATTERN',source,proposal,[])


def test_historical_recency_contamination_and_small_sample():
    rows=[{'source_id':1,'source_question_ref':'1','year':2020,'subject':'Math','topic':'Fractions','difficulty':'EASY','qtype':'SINGLE_CORRECT','language':'English','estimated_seconds':60,'confidence':'0.9','classification_reason':'One reasoning step'},
          {'source_id':2,'source_question_ref':'1','year':2025,'subject':'Math','topic':'Algebra','difficulty':'HARD','qtype':'SINGLE_CORRECT','language':'English','estimated_seconds':90,'confidence':'0.8','classification_reason':'Three reasoning steps'}]
    result=aggregate(rows,2025)
    assert result['counts']['subject']['Math']==2 and result['warnings']
    assert result['recency_weighted_counts']['topic']['Fractions']==0.5
    rows[0]['origin']='GEMINI_GENERATED'
    with pytest.raises(ValueError):aggregate(rows,2025)


def setup_run(admin,pid):
    root=f'/api/programs/{pid}'
    question=admin.post(root+'/blueprints',json={'kind':'QUESTION_GENERATOR','name':'Question','payload':{'scope':'PROGRAM'}}).json()['version']['id']
    pat=admin.post(root+'/blueprints',json={'kind':'EXAM_PATTERN','name':'Sample','payload':pattern()}).json()['version']['id']
    gen={'pattern_version_id':pat,'rules':[{'section':'MAT','block':'A','language':'English','seconds':60,'question_blueprint_version_id':question,'difficulty':{d.value:100 if d==Difficulty.MEDIUM else 0 for d in Difficulty}}]}
    response=admin.post(root+'/blueprints',json={'kind':'EXAM_GENERATOR','name':'Generator','payload':gen})
    assert response.status_code==201,response.text
    return root,response.json()['version']['id']


def test_paper_run_freezes_versions_and_requires_separate_review(clients):
    admin,student,_=clients;pid=create(admin)['id'];root,vid=setup_run(admin,pid)
    for i in range(4):
        response=admin.post(root+'/inventory',json={'payload':candidate(i,slots()[0])['payload'],'provenance_note':'Manual test fixture'})
        assert response.status_code==201,response.text
        qid=response.json()['id']
        assert admin.post(root+'/inventory/'+str(qid)+'/review',json={'academic_status':'APPROVED','transcription_status':'APPROVED','reason':'Reviewed fixture','checked_answer_solution':True,'checked_source_fidelity':True,'checked_curriculum_age_language':True,'checked_duplicates_and_visuals':True}).status_code==200
    response=admin.post(root+'/paper-runs',json={'blueprint_version_id':vid,'sample_preview':True})
    assert response.status_code==201,response.text
    run=response.json();assert run['payload']['feasible']
    assert admin.post(root+f"/paper-runs/{run['id']}/approve",json={'status':'APPROVED','reason':'Sample'}).status_code==422
    assert student.get(root+'/paper-runs').status_code==403
    assert content_hash(admin.get(root+'/paper-runs').json()[0]['payload'])==content_hash(run['payload'])


def test_gemini_proposal_acceptance_and_failure(clients):
    admin,_,_=clients;pid=create(admin)['id'];root=f'/api/programs/{pid}'
    bp=admin.post(root+'/blueprints',json={'kind':'QUESTION_GENERATOR','name':'Question','payload':{'scope':'PROGRAM'}}).json()
    prompt=admin.post(root+'/prompts',json={'purpose':'BLUEPRINT_REFINEMENT','template':'Review soft authoring settings.'}).json()['id']
    proposal=Proposal(patches=[{'path':'/overrides/MEDIUM/seconds','old':None,'new':75,'reason':'Longer reasoning','confidence':0.7,'impact':'Allow more time'}])
    with patch('blueprint_api.structured_call',return_value=(proposal,{'model':'mock','usage':{},'outcome':'SUCCEEDED'})):
        rid=admin.post(root+'/refinements',json={'version_id':bp['version']['id'],'prompt_id':prompt}).json()['id']
    assert admin.get(root+'/refinements').json()[0]['status']=='READY'
    result=admin.post(root+f'/refinements/{rid}/accept',json={'accepted_indices':[0],'revision':1,'reason':'Approved time override'})
    assert result.status_code==200,result.text
    assert result.json()['status']=='DRAFT' and result.json()['version_number']==2
    assert admin.post(root+f'/refinements/{rid}/accept',json={'accepted_indices':[0],'revision':2,'reason':'Again'}).status_code==409
    with patch('blueprint_api.structured_call',side_effect=TimeoutError('private provider details')):
        admin.post(root+'/refinements',json={'version_id':result.json()['id'],'prompt_id':prompt})
    failure=admin.get(root+'/refinements').json()[0]
    assert failure['status']=='FAILED' and 'private' not in failure['error']


def test_generated_gap_stays_draft_and_verifier_is_blind(clients):
    admin,_,_=clients;pid=create(admin)['id'];root,vid=setup_run(admin,pid)
    run=admin.post(root+'/paper-runs',json={'blueprint_version_id':vid,'sample_preview':True}).json()
    prompt_ids=[admin.post(root+'/prompts',json={'purpose':purpose,'template':'Use the supplied slot and independently reason.'}).json()['id'] for purpose in ('QUESTION_AUTHORING','INDEPENDENT_SOLVING')]
    calls=[]
    def mocked(purpose,prompt,data,schema):
        calls.append((purpose,data))
        if purpose=='QUESTION_AUTHORING':return Candidate.model_validate(candidate(99,slots()[0])['payload']),{'model':'mock-author'}
        assert 'answers' not in data['question'] and 'solution' not in data['question']
        return IndependentSolution(answers=['A'],reasoning='Independently derived.',curriculum_match=True,age_appropriate=True,plausible_distractors=True,unambiguous=True,units_valid=True,difficulty_supported=True,language_valid=True,estimated_seconds=60),{'model':'mock-verifier'}
    with patch('blueprint_api.structured_call',side_effect=mocked):
        result=admin.post(root+f"/paper-runs/{run['id']}/generate-missing",json={'slot_position':1,'author_prompt_id':prompt_ids[0],'verifier_prompt_id':prompt_ids[1]})
    assert result.status_code==202,result.text
    job=admin.get(root+'/generation-jobs').json()[0]
    assert job['status']=='DRAFT_READY',job
    assert len(calls)==2
    inventory=admin.get(root+'/inventory').json()[0]
    assert inventory['origin']=='GEMINI_GENERATED' and inventory['academic_status']=='IN_REVIEW'
    assert admin.post(root+'/paper-feasibility',json={'blueprint_version_id':vid,'sample_preview':True}).json()['selected']==[]


def test_history_profile_freezes_inclusion_and_rejects_cross_program(clients):
    admin,_,_=clients;pid=create(admin)['id'];root=f'/api/programs/{pid}'
    source=admin.post(root+'/sources',json={'kind':'HISTORICAL_QUESTION_PAPER','uri':'https://example.test/paper.pdf','sha256':'a'*64,'filename':'paper.pdf','mime_type':'application/pdf','authority':'Fixture','edition':'2025','language':'English','authorized_use':True}).json()['id']
    observation={'source_id':source,'source_question_ref':'1','year':2025,'subject':'Math','topic':'Fractions','difficulty':'EASY','qtype':'SINGLE_CORRECT','language':'English','estimated_seconds':60,'confidence':'0.9','classification_reason':'Reviewed one-step fraction problem'}
    assert admin.post(root+'/historical-observations',json=observation).status_code==422
    review={'status':'APPROVED','included':True,'reason':'Checksum checked','checksum_checked':True}
    assert admin.post(root+f'/sources/{source}/review',json=review).status_code==200
    oid=admin.post(root+'/historical-observations',json=observation).json()['id']
    assert admin.post(root+'/historical-profiles',json={'reference_year':2025}).status_code==422
    admin.post(root+f'/historical-observations/{oid}/review',json={'status':'APPROVED','reason':'Reviewed classification'})
    profile=admin.post(root+'/historical-profiles',json={'reference_year':2025})
    assert profile.status_code==201,profile.text
    frozen=admin.get(root+'/historical-profiles').json()[0]
    review['included']=False;admin.post(root+f'/sources/{source}/review',json=review)
    assert admin.post(root+'/historical-profiles',json={'reference_year':2025}).status_code==422
    assert admin.get(root+'/historical-profiles').json()[0]==frozen
