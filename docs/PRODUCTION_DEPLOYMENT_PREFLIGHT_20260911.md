# Production deployment preflight — 11 September 2026

## Release status

DEPLOYED: 100% production traffic is on `question-bank-cloud-v4-security-20260911b` following explicit user approval of the secret and IAM changes. Live app/health, authentication boundaries and Admin MFA checks passed. Database capacity is unchanged. The previous revision is retained for rollback without a public tag.

The user approved a US$150/month production budget and deployment. This does not establish a billing cap or validate the requested 2,000-student, three-hour workload. Database resizing is excluded from this release because it can interrupt service.

## Evidence

- Production: `question-bank-cloud-v4`, project `gen-lang-client-0491787004`, region `asia-south1`.
- Existing revision: `question-bank-cloud-v4-dqb-20260911114927`.
- Final candidate build: `9279be1b-ee1c-44ce-a37a-8e7a477dd595`, SUCCESS.
- Immutable candidate: `asia-south1-docker.pkg.dev/gen-lang-client-0491787004/qb-security-staging/app@sha256:4b5ba630a907bff5e864cab145428f6fd6b56ee8727d62b1de2b20b476e464ea`.
- Local backend tests: 223 passed. Exam heartbeat browser-independent Node test: passed. Diff whitespace check: passed.
- Build validation against disposable PostgreSQL 17: additive security schema expansion preserves the legacy Alembic marker; subsequent repeated upgrade to head, quota operations, and bounded pool reuse passed.
- On-demand production backup `1789132887230`: SUCCESSFUL, description `pre-security-production-rollout`. Restore rehearsal not performed.
- Read-only production preflight: database `question_bank`, role `question_bank_app`, Alembic `0020_dqb_document_controls`, zero unexpired IN_PROGRESS exam sessions at the time of inspection.
- Existing `security_rate_limits` table present; `security_mfa` and `security_session_state` missing.
- Existing database login has CREATEDB and CREATEROLE, belongs to cloudsqlsuperuser, and can create in public schema. Retain it for the old revision's rollback, but do not use it as the candidate database login.
- Existing DB remains `db-custom-1-3840`, ZONAL, with backups/PITR. Two successful 1,000-student/10-minute staging tests used a larger two-vCPU database; their capacity result does not transfer to this production size.

## Approved provisioning — completed

1. Create `qb-production-mfa-key` in Secret Manager with a generated Fernet key. Never log or commit its value.
2. Create `qb-production-runtime-db` in Secret Manager with a generated password and the production Cloud SQL socket URL for a new `qb_production_runtime` database login.
3. Grant `roles/secretmanager.secretAccessor` on these two secrets to `qb-cloud-v4@gen-lang-client-0491787004.iam.gserviceaccount.com`.
4. Create the matching database role with LOGIN, no superuser/CREATEDB/CREATEROLE, no schema creation or Alembic update privileges; grant application DML and sequence access. Verify effective privileges before deployment. Do not change the old role's password or grants.
5. Apply the reviewed additive security table DDL transactionally. Preserve Alembic marker `0020_dqb_document_controls` so the old image can still cold-start. Check active exams and acquire a migration lock before schema work. Do not advance the marker until legacy revisions have been retired in a separately reviewed release.

The initial secret/IAM provisioning attempt was blocked by automatic approval review and did not execute. The user then explicitly approved those changes. Both secrets were created with version 1 and access granted on those two secrets. Job `qb-prod-security-expand-fvrvv` completed the additive tables, matching restricted role and privilege verification successfully; legacy marker 0020 was preserved. Secret values were never printed or committed.

The existing service account's legacy permissions remain a separate least-privilege gap: changing the database login alone does not remove the service account's access to the old database secret. Do not describe this release as complete security hardening.

## Rollout procedure and future capacity work

- Keep the production OAuth client, storage, backend model configuration and existing URL. Never copy staging OAuth or MFA keys.
- Deploy immutable candidate with zero traffic and a validation tag. Require startup identity/schema/privilege guards. Set `EXPECTED_SCHEMA_REVISION=0020_dqb_document_controls` only with the verified additive schema present.
- Preserve an exact service configuration snapshot and the existing revision. Review autoscaling and connection-pool limits against the unchanged database size; do not claim 2,000-user capacity.
- Check candidate startup, health, API authorization and staff MFA; use bounded smoke checks, never a production load test.
- Promote only after checks pass; monitor errors and latency, restore 100% to the existing revision immediately on regression.
- Verify the public production URL and record the actual revision and traffic percentages. Keep the compatibility schema expansion on rollback; do not delete security data.
- Schedule separate database capacity work and a full 2,000-student, three-hour staging validation before publishing that capacity claim.

## Release checks and configuration

- Final runtime: 2 vCPU, 2 GiB; concurrency 10; minimum instances 0; maximum instances 6; database pool size 5 per instance. Database remains 1 vCPU / 3.75 GiB, ZONAL. No vertical resize or HA change.
- Preserve always-allocated CPU (`cpu-throttling=false`) for existing background document/exam workflows; minimum zero permits idle scale-down, but background work is still not a durable queue. The first zero-traffic revision used throttling, was canaried briefly without observed server errors, then was replaced with revision suffix `b` to preserve background behavior.
- Startup identity/schema/privilege guards passed. All original production environment entries except DATABASE_URL, and the existing volume mounts, were checked for preservation. Added flags/identity guards and MFA secret are intentional.
- Final candidate smoke checks: app and public health 200; unauthenticated auth/me and Admin API 401; docs and OpenAPI 404; production OAuth client unchanged; valid Admin password login requires MFA; Admin API without MFA returns 403 MFA_REQUIRED; foreign Origin rejected 403. Temporary test sessions were revoked. No MFA enrolment or secret reset was performed for a real user.
- Successful MFA completion and Student browser workflows were previously checked in staging; this production smoke test did not enrol a real account or run a synthetic exam.
- These bounded checks are not a full penetration test or production capacity validation.

## Emergency rollback

Run only if release behavior regresses:

```sh
gcloud run services update-traffic question-bank-cloud-v4 \
  --project=gen-lang-client-0491787004 --region=asia-south1 \
  --to-revisions=question-bank-cloud-v4-dqb-20260911114927=100
```

The prior revision retains its prior database credentials and startup behavior. Keep the additive security tables and marker 0020 when rolling back; do not drop tables or restore the database just to change application traffic. The old revision lacks the new security protections.

## Final production verification

- `https://meritiqra.com/app`: HTTP 200.
- `/api/health`: HTTP 200 and revision `question-bank-cloud-v4-security-20260911b`.
- Live-domain authentication, Admin MFA and foreign-origin smoke checks passed, including revoking the temporary session.
- Cloud Run: 100% to the final revision; removed `release-check` and `security-validate` tags so the old unprotected revision has no temporary public URL. The revision itself remains available for rollback.
- No server errors appeared in the final revision's bounded rollout log check. This observation is not ongoing monitoring or a reliability SLA.
- Completed one-time jobs `qb-prod-security-expand` and `qb-prod-release-preflight` deleted after success. Backups, secrets and database tables retained.
- Staff may need to enrol production MFA separately from staging. Do not reuse or disclose the staging setup key.
- No live load test, database resize or HA conversion was performed. The full 2,000-student/three-hour workload remains unvalidated. The US$150 budget is an authorization, not a provider-enforced spending limit.
