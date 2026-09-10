"""Evidence integrity, source isolation and automatic setup API tests."""
from datetime import datetime, timezone
from unittest.mock import patch
import pytest

from tests.test_programs import clients, create
from official_exam import OfficialPattern, validate_evidence, official_url, safe_url, numbers
from program_exam import Settings

YEAR=datetime.now(timezone.utc).year+1
ROW1='Mental Ability and Environmental Studies 20 + 20 25 + 25 60 Minutes'
ROW2='Arithmetic Test 20 25 30 Minutes'
ROW3='Language Test 20 25 30 Minutes'
CYCLE=f'Class VI Selection Test {YEAR} for admission in {YEAR}-{YEAR+1}.'
QUOTE='\n'.join([ROW1,ROW2,ROW3,'Total 80 100 2 Hours'])
NEGATIVE='No negative marking will be done.'
DOCUMENT={'url':'https://example.gov.in/prospectus.pdf','text':'\n'.join([CYCLE,QUOTE,NEGATIVE]),'sha256':'a'*64,'links':[]}


def official():
    return OfficialPattern(exam_name='JNVST Class VI',authority='NVS',level='VI',exam_year=YEAR,
        exam_cycle=f'{YEAR}-{YEAR+1}',source_index=0,cycle_quote=CYCLE,pattern_quote=QUOTE,
        negative_marking_quote=NEGATIVE,total_questions=80,total_marks=100,duration_minutes=120,negative_marks=0,
        sections=[{'subject':'Mental Ability and Environmental Studies','count':40,'total_marks':50,'duration_minutes':60,'evidence_quote':ROW1},
                  {'subject':'Arithmetic Test','count':20,'total_marks':25,'duration_minutes':30,'evidence_quote':ROW2},
                  {'subject':'Language Test','count':20,'total_marks':25,'duration_minutes':30,'evidence_quote':ROW3}])


def result():
    p=official()
    values=Settings(name=p.exam_name,level='VI',duration_minutes=120,curriculum='## Suggested syllabus\n\nReasoning, environmental studies, arithmetic and reading.',
        pattern='## Official pattern\n\n80 questions, 100 marks, 120 minutes.',generation_prompt='## Authoring instructions\n\n- Use the selected difficulty.\n- Provide worked solutions.',
        sections=[{'subject':s.subject,'count':s.count,'marks':1.25,'duration_minutes':s.duration_minutes} for s in p.sections]).model_dump()
    return {'settings':values,'official':p.model_dump(),'sources':[{'url':DOCUMENT['url'],'sha256':DOCUMENT['sha256'],'title':'Official prospectus'}],
        'checked_at':datetime.now(timezone.utc).isoformat(),'assumptions':[],'search_html':'','queries':[]}


def test_official_rows_and_composite_totals_require_evidence():
    assert validate_evidence(official(),[DOCUMENT])==DOCUMENT
    assert 40 in numbers('20 + 20') and 40 not in numbers('20 20')
    bad=official();bad.sections[0].count=41
    with pytest.raises(ValueError):validate_evidence(bad,[DOCUMENT])
    bad=official();bad.sections[0].evidence_quote=ROW2
    with pytest.raises(ValueError):validate_evidence(bad,[DOCUMENT])
    bad=official();bad.pattern_quote='Invented pattern 80 100 120'
    with pytest.raises(ValueError):validate_evidence(bad,[DOCUMENT])
    bad=official();bad.exam_year=2020
    with pytest.raises(ValueError):validate_evidence(bad,[DOCUMENT])
    with pytest.raises(ValueError):validate_evidence(official(),[{**DOCUMENT,'url':'https://coaching.example/prospectus.pdf'}])


