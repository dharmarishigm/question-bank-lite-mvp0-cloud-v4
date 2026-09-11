"""Default-deny boundary and cross-instance quotas for the security candidate.

Route handlers remain responsible for role and object-level authorization.
No JWT in browser storage: existing revocable HttpOnly sessions are tokens.
"""
import hashlib
import logging
import os
import re
import time
from contextlib import closing
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

SCHEMA = '''CREATE TABLE IF NOT EXISTS security_rate_limits (
 id INTEGER PRIMARY KEY AUTOINCREMENT, bucket TEXT NOT NULL UNIQUE,
 hits INTEGER NOT NULL, expires_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_security_rate_expiry ON security_rate_limits(expires_at);'''

def enabled():
    return os.getenv('SECURITY_HARDENING', '1' if os.getenv('K_SERVICE') else '0') == '1'

# Method-specific, intentionally small pre-authentication surface.
PUBLIC = {
    ('GET', '/api/health'), ('GET', '/api/auth/config'),
    ('POST', '/api/auth/google'), ('POST', '/api/auth/admin-login'),
    ('GET', '/api/public/exams'), ('GET', '/api/public/programs'),
    ('GET', '/api/enquiries/challenge'), ('POST', '/api/enquiries'),
    ('GET', '/api/mobile/config'), ('POST', '/api/mobile/auth/start'),
    ('POST', '/api/mobile/auth/exchange'),
}

def public(method, path):
    return (method, path) in PUBLIC or (method in {'GET', 'POST'} and bool(re.fullmatch(r'/api/register/exam/[A-Za-z0-9_-]{16,200}', path)))

def quota_group(method,path):
    if re.search(r'/sessions/\d+/(answers|submit|security-events)',path):return 'exam-write',600
    if method not in {'GET','HEAD','OPTIONS'} and re.search(r'(digitize|digitise|generate|explain|/ocr|/pdf/parse)',path):return 'expensive',12
    if method not in {'GET','HEAD','OPTIONS'} and ('/upload' in path or path.endswith('/documents')):return 'upload',20
    if method not in {'GET','HEAD','OPTIONS'} and '/admin/' in path:return 'admin-write',60
    if '/payments' in path:return 'payment',20
    return 'api',int(os.getenv('SECURITY_USER_RPM','300'))

