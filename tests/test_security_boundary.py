from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi import HTTPException
from tests.test_programs import clients
from security_boundary import reserve


def test_private_routes_fail_closed_without_login_config(clients, monkeypatch):
    admin, student, anonymous = clients
    monkeypatch.setenv('SECURITY_HARDENING','1')
    monkeypatch.delenv('GOOGLE_CLIENT_ID',raising=False)
    monkeypatch.delenv('ADMIN_LOCAL_EMAIL',raising=False)
    for path in ['/api/questions','/api/facets','/api/grand-tests','/api/admin/users','/uploads/private.pdf','/api/future-private-route']:
        response=anonymous.get(path)
        assert response.status_code==401,(path,response.text)
        assert response.headers['cache-control']=='no-store, private'
    assert anonymous.get('/api/auth/config').status_code==200
    assert anonymous.get('/api/health').status_code==200
    for path in ['/docs','/openapi.json','/redoc']:
        assert anonymous.get(path).status_code==404
    assert anonymous.post('/api/auth/student-registration-login',json={}).status_code==403
    assert anonymous.post('/api/auth/mock',json={'email':'admin@example.test'}).status_code==403
    assert student.get('/api/admin/users').status_code==403
    assert admin.get('/api/questions').status_code==200


def test_csrf_headers_body_limit_and_cross_site(clients, monkeypatch):
    admin, student, anonymous=clients
    monkeypatch.setenv('SECURITY_HARDENING','1')
    assert admin.post('/api/grand-tests',headers={'X-CSRF-Token':'wrong'},json={}).status_code==403
    assert anonymous.post('/api/auth/google',headers={'Sec-Fetch-Site':'cross-site'},json={}).status_code==403
    monkeypatch.setenv('SECURITY_MAX_BODY_BYTES','12')
    response=admin.post('/api/grand-tests',json={'oversized':'x'*20})
    assert response.status_code==413
    assert response.headers['x-content-type-options']=='nosniff'
    assert response.headers['x-frame-options']=='DENY'
    assert "frame-ancestors 'none'" in response.headers['content-security-policy']


def test_distributed_quota_is_atomic_and_resets(clients):
    def attempt(_):
        try:reserve('test-concurrent-user','test',5,now=120);return True
        except HTTPException as e:
            assert e.status_code==429
            assert int(e.headers['Retry-After'])>0
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(attempt,range(12)))
    assert sum(results)==5
    reserve('test-concurrent-user','test',5,now=180)


def test_per_user_quota_and_asset_guard(clients,monkeypatch):
    admin, student, anonymous=clients
    monkeypatch.setenv('SECURITY_HARDENING','1')
    assert student.get('/uploads/answer-key.pdf').status_code==403
    monkeypatch.setenv('SECURITY_USER_RPM','1')
    response=student.get('/api/auth/me')
    assert response.status_code==429
    assert response.headers.get('Retry-After')


def test_google_login_requires_audience_configuration(clients,monkeypatch):
    monkeypatch.delenv('GOOGLE_CLIENT_ID',raising=False)
    assert clients[2].post('/api/auth/google',json={'credential':'anything'}).status_code==503


def test_rotation_invalidates_old_tokens_and_keeps_absolute_expiry(clients,monkeypatch):
    admin,_,anon=clients
    monkeypatch.setenv('SECURITY_HARDENING','1')
    old=admin.cookies.get('qb_session')
    csrf=admin.cookies.get('qb_csrf')
    response=admin.post('/api/auth/refresh')
    assert response.status_code==200,response.text
    assert 0 < response.json()['expires_in'] <= 12*3600
    assert admin.cookies.get('qb_session')!=old
    assert admin.cookies.get('qb_csrf')!=csrf
    assert anon.get('/api/auth/me',headers={'Cookie':'qb_session='+old}).status_code==401
    assert admin.get('/api/auth/me').status_code==200


def test_local_admin_password_cannot_elevate_student(clients,monkeypatch):
    _,student,anonymous=clients
    monkeypatch.setenv('APP_ENV','production')
    monkeypatch.setenv('SECURITY_HARDENING','1')
    monkeypatch.setenv('ADMIN_LOCAL_EMAIL','student@example.test')
    monkeypatch.setenv('ADMIN_LOCAL_PASSWORD','only-for-test')
    response=anonymous.post('/api/auth/admin-login',json={'email':'student@example.test','password':'only-for-test'})
    assert response.status_code==403
    assert anonymous.get('/api/auth/me').status_code==401


def test_external_origin_behind_tls_proxy(clients, monkeypatch):
    anonymous=clients[2]
    monkeypatch.setenv('SECURITY_HARDENING','1')
    monkeypatch.setenv('APP_BASE_URL','https://staging.example.test')
    monkeypatch.delenv('GOOGLE_CLIENT_ID',raising=False)
    allowed=anonymous.post('/api/auth/google',headers={'Origin':'https://staging.example.test'},json={'credential':'invalid'})
    assert allowed.status_code==503
    for origin in ['https://evil.example.test','http://staging.example.test','null']:
        rejected=anonymous.post('/api/auth/google',headers={'Origin':origin},json={})
        assert rejected.status_code==403
        assert rejected.json()['detail']=='Origin not permitted'


def test_verified_users_do_not_share_ip_budget(clients,monkeypatch):
    admin, student, anonymous=clients
    monkeypatch.setenv('SECURITY_HARDENING','1')
    monkeypatch.setenv('SECURITY_IP_RPM','1')
    monkeypatch.setenv('SECURITY_AUTH_INGRESS_RPM','2')
    for client in (admin,student):
        assert client.get('/api/auth/me').status_code==200
        assert client.get('/api/auth/me').status_code==200
        assert client.get('/api/auth/me').status_code==429
    # A made-up cookie cannot create a fresh per-account quota.
    assert anonymous.get('/api/auth/me',headers={'Cookie':'qb_session=forged-one'}).status_code==401
    assert anonymous.get('/api/auth/me',headers={'Cookie':'qb_session=forged-two'}).status_code==429


def test_public_routes_keep_ip_limit_with_valid_session(clients,monkeypatch):
    monkeypatch.setenv('SECURITY_HARDENING','1')
    monkeypatch.setenv('SECURITY_IP_RPM','1')
    assert clients[0].get('/api/health').status_code==200
    assert clients[1].get('/api/health').status_code==429