def test_source_allowlist_and_private_address_rejection():
    assert official_url('https://cbseitms.rcil.gov.in/nvs/')
    assert official_url('https://ielts.org/take-a-test/test-types/ielts-academic-test')
    assert not official_url('https://ielts.org.attacker.com/')
    for value in ['http://example.gov.in/file','https://example.gov.in.attacker.com/file','https://user:pass@example.gov.in/','http://169.254.169.254/','https://example.gov.in:8443/file']:
        assert not official_url(value)
    with patch('official_exam.socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
        with pytest.raises(ValueError):safe_url('https://example.gov.in/file')


def test_lookup_persistence_reference_isolation_and_markdown(clients):
    admin,student,anonymous=clients;pid=create(admin)['id'];path=f'/api/programs/{pid}/official-pattern'
    data={'request_key':'official-request-001','settings':{}}
    assert admin.get(path).json() is None
    assert student.post(path,json=data).status_code==403
    assert anonymous.get(path).status_code==401
    with patch('official_exam.lookup_official',return_value=result()) as lookup:
        response=admin.post(path,json=data)
        assert response.status_code==202,response.text
        assert admin.post(path,json=data).json()['id']==response.json()['id']
        assert lookup.call_count==1
    job=admin.get(path).json();assert job['status']=='READY'
    setup=job['result']['settings'];assert setup['official_lookup_id']==job['id']
    preview=admin.post(f'/api/programs/{pid}/exam-prompt',json=setup)
    assert preview.status_code==200,preview.text
    body=preview.json();assert body['question_count']==80 and body['total_marks']==100
    assert '## Subject-wise pattern' in body['effective_prompt'] and '| Subject |' in body['effective_prompt']
    assert DOCUMENT['url'] in body['effective_prompt']
    other=admin.post('/api/programs',json={'code':'OTHER_OFFICIAL','name':'Other'}).json()['id']
    assert admin.post(f'/api/programs/{other}/exam-prompt',json=setup).status_code==422
    assert admin.get('/api/questions').json()['total']==0


def test_lookup_failure_does_not_invent_official_pattern(clients):
    admin,_,_=clients;pid=create(admin)['id'];path=f'/api/programs/{pid}/official-pattern'
    with patch('official_exam.lookup_official',side_effect=ValueError('private diagnostic')):
        assert admin.post(path,json={'request_key':'failed-official-001','settings':{}}).status_code==202
    job=admin.get(path).json();assert job['status']=='FAILED' and job['result']=={}
    assert 'private diagnostic' not in job['error']
    assert admin.post(path,json={'request_key':'failed-official-001','settings':{'level':'IX'}}).status_code==409


def test_serving_schema_preserves_property_names():
    from blueprint_gemini import serving_schema
    from program_exam import CompleteSuggestion
    schema = serving_schema(CompleteSuggestion)
    assert "pattern" in schema["properties"]
    assert set(schema["required"]) <= set(schema["properties"])


@pytest.mark.parametrize('grade',[8,9])
def test_supported_undated_sof_page_keeps_unknown_penalty_explicit(grade):
    title=f'SOF International Science Olympiad (ISO) Syllabus Class {grade}'
    quote='Total Questions: 50 Time: 1 hr. Science 45 45 Achievers Section 5 15 Grand Total 50 60'
    doc={'url':f'https://sofworld.org/nso/class-{grade}/nso-syllabus/nso-syllabus-class-{grade}','text':title+' '+quote,'sha256':'a'*64}
    p=OfficialPattern(exam_name='Science Olympiad',authority='SOF',level=f'Class {grade}',exam_year=None,
        exam_cycle='Current published syllabus (undated)',source_index=0,cycle_quote=title,pattern_quote=quote,
        negative_marks=None,negative_marking_quote='',total_questions=50,total_marks=60,duration_minutes=60,
        sections=[{'subject':'Science','count':45,'total_marks':45,'evidence_quote':'Science 45 45'},
                  {'subject':'Achievers Section','count':5,'total_marks':15,'evidence_quote':'Achievers Section 5 15'}])
    assert validate_evidence(p,[doc])==doc
    wrong=p.model_copy(update={'level':'Class 9' if grade==8 else 'Class 8'})
    with pytest.raises(ValueError):validate_evidence(wrong,[doc])
    with pytest.raises(ValueError):validate_evidence(p,[{**doc,'url':'https://example.gov.in/syllabus'}])
    p.negative_marks=0
    with pytest.raises(ValueError):validate_evidence(p,[doc])
    assert official_url(doc['url'])
    assert not official_url('https://sofworld.org.attacker.test/')


def test_class9_guidance_uses_previous_class_source_and_keeps_grade():
    from official_exam import lookup_official
    from program_exam import CompleteSuggestion,Section
    title='SOF International Science Olympiad (ISO) Syllabus Class 9'
    quote='Total Questions: 50 Time: 1 hr. Science 45 45 Achievers Section 5 15 Grand Total 50 60'
    url='https://sofworld.org/nso/class-9/nso-syllabus/nso-syllabus-class-9'
    doc={'url':url,'text':title+' '+quote+' Official current school syllabus for practice coverage.','sha256':'a'*64,'links':[]}
    previous={'url':url.replace('class-9','class-8'),'text':'Class 8 official syllabus material','sha256':'b'*64,'links':[]}
    pattern=OfficialPattern(exam_name='SOF Science',authority='SOF',level='Level 1',exam_cycle='Current published syllabus (undated)',source_index=0,cycle_quote=title,pattern_quote=quote,total_questions=50,total_marks=60,duration_minutes=60,
        sections=[{'subject':'Science','count':45,'total_marks':45,'evidence_quote':'Science 45 45'},{'subject':'Achievers Section','count':5,'total_marks':15,'evidence_quote':'Achievers Section 5 15'}])
    guidance=CompleteSuggestion(curriculum='Class 9 and applicable Class 8 topics',level='Class 9',pattern='Practice',duration_minutes=60,sections=[Section(subject='Science',count=45),Section(subject='Achievers Section',count=5)],instructions='Review the source',generation_prompt='Current class achievers questions')
    with patch('official_exam.fetch_document',side_effect=[doc,previous]) as fetch,patch('official_exam.structured_call',side_effect=[(pattern,{}),(guidance,{})]) as model:
        result=lookup_official({'name':'Science Olympiad SOF'},Settings(level='Class 9'))
    assert result['settings']['level']=='Class 9'
    assert len(result['sources'])==2
    assert fetch.call_args_list[1].args[0]==previous['url']
    assert model.call_args_list[1].args[2]['previous_class_curriculum_document']==previous['text']