def reserve(principal, group, limit, now=None):
    """Atomic fixed-minute counter shared by all Cloud Run instances.

Stable per-principal keys avoid creating a row for every time window.
Expired rows are pruned in small batches; no credentials or IPs are stored.
"""
    from platform_api import db
    now = time.time() if now is None else now
    end = (int(now // 60) + 1) * 60
    key = hashlib.sha256((group + ':' + principal).encode()).hexdigest()
    with closing(db()) as conn:
        row = conn.execute('''INSERT INTO security_rate_limits(bucket,hits,expires_at) VALUES(?,1,?)
          ON CONFLICT(bucket) DO UPDATE SET
          hits=CASE WHEN security_rate_limits.expires_at<=? THEN 1 ELSE security_rate_limits.hits+1 END,
          expires_at=CASE WHEN security_rate_limits.expires_at<=? THEN excluded.expires_at ELSE security_rate_limits.expires_at END
          RETURNING hits,expires_at''', (key, end, now, now)).fetchone()
        if int(now) % 60 == 0:
            conn.execute('DELETE FROM security_rate_limits WHERE id IN (SELECT id FROM security_rate_limits WHERE expires_at<? LIMIT 100)', (now-3600,))
        conn.commit()
    if row['hits'] > limit:
        raise HTTPException(429, 'Request limit reached. Please retry shortly.', headers={'Retry-After':str(max(1, int(row['expires_at']-now)+1))})

def authorize(request):
    from platform_api import _auth, current_user
    path, method = request.url.path, request.method
    # Ignore client-supplied forwarding headers; the deployment must retain a
    # trusted proxy configuration. Edge abuse prevention is additionally needed.
    host = request.client.host if request.client else 'unknown'
    # Public/invalid-session traffic stays IP-limited. Verified accounts get
    # separate budgets so a school NAT cannot merge every student's quota.
    # Never derive a principal from an unverified cookie or browser header.
    user = None
    if not public(method, path) and request.cookies.get('qb_session'):
        try:
            user = current_user(request.cookies.get('qb_session'))
        except HTTPException:
            pass
    principal = 'user:'+str(user['id']) if user is not None else 'ip:'+host
    reserve(principal, 'ingress', int(os.getenv('SECURITY_AUTH_INGRESS_RPM', '1200')) if user is not None else int(os.getenv('SECURITY_IP_RPM', '1200')))
    if user is not None:
        request.state.authenticated_user = user
    if path in {'/docs','/redoc','/openapi.json','/docs/oauth2-redirect'}:
        raise HTTPException(404, 'Not found')
    if path in {'/api/auth/mock','/api/auth/bootstrap-admin','/api/auth/student-registration-login'}:
        raise HTTPException(403, 'Use verified Google sign-in')
    if public(method, path):
        if method == 'POST':
            reserve('ip:'+host, 'public-write', 20)
        return
    user = _auth(request, method not in {'GET','HEAD','OPTIONS'})
    if os.getenv('REQUIRE_STAFF_MFA')=='1':
        from security_mfa import state
        status=state(request,user)
        if status['mfa_required'] and path not in {'/api/auth/me','/api/auth/logout','/api/auth/mfa/setup','/api/auth/mfa/verify'}:
            raise HTTPException(403,'MFA_REQUIRED')
    request.state.security_user = user
    group,limit=quota_group(method,path)
    reserve('user:'+str(user['id']), group,limit)
    if path.startswith('/api/admin/') and user['role'] != 'ADMIN':
        raise HTTPException(403, 'Administrator access required')
    if path.startswith('/uploads/'):
        if user['role'] != 'ADMIN':
            authorize_asset(path, user)

def authorize_asset(path, user):
    """Only scoped raster evidence is available outside the Admin library."""
    import json
    from platform_api import db
    if not re.fullmatch(r'/uploads/[A-Za-z0-9_-]+\.(?:png|jpg|jpeg|webp)', path, re.I):
        raise HTTPException(403, 'Use the authorized document viewer')
    def references(value):
        if isinstance(value, str):return value==path
        if isinstance(value, dict):return any(references(v) for v in value.values())
        if isinstance(value, list):return any(references(v) for v in value)
        return False
    with closing(db()) as conn:
        if user['role']=='OPERATOR':
            from grand_tests import workspace
            for row in conn.execute('SELECT id,questions_json FROM grand_tests WHERE created_by=? AND questions_json LIKE ?', (user['id'], '%'+path+'%')).fetchall():
                if references(json.loads(row['questions_json'])):
                    workspace(conn,row['id'],user)
                    return
        else:
            for row in conn.execute('SELECT question_set_json FROM exam_sessions WHERE user_id=? AND question_set_json LIKE ?', (user['id'], '%'+path+'%')).fetchall():
                # Answers and explanations must never grant access during an exam.
                questions=json.loads(row['question_set_json'] or '[]')
                safe=[{k:q.get(k) for k in ('statement','options','visual_assets','content_blocks')} for q in questions]
                if references(safe):return
    raise HTTPException(403, 'Document access not granted')

class SecurityBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not enabled():
            return await self.app(scope, receive, send)
        request = Request(scope)
        protected = request.url.path.startswith(('/api/', '/uploads/')) or request.url.path in {'/docs','/redoc','/openapi.json','/docs/oauth2-redirect'}
        async def secure_send(message):
            if message['type'] == 'http.response.start':
                headers = list(message.get('headers', []))
                additions = {
                    b'x-content-type-options': b'nosniff', b'x-frame-options': b'DENY',
                    b'referrer-policy': b'same-origin',
                    b'permissions-policy': b'geolocation=(), payment=(), usb=()',
                    b'content-security-policy': b"object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
                }
                if os.getenv('K_SERVICE') or request.url.scheme == 'https':
                    additions[b'strict-transport-security'] = b'max-age=31536000'
                if protected:
                    additions[b'cache-control'] = b'no-store, private'
                headers = [(k,v) for k,v in headers if k.lower() not in additions]
                message['headers'] = headers + list(additions.items())
            await send(message)
        try:
            if protected:
                # Cross-site cookie requests must not reach login or mutation handlers.
                if request.method not in {'GET','HEAD','OPTIONS'} and request.headers.get('sec-fetch-site') == 'cross-site':
                    raise HTTPException(403, 'Cross-site request rejected')
                origin=request.headers.get('origin')
                if request.method not in {'GET','HEAD','OPTIONS'} and origin and origin.rstrip('/')!=(os.getenv('APP_BASE_URL') or str(request.base_url)).rstrip('/'):
                    raise HTTPException(403, 'Origin not permitted')
                await run_in_threadpool(authorize, request)
                limit = int(os.getenv('SECURITY_MAX_BODY_BYTES', str(32*1024*1024)))
                length = request.headers.get('content-length')
                if length and (not length.isdigit() or int(length)>limit):
                    raise HTTPException(413, 'Request body exceeds the permitted size')
                received = 0
                async def bounded_receive():
                    nonlocal received
                    message = await receive()
                    received += len(message.get('body', b''))
                    if received > limit:
                        raise HTTPException(413, 'Request body exceeds the permitted size')
                    return message
        except HTTPException as exc:
            return await JSONResponse({'detail':exc.detail}, status_code=exc.status_code, headers=exc.headers)(scope, receive, secure_send)
        except Exception:
            logging.getLogger(__name__).exception('Security boundary or protected request failed')
            return await JSONResponse({'detail':'Service temporarily unavailable'}, status_code=503)(scope, receive, secure_send)
        return await self.app(scope, bounded_receive if protected else receive, secure_send)
