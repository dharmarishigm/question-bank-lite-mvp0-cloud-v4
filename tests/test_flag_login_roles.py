from unittest.mock import patch
from tests.test_programs import clients


def test_google_role_choice_does_not_grant_permissions(clients):
    admin, student, anon = clients
    identity = {'sub':'new-flag-google', 'email':'flag-login@example.test', 'email_verified':True, 'name':'FLAG learner'}
    with patch('google.oauth2.id_token.verify_oauth2_token', return_value=identity):
        for role in ('ADMIN','FLAG'):
            assert anon.post('/api/auth/google',json={'credential':'mock','login_role':role}).status_code==403
        assert admin.put('/api/flag/members',json={'email':identity['email']}).status_code==200
        assert anon.post('/api/auth/google',json={'credential':'mock','login_role':'FLAG'}).status_code==200
        assert anon.get('/api/flag/access').json()['allowed'] is True
        assert anon.get('/api/flag/members').status_code==403
        assert admin.put('/api/flag/members',json={'email':identity['email'],'active':False}).status_code==200
        assert anon.get('/api/flag/materials').status_code==403
