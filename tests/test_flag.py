import io
import time
import zipfile
from unittest.mock import patch
import pymupdf
import openpyxl
import pytest
from tests.test_programs import clients
import flag_api


@pytest.fixture(autouse=True)
def private_storage(tmp_path,monkeypatch):
    monkeypatch.setenv('FLAG_LOCAL_DIR',str(tmp_path));monkeypatch.delenv('GCS_DATA_BUCKET',raising=False)
    flag_api.read_bytes.cache_clear()


def pdf_bytes():
    with pymupdf.open() as doc:
        page=doc.new_page();page.insert_text((50,50),'Patient flow forecasting links incidence and prevalence.')
        return doc.tobytes()


def xlsx_bytes():
    book=openpyxl.Workbook();sheet=book.active;sheet.title='Inputs';sheet.append(['Patients',100]);sheet.append(['Revenue','=B1*5']);sheet.merge_cells('A4:B4');sheet['A4']='Long merged description'
    output=io.BytesIO();book.save(output);return output.getvalue()


def grant(admin,**kwargs):
    return admin.put('/api/flag/members',json={'email':'student@example.test',**kwargs})


def test_entitlements_and_every_material_path(clients):
    admin,student,anon=clients
    assert anon.get('/api/flag/access').status_code==401
    assert student.get('/api/flag/access').json()['allowed'] is False
    assert student.get('/api/flag/materials').status_code==403
    assert student.get('/api/flag/members').status_code==403
    assert student.put('/api/flag/members',json={'email':'student@example.test'}).status_code==403
    assert student.post('/api/flag/materials',files={'file':('test.pdf',pdf_bytes())}).status_code==403
    result=admin.post('/api/flag/materials',files={'file':('test.pdf',pdf_bytes())});assert result.status_code==201,result.text
    mid=result.json()['ids'][0]
    paths=[f'/api/flag/materials/{mid}/download',f'/api/flag/materials/{mid}/pages/1',f'/api/flag/materials/{mid}/pages/1/image']
    for path in paths:
        assert student.get(path).status_code==403
        assert anon.get(path).status_code==401
    assert grant(admin).status_code==200
    assert student.get('/api/flag/access').json()['allowed']
    assert student.get(paths[0]).status_code==403
    for path in paths[1:]:assert student.get(path).status_code==200
    assert student.get(paths[1]).json()['words']
    assert admin.get(paths[0]).content.startswith(b'%PDF')
    assert grant(admin,active=False).status_code==200
    for path in paths:assert student.get(path).status_code==403
    assert grant(admin,kind='SUBSCRIBER').status_code==422
    expiry=time.time()+100
    assert grant(admin,kind='SUBSCRIBER',expires_at=expiry).status_code==200
    with patch('flag_api.time.time',return_value=expiry+1):assert student.get(paths[0]).status_code==403


def test_replace_upload_and_workbook_values(clients):
    admin,student,_=clients;grant(admin)
    old=admin.post('/api/flag/materials',files={'file':('a.pdf',pdf_bytes())}).json()['ids'][0]
    admin.post('/api/flag/materials',files={'file':('b.pdf',pdf_bytes())})
    assert admin.get(f'/api/flag/materials/{old}/download').status_code==404
    zipped=io.BytesIO()
    with zipfile.ZipFile(zipped,'w') as z:z.writestr('../Inputs.xlsx',xlsx_bytes())
    result=admin.post('/api/flag/materials',files={'file':('templates.zip',zipped.getvalue())});assert result.status_code==201,result.text
    mid=result.json()['ids'][0];path=f'/api/flag/materials/{mid}/sheet?name=Inputs'
    result=student.get(path);assert result.status_code==200,result.text
    assert result.json()['rows'][1][1]['formula']==''
    assert admin.get(path).json()['rows'][1][1]['formula']=='=B1*5'
    assert result.json()['merges']==[[4,1,4,2]]
    assert student.get(path.replace('Inputs','Missing')).status_code==404
    assert student.get(f'/api/flag/materials/{mid}/pages/1').status_code==404
    assert grant(admin,active=False).status_code==200
    assert student.get(path).status_code==403
    assert admin.post('/api/flag/materials',files={'file':('bad.pdf',b'bad')}).status_code==422
    assert admin.post('/api/flag/materials',files={'file':('bad.zip',b'bad')}).status_code==422


def test_explanation_source_csrf_and_quota(clients):
    admin,student,anon=clients;grant(admin)
    mid=admin.post('/api/flag/materials',files={'file':('test.pdf',pdf_bytes())}).json()['ids'][0]
    path=f'/api/flag/materials/{mid}/explain';data={'page':1,'selected_text':'Patient flow forecasting'}
    assert anon.post(path,json=data).status_code==401
    assert student.post(path,json=data,headers={'X-CSRF-Token':''}).status_code==403
    assert student.post(path,json={'page':1,'selected_text':'Invented source'}).status_code==422
    assert student.post(path,json={'page':1,'rectangle':[0,0,2,1]}).status_code==422
    with patch('blueprint_gemini.structured_call',return_value=(flag_api.Explanation(markdown='## Concept\nPatient flow.'),{})) as call:
        for _ in range(10):assert student.post(path,json=data).status_code==200
        assert student.post(path,json=data).status_code==429
        assert call.call_count==10
        assert call.call_args.args[2]['page_context'].startswith('Patient flow')
    grant(admin,active=False)
    assert student.post(path,json=data).status_code==403


def test_gate_ece_reference_fallback_and_live():
    from program_exam import Settings
    from gate_setup import lookup,is_ece
    import requests
    assert is_ece({'name':'GATE ECE'}) and is_ece({'code':'GATE_ECE'})
    assert not is_ece({'name':'GATE Electrical Engineering'})
    with patch('official_exam.fetch_document',side_effect=requests.exceptions.SSLError('TLS')):
        result=lookup(Settings(difficulty='hard'))
    assert result['live_verified'] is False and result['checked_at'].startswith('2026-09-10')
    assert 'Live verification was unavailable' in result['status_label']
    assert sum(s['count'] for s in result['settings']['sections'])==65
    assert sum(s['count']*s['marks'] for s in result['settings']['sections'])==100
    assert result['settings']['difficulty']=='hard'
    with patch('official_exam.fetch_document',side_effect=[{'text':'GATE 2027 10(General Aptitude) + 55(Subject) = 65 100 180 13 72 1/3 2/3','sha256':'p'}, {'text':'Electronics and Communication Engineering syllabus','sha256':'s'}]):
        assert lookup(Settings())['live_verified'] is True
