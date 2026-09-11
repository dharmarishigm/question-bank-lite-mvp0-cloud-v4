# Security hardening and isolated-traffic validation playbook

## Incident correction — preview disabled

Recovery completed on 11 September 2026:

- `https://meritiqra.com/app` returned HTTP 200; `/api/health` identified the
  original live revision `question-bank-cloud-v4-dqb-20260911114927`.
- Production retains 100% traffic on that exact revision.
- The `security-preview` tag and faulty security revision were removed.
- One-time recovery execution `qb-restore-migration-20260911-pndrx` completed
  successfully; its job definition was removed to prevent accidental reruns.
- A zero-traffic copy of the previous image, `question-bank-cloud-v4-dqb-recovery-20260911`,
  replaced the latest deployment template so Cloud Run permitted deletion of
  the faulty preview. It did not replace the serving revision.

The shared-database preview below was unsafe and has been disabled. Its startup
advanced Alembic to `0021_security_rate_limits`, preventing the previous production
image from cold-starting because that image only knows migrations through 0020.
Zero HTTP traffic did **not** provide database isolation. Recovery restores only
the migration version marker to 0020 and retains all tables and application data.

Do not reuse the historical preview URL below. Future security validation must
use a separate Cloud Run service, separate database secret targeting a separate
database, separate storage bucket, and separate runtime identity. The preview
deployment script now refuses the production service and shared resource
references. Migration rollout tests must include cold-starting the previous image
after any database change. The historical deployment evidence below is retained
for the incident record, not as a statement that the preview remains available.

## Deployed preview and evidence

