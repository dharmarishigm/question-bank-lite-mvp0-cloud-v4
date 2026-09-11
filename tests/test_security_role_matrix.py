"""Exercise every registered Admin API against unprivileged test sessions."""
import re
import app
from tests.test_programs import clients


def test_all_admin_routes_deny_students_and_require_mfa(clients, monkeypatch):
    admin, student, anon = clients
    monkeypatch.setenv('SECURITY_HARDENING','1')
    monkeypatch.setenv('REQUIRE_STAFF_MFA','1')
    monkeypatch.setenv('SECURITY_USER_RPM','10000')
    monkeypatch.setenv('SECURITY_IP_RPM','10000')
    checked=0
    for path, operations in app.app.openapi()['paths'].items():
        if not path.startswith('/api/admin/'):
            continue
        path=re.sub(r'\{[^}]+\}','999999',path)
        for method in {key.upper() for key in operations if key in {'get','post','put','patch','delete'}}:
            for client, expected, detail in [(student,403,'Administrator access required'),(admin,403,'MFA_REQUIRED'),(anon,401,None)]:
                response=client.request(method,path,json={})
                assert response.status_code==expected,(method,path,response.text)
                if detail:assert response.json()['detail']==detail,(method,path,response.text)
            checked+=1
    assert checked>=10


def test_student_cannot_claim_admin_role_with_headers(clients,monkeypatch):
    monkeypatch.setenv('SECURITY_HARDENING','1')
    response=clients[1].get('/api/admin/users',headers={'X-Role':'ADMIN','X-User-Role':'ADMIN','X-User-Id':'1'})
    assert response.status_code==403
