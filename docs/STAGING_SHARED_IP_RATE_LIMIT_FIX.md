# Staging: shared-IP exam rate-limit fix

## Problem and change

The original 1,000-user load attempt stopped at 464 active users with HTTP 429. The boundary charged every authenticated student from one perceived IP to a shared 1,200-request/minute bucket. This also updated one PostgreSQL counter row for all those requests, introducing a possible contention point.

Private requests now resolve the active, unexpired session before selecting their ingress quota principal. Verified accounts receive independent ingress budgets (default 1,200/minute) as well as the existing operation quotas. Public requests and invalid/absent sessions retain the IP budget. Browser-supplied user IDs, role headers, and forged session cookies cannot select a user quota. The validated identity is cached only within that request.

No MFA, CSRF, session expiry, role, object-access, or operation-limit checks were removed. Numeric quota defaults were not increased. This does not replace edge DDoS/WAF protection: many valid accounts still need aggregate resource controls and monitoring. Staging retains its existing three-instance cap, concurrency 20, and database pool size five per instance.

## Validation

- 213 backend tests passed, including independent budgets for users sharing an IP, invalid cookies retaining IP limits, public routes retaining IP limits even with valid sessions, MFA, and Admin endpoint authorization.
- PostgreSQL build checks passed.
- Deployed only to staging revision `qb-security-staging-00003-sg9`.
- Rerun execution: `qb-security-staging-load1000-nz7hm`.
- No production changes.

## Rerun result

The rerun reached 1,000 active users. Start p95 improved to 382 ms, but sustained load failed: 24,225 HTTP 200 responses and 19 Cloud Run HTTP 429 responses (no available instance). Read p95 was 8,854 ms; save p95 was 7,984 ms. No exams completed before automatic abort. Synthetic sessions were revoked. The quota fix passed its targeted test; end-to-end 1,000-user capacity did not pass.
