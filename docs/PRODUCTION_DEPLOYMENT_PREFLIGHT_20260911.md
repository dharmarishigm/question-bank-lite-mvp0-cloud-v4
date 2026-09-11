# Production deployment preflight — 11 September 2026

## Release status

Validated candidate; production promotion pending approval-review clearance for production secret and IAM provisioning. No production traffic, schema, database capacity, or runtime identity changes were made in this rollout. The existing revision remains the rollback target and serves production.

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

## Concrete provisioning awaiting approval

1. Create `qb-production-mfa-key` in Secret Manager with a generated Fernet key. Never log or commit its value.
2. Create `qb-production-runtime-db` in Secret Manager with a generated password and the production Cloud SQL socket URL for a new `qb_production_runtime` database login.
3. Grant `roles/secretmanager.secretAccessor` on these two secrets to `qb-cloud-v4@gen-lang-client-0491787004.iam.gserviceaccount.com`.
4. Create the matching database role with LOGIN, no superuser/CREATEDB/CREATEROLE, no schema creation or Alembic update privileges; grant application DML and sequence access. Verify effective privileges before deployment. Do not change the old role's password or grants.
5. Apply the reviewed additive security table DDL transactionally. Preserve Alembic marker `0020_dqb_document_controls` so the old image can still cold-start. Check active exams and acquire a migration lock before schema work. Do not advance the marker until legacy revisions have been retired in a separately reviewed release.

Automatic approval review rejected the attempted secret/IAM provisioning because explicit approval for those exact changes was required and the matching database user was not yet created. The rejected command did not execute. No workaround was attempted.

The existing service account's legacy permissions remain a separate least-privilege gap: changing the database login alone does not remove the service account's access to the old database secret. Do not describe this release as complete security hardening.

## Remaining rollout after provisioning

- Keep the production OAuth client, storage, backend model configuration and existing URL. Never copy staging OAuth or MFA keys.
- Deploy immutable candidate with zero traffic and a validation tag. Require startup identity/schema/privilege guards. Set `EXPECTED_SCHEMA_REVISION=0020_dqb_document_controls` only with the verified additive schema present.
- Preserve an exact service configuration snapshot and the existing revision. Review autoscaling and connection-pool limits against the unchanged database size; do not claim 2,000-user capacity.
- Check candidate startup, health, API authorization and staff MFA; use bounded smoke checks, never a production load test.
- Promote only after checks pass; monitor errors and latency, restore 100% to the existing revision immediately on regression.
- Verify the public production URL and record the actual revision and traffic percentages. Keep the compatibility schema expansion on rollback; do not delete security data.
- Schedule separate database capacity work and a full 2,000-student, three-hour staging validation before publishing that capacity claim.
