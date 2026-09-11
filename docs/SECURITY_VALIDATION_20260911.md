# Security validation — 11 September 2026

Target: isolated staging revision `qb-security-staging-00002-fl9`.
No production changes, authenticated production requests, or load tests were performed.

## Passed

- Existing backend suite: 209 tests passed.
- Added role matrix: two tests passed. Every registered `/api/admin/` method rejects Student sessions (403), Admin sessions without MFA (403 MFA_REQUIRED), and anonymous requests (401). Client-supplied role headers do not grant Admin access.
- Local Chromium with disposable accounts: Student Admin navigation hidden and Admin API denied; Admin redirected to MFA; valid TOTP grants access; subsequent Google login requires MFA again. Google identity verification is mocked only in this local test server.
- Existing tests cover CSRF, origin restrictions, atomic quota counters/reset, session rotation invalidating old tokens, idle expiry, MFA replay rejection, prevention of repeat enrollment, and Operator ownership.
- Live staging probes: unauthenticated Admin users API, identity API, DigitalQBank API, question API, and PDF path all return 401. API docs and OpenAPI return 404. Health returns 200. TLS verification succeeds; responses include HSTS, nosniff and DENY frame headers.
- Read-only deployed configuration confirms MFA and hardening enabled, staging runtime identity, staging database secret reference, staging bucket, and staging public origin.

## Reproduce locally

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m tests.validate_security_roles_ui
```

The browser script binds localhost:8063 and uses a temporary database. It requires permission to run a local server/browser. It does not use real user credentials or MFA seeds.

## Limits and remaining work

Authenticated role/MFA assertions were run locally against the application code, not by borrowing the user's live Google sessions. Live staging checks were unauthenticated and configuration-only. A hidden menu alone is not the security boundary; the API denial tests are essential. Public static application HTML may be downloadable without granting access to private data.

This is not a complete penetration test, dependency/container vulnerability audit, exhaustive object-level authorization review, or capacity certification. Edge/WAF deployment, payment integration review, malware scanning, MFA recovery, and 10,000-user load validation remain separate work. No production promotion is authorized by these results.
