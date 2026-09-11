import time
from cryptography.fernet import Fernet
from tests.test_programs import clients
from security_mfa import code_for


def test_staff_mfa_enrollment_replay_and_step_up(clients,monkeypatch):
    admin,student,anon=clients
    monkeypatch.setenv('REQUIRE_STAFF_MFA','1')
    monkeypatch.setenv('SECURITY_HARDENING','1')
    monkeypatch.setenv('MFA_ENCRYPTION_KEY',Fernet.generate_key().decode())
    assert admin.get('/api/auth/me').json()['mfa_required']
    assert admin.get('/api/admin/users').status_code==403
    assert student.get('/api/auth/me').json()['mfa_required'] is False
    setup=admin.post('/api/auth/mfa/setup',json={})
    assert setup.status_code==200,setup.text
    key=setup.json()['secret']
    code=code_for(key,int(time.time()//30))
    assert admin.post('/api/auth/mfa/verify',json={'code':code}).status_code==200
    assert admin.get('/api/admin/users').status_code==200
    assert admin.post('/api/auth/mfa/verify',json={'code':code}).status_code==401
    assert admin.post('/api/auth/mfa/setup',json={}).status_code==409
    assert anon.post('/api/auth/mfa/setup',json={}).status_code==401
    assert student.post('/api/auth/mfa/setup',json={}).status_code==403


def test_idle_expiry_is_enforced(clients,monkeypatch):
    admin,_,_=clients
    monkeypatch.setenv('REQUIRE_STAFF_MFA','1')
    monkeypatch.setenv('SECURITY_HARDENING','1')
    monkeypatch.setenv('SESSION_IDLE_SECONDS','-1')
    assert admin.get('/api/auth/me').status_code==401


def test_active_student_session_survives_three_hour_exam(clients,monkeypatch):
    from contextlib import closing
    from platform_api import db,_hash
    _,student,_=clients
    monkeypatch.setenv('REQUIRE_STAFF_MFA','1')
    monkeypatch.setenv('SECURITY_HARDENING','1')
    assert student.get('/api/auth/me').status_code==200
    token=_hash(student.cookies['qb_session'])
    # Age the login, but retain recent activity and its original 12-hour expiry.
    with closing(db()) as conn:
        conn.execute('UPDATE app_sessions SET created_at=? WHERE token_hash=?',(time.time()-3*3600,token));conn.commit()
    response=student.get('/api/auth/me')
    assert response.status_code==200
    assert response.json()['mfa_required'] is False