- [Open security validation version](https://security-preview---question-bank-cloud-v4-e27n2q2rxa-el.a.run.app/app)
- Preview revision: `question-bank-cloud-v4-security-20260911121038`, **0% production traffic**.
- Existing live revision: `question-bank-cloud-v4-dqb-20260911114927`, **100% traffic unchanged**.
- Cloud Build `d5265c1f-be02-49f1-b7a7-26cac9768079`: SUCCESS, including PostgreSQL migration and quota increment/rejection/reset validation.
- Full backend suite: **206 passed**; dependency deprecation warnings remain.
- Browser workflow with `VALIDATE_SECURITY=1`: passed Admin/Operator DigitalQBank,
  review/save, exam publication and Upload & Digitise regression on desktop/mobile.
  Google verification and AI extraction were mocked locally; real Google origin
  configuration and live authenticated workflows remain for user acceptance.
- Deployed candidate `/api/health`: healthy; anonymous questions, workspaces and
  Admin API requests: 401. The deployment script compared pre/post live allocations.

Sign in afresh on the preview hostname. Production-domain cookies do not transfer
to this hostname. Use disposable test records because the database is shared.

## Goal and release rule

Harden MeritIQra without promoting unvalidated security changes to production.
Build an immutable image from the current serving image, validate PostgreSQL
migrations, deploy a tagged `security-preview` revision with **zero production
traffic**, and verify the original traffic allocation is unchanged. Do not run
`scripts/deploy_gcp.sh` for this review: it promotes traffic. Use
`bash scripts/deploy_security_preview.sh`.

A tagged revision is not a separate test environment. It shares Cloud SQL,
storage, service-account permissions and external AI billing with production.
Use clearly named test records, never mass deletion or load tests on this URL.
The additive migration creates only the security counter table; it does not
rewrite application records or revoke existing production sessions.

## Implemented controls

| Finding | Change | Verification |
|---|---|---|
| Legacy API authentication depended on configured login options | Security middleware defaults on in Cloud Run; private `/api/` routes require a valid server-side session, including future routes | Missing/invalid session returns 401 even without login configuration |
| Sparse, per-process throttling | Atomic database-backed minute counters shared across instances; IP ingress, public writes, authenticated-user and expensive-action limits | Concurrent reservation test admits exactly the allowed count; 429 includes Retry-After |
| Registration details were accepted as credentials | Candidate rejects DOB/phone sign-in, mock login and bootstrap routes | Regression tests; use verified Google identity |
| Local Admin login accepted a matching non-Admin/inactive database account | Require ACTIVE and ADMIN at login | Existing suite plus explicit privilege regression |
| Missing OAuth audience configuration could reach token validation | Refuse Google login when client ID is absent | 503 configuration failure test |
| Cookie security depended only on a URL variable | Secure cookies forced in Cloud Run; session remains HttpOnly, SameSite=Lax | Cookie configuration checked; server-side session expiry and revocation retained |
| Session rotation unavailable | POST `/api/auth/refresh`, with existing session + CSRF, atomically replaces session and CSRF tokens; absolute expiry is preserved | Old token fails after rotation; repeated use cannot rotate again |
| Uneven CSRF enforcement | Default boundary checks CSRF on private writes and rejects browser cross-site writes | Invalid CSRF and cross-site tests |
| Unbounded request bodies | 32 MiB body ceiling, including receive-stream counting | Oversized request rejected before handler work |
| Direct upload paths exposed too broadly | Admin raw-file access; non-Admin raster assets require references in owned authorized workspaces or safe exam-snapshot fields | Unauthorized raw answer-key request denied; scoped viewer routes retain their own checks |
| Public API schema and inconsistent browser headers | Disable docs/schema on candidate; nosniff, frame denial, referrer policy, limited CSP, HSTS on HTTPS, no-store for protected data | Header and docs tests |

`SECURITY_HARDENING=1` enables the boundary locally and explicitly on the preview.
It is on by default when `K_SERVICE` is present. Development unit tests can run
without the new boundary; separate boundary tests explicitly enable it.

## Token and identity policy

An HttpOnly random session cookie **is a token**. Keep the existing verified
Google OpenID Connect identity exchange and hashed, revocable database sessions.
Do not introduce long-lived JWTs in localStorage or add a static browser API key:
neither protects a browser-facing API. The session lifetime remains 12 hours;
refresh rotates tokens but does not extend this absolute limit. Refresh is an
available API, not an automatic background browser refresh loop.

Login, authentication configuration, minimal health, public catalog, enquiries,
mobile PKCE start/exchange and token-bearing exam invitation routes need narrowly
defined pre-authentication access. They have method-specific allowlisting and
rate limits. This is the necessary exception to “no API without a token”; all
business-private APIs require authentication and retain handler-level role and
object ownership checks. Public endpoint inventory is in `security_boundary.py`.

The preview blocks weak student registration-detail sign-in. Students must use
their verified Google email. For Google login on the tagged hostname, add its
origin to the existing OAuth client’s authorized JavaScript origins if needed.
This release does not change that external OAuth configuration. Existing local
Admin login remains available for preview validation; enforced staff MFA and
retirement of password fallback are still rollout requirements.

## Rate limits and abuse protection

Defaults: 1,200 ingress requests/IP/minute; 20 public writes/IP/minute;
300 authenticated API requests/user/minute; 12 expensive mutation requests/user/minute.
The fixed-window algorithm can admit a burst at a window boundary. Request
principals are hashed; raw session tokens are never counter keys or log fields.
Counters expire logically and are pruned in bounded batches.

These are application safety limits, **not an Internet DDoS shield**. Trusted
proxy handling must preserve the actual client IP. Do not trust arbitrary
X-Forwarded-For input. Campus NAT can share one IP; tune limits with real usage.
Before production promotion, put an external HTTPS load balancer and Cloud Armor
in front, test WAF rules in preview, then restrict Cloud Run ingress to internal
and load-balancing traffic to prevent bypass. That ingress change would remove
the requested direct validation URL and affect live traffic, so it is not applied
to the shared service in this release. New expensive endpoints must explicitly
join the expensive-action policy; the general API quota still applies to them.

## GCP observations, 11 September 2026

- Dedicated runtime account: `qb-cloud-v4@gen-lang-client-0491787004.iam.gserviceaccount.com`.
  Observed project roles: Cloud SQL client, Vertex AI user, Document AI API user.
- `DATABASE_URL`, local Admin email/password use Secret Manager references.
- Bucket `gen-lang-client-0491787004-qb-v4-data`: uniform bucket-level access on,
  public-access prevention enforced.
- Cloud SQL: encrypted-only connections, backups and PITR enabled; ZONAL,
  `db-custom-1-3840`.
- Live Cloud Run: 2 CPU, 2 GiB, concurrency 160, maximum 10 instances, ingress all.
- Preview concurrency is 40 to bound validation pressure; this is not a scale claim.

Do not blanket-apply the existing Terraform state during this rollout. Review a
plan first. Next infrastructure work: separate staging DB/bucket/service account,
Cloud Armor/load balancer, regional DB HA, measured connection budgeting,
secret rotation procedure, audit-log retention/alerts, restore exercise and
workload-specific IAM. Separate build/deploy identity from runtime identity.
Never commit Terraform state or secret values; current ignore rules exclude them.
This audit did not certify every IAM binding, dependency or project resource.

## 10,000 concurrent users: mandatory capacity gate

Ten thousand logged-in users is not ten thousand requests at once. Define a
workload: sign-in ramp, answer autosaves, exam reads/submission bursts, PDF traffic,
and a separately throttled AI queue. The current one-vCPU DB and ten-instance
cap have **not** been demonstrated to support that target.

Before changing production capacity:

1. Create isolated staging resources with representative anonymized data.
2. Move OCR/AI/background work to durable Cloud Tasks/Pub/Sub jobs with retries,
   idempotency and per-user budgets; isolate exam submission from generation.
3. Add bounded DB pooling/PgBouncer and establish a connection budget across all
   instances. Evaluate Redis/Memorystore for high-volume shared quotas; current
   SQL counters and connection-per-call adapter need measured load validation.
4. Test 100, 1,000, 5,000 then 10,000 concurrent users, including NAT and failure
   cases; measure p95/p99 latency, error rate, DB saturation and billing.
5. Verify no lost/duplicated answers or submissions, recovery after instance
   termination, and sustained operation for the full exam duration. Set SLOs and
   resource/budget alerts before increasing instance limits.

No load test against production or the shared-data preview is authorized by this
playbook. Use a separately provisioned staging environment for that test.

## Payment integration requirements

No payment gateway is added or activated in this release. Use provider-hosted
checkout/tokenization; never collect/store PAN or CVV in this app. Create orders
and amounts server-side, bind them to authenticated users, use idempotency keys,
and validate entitlement changes in a transaction. Verify webhook signatures
over raw request bytes with a timestamp tolerance and deduplicate event IDs.
Only verified webhooks establish payment state; browser redirects do not.
Reconcile asynchronously and audit refunds, adjustments and subscription changes.
Use separate test/live keys in Secret Manager and require staff step-up auth for
refunds. Document applicable PCI scope with the provider before launch; this
application is not claimed PCI compliant.

## Validation and acceptance checklist

- Run full pytest suite and security-specific tests; verify real PostgreSQL
  upgrade and repeated upgrade in Cloud Build.
- Open preview `/app` in a separate browser profile. Sign in as Admin, Operator,
  and enrolled Student. Confirm roles cannot read another user’s objects, source
  documents or unreleased answers. Exercise question images and FLAG content.
- Validate DigitalQBank review/save, Program dropdown, exam start/answer/submit,
  registrations, proctor workflow and logout; use disposable test records.
- Verify anonymous private requests return 401, wrong-role requests 403,
  missing CSRF 403, quota 429, and expired/revoked tokens 401.
- Check browser console for CSP issues and Google origin configuration. Current
  CSP is only a baseline; migrating inline scripts to nonces and adopting a strict
  script policy remain necessary XSS work.
- Add an independent penetration test and OWASP ASVS assessment before declaring
  production-grade security. Include upload malware/polyglot scanning, parser
  sandboxing, dependency/container vulnerability scanning and authorization
  coverage for every route. Those controls are not certified by passing pytest.
- Promotion requires a separate explicit request after validation. Keep the
  previous live revision available for rollback. Never run a destructive downgrade
  against the shared database during rollback.

## Standards and primary references

- [OWASP session management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
- [OWASP authentication](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- [OWASP ASVS mapping](https://cheatsheetseries.owasp.org/IndexASVS.html)
- [Google Cloud Armor rate limiting](https://docs.cloud.google.com/armor/docs/configure-rate-limiting)

This playbook records implemented controls and remaining gates. It is not a
claim that every industry security standard has been met or that the system is
unbreakable.
