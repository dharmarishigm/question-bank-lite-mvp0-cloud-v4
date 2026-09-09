import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
import app
from platform_api import init_platform


@pytest.fixture
def clients():
    with tempfile.TemporaryDirectory() as folder:
        path = str(Path(folder) / 'programs.db')
        with sqlite3.connect(path) as conn:
            conn.executescript(app.SCHEMA)
        with patch.object(app, 'DB_PATH', path), patch.dict(os.environ, {'APP_ENV':'test','AUTH_MODE':'mock','ADMIN_EMAILS':'admin@example.test'}):
            init_platform()
            with TestClient(app.app) as admin, TestClient(app.app) as student, TestClient(app.app) as anonymous:
                for client, email in [(admin,'admin@example.test'),(student,'student@example.test')]:
                    assert client.post('/api/auth/mock',json={'email':email}).status_code == 200
                    client.headers['X-CSRF-Token'] = client.cookies['qb_csrf']
                yield admin, student, anonymous


def create(admin):
    response = admin.post('/api/programs',json={'code':'NAVODAYA','name':'Navodaya'})
    assert response.status_code == 201, response.text
    return response.json()


def test_program_crud_lock_and_archive(clients):
    admin, student, anonymous = clients
    assert anonymous.get('/api/programs').status_code == 401
    assert student.post('/api/programs',json={'code':'NO','name':'No'}).status_code == 403
    program = create(admin)
    pid = program['id']
    assert admin.post('/api/programs',json={'code':'NAVODAYA','name':'Duplicate'}).status_code == 409
    assert admin.get('/api/programs?q=nav').json()['total'] == 1
    assert admin.put(f'/api/programs/{pid}?revision=1',json={'code':'NAVODAYA','name':'Updated'}).status_code == 200
    assert admin.put(f'/api/programs/{pid}?revision=1',json={'code':'NAVODAYA','name':'Stale'}).status_code == 409
    assert admin.delete(f'/api/programs/{pid}?revision=2').status_code == 200
    assert student.get(f'/api/programs/{pid}').status_code == 404
    assert admin.post(f'/api/programs/{pid}/restore?revision=3').status_code == 200
    assert student.get(f'/api/programs/{pid}').status_code == 200


def test_immutable_payload_lifecycle_and_history(clients):
    admin, student, _ = clients
    pid = create(admin)['id']
    payload = {'scope':'PROGRAM','overrides':{'EASY':{'seconds':30}}}
    created = admin.post(f'/api/programs/{pid}/blueprints',json={'kind':'QUESTION_GENERATOR','name':'Question defaults','payload':payload})
    assert created.status_code == 201, created.text
    body=created.json();bid=body['id'];version=body['version'];vid=version['id']
    path=f'/api/programs/{pid}/blueprints/{bid}'
    assert student.get(path+'/versions').json() == []
    for before,after in [('DRAFT','IN_REVIEW'),('IN_REVIEW','PUBLISHED')]:
        response=admin.post(path+f'/versions/{vid}/transition',json={'expected_status':before,'status':after,'reason':'Reviewed'})
        assert response.status_code==200,response.text
    assert len(student.get(path+'/versions').json())==1
    updated=admin.post(path+'/versions',json={'revision':1,'summary':'Increase time','payload':{'scope':'PROGRAM','overrides':{'EASY':{'seconds':40}}}})
    assert updated.status_code==201,updated.text
    assert updated.json()['version_number']==2
    original=admin.get(path+'/versions').json()[1]
    assert original['payload_hash']==version['payload_hash'] and original['status']=='PUBLISHED'
    assert admin.post(path+'/versions',json={'revision':1,'summary':'Stale','payload':payload}).status_code==409
    effective=admin.get(path+f'/effective/{vid}').json()
    assert effective['effective']['EASY']['seconds']==30
    diff=admin.get(path+f'/compare?left={vid}&right={updated.json()["id"]}').json()
    assert diff['changes']==[{'path':'/overrides/EASY/seconds','old':30,'new':40}]
    assert admin.delete(f'/api/programs/{pid}?revision=1').status_code==200
    assert len(admin.get(path+'/versions').json())==2


def test_cross_program_parent_is_rejected(clients):
    admin, _, _=clients
    pid=create(admin)['id']
    other=admin.post('/api/programs',json={'code':'OTHER','name':'Other'}).json()['id']
    version=admin.post(f'/api/programs/{pid}/blueprints',json={'kind':'QUESTION_GENERATOR','name':'Parent','payload':{'scope':'PROGRAM'}}).json()['version']['id']
    response=admin.post(f'/api/programs/{other}/blueprints',json={'kind':'QUESTION_GENERATOR','name':'Child','payload':{'scope':'TOPIC','parent_version_id':version}})
    assert response.status_code==422,response.text
