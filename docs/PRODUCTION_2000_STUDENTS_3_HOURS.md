# Production candidate: 2,000 students, three-hour exams

## Release status and evidence

This is a production deployment candidate and validation plan, not a claim that 2,000 students for three hours have passed. Do not promote it merely because the image builds.

Two 1,000-student, ten-minute exams passed on staging: 86,000 successful requests, 40,000 persisted answers, 2,000 correctly scored submissions, zero request failures. Those tests used a two-vCPU database and up to six app instances. Prior 2,000-user testing failed with a saturated one-vCPU database and unavailable Cloud Run instances. The three-hour test described here has not been run.

Production resources, database and traffic were not modified to prepare this candidate.

## Artifacts

- `Dockerfile.production`: immutable runtime base; explicit source overlays; no startup migration.
- `scripts/check_production_runtime.py`: read-only, fail-closed environment, actual DB identity, schema and database privilege checks.
- `config/production-exam-profile.json`: proposed resource limits and acceptance criteria.
- `scripts/stage_production_build.py`: source-only build context using the isolated build account/repository, not production credentials.
- `scripts/load_staging_exam_2000_3h.py`: bounded staging-only synthetic three-hour validation scenario, not invoked by deployment.
- `docs/CUSTOMER_PERFORMANCE_VALIDATION_REPORT_20260911.md`: historical measured evidence and limitations.

## Architecture and scaling

Use stateless Cloud Run instances with PostgreSQL as the authoritative store for sessions, saved answers, exam timing, scores, audit and shared quotas. Keep document files in the reviewed private bucket. Do not rely on local filesystem state, process memory, sticky sessions, or background work surviving instance termination.

Cloud Run automatically scales horizontally based on request concurrency and CPU demand, and can scale the web tier to zero with a minimum of zero. Its autoscaler does not increase the CPU or RAM of an existing instance. Vertical application changes create a new revision. Cloud SQL CPU/RAM resizing is a controlled operation which can interrupt connections; never trigger it automatically during an active exam. SQL storage auto-growth is separate and does not imply compute autoscaling or automatic shrinkage.

Sources: https://docs.cloud.google.com/run/docs/about-instance-autoscaling and https://docs.cloud.google.com/sql/docs/postgres/instance-settings.

### Proposed profile — validate before use

| Setting | Proposed target |
|---|---|
| Cloud Run CPU / memory | 2 vCPU / 2 GiB per instance |
| Worker processes | 1 per instance |
| Request concurrency | 10 per instance |
| Minimum instances outside exam window | 0, accepting cold starts |
| Minimum instances before/during scheduled exam | 4, pre-warmed 15–30 minutes before start |
| Maximum instances | 12, subject to quota and DB connection budget |
| DB pool | 5 connections per instance, zero overflow |
| Cloud SQL starting proposal | 4 vCPU / 15 GiB, regional HA; benchmark before choosing final size |
| Connection budget | Allow at least 150 for two overlapping revisions, jobs and operational reserve; verify actual max_connections |
| HTTP request timeout | 300 seconds, not three hours |
| Exam duration | 180 minutes in the exam configuration |

The exam consists of many short requests; do not hold one HTTP connection open for three hours. Do not resize the database back down until all active exams have ended and the grace period has passed. Cloud SQL does not scale to zero like Cloud Run; its idle baseline cost remains.

Horizontal scale ceilings, database capacity, worker count and pool size must be reviewed together. Two full-size revisions can temporarily double DB connections. Never raise app limits alone in response to database saturation.

## Three-hour session behavior

The app's absolute login lifetime is 12 hours. Idle expiration remains one hour. During an active exam the browser checks its session once per minute without extending the absolute expiry. This prevents an active reader from appearing idle merely because no answer was saved recently. Browser sleep/offline periods can still require reauthentication; server time remains authoritative.

Student sessions are not subject to staff MFA step-up. Staff MFA remains required. Do not disable security checks to achieve a load-test pass. Test reauthentication, refresh, expiry and recovery across the complete duration. Validate the heartbeat overhead with real browsers; the synthetic API scenario alone does not test it.

Synchronous answer persistence runs in a worker thread rather than blocking the event loop. Saving still requires ownership and CSRF checks, records audit, and commits before success is returned. An interrupted save must not be represented as persisted in the UI. Do not describe unverified offline/retry behavior as guaranteed.

## Build

From the repository root:

```bash
python3 scripts/stage_production_build.py > /tmp/qb-production-build-path
BUILD_CONTEXT=$(cat /tmp/qb-production-build-path)
gcloud builds submit "$BUILD_CONTEXT" \
  --config="$BUILD_CONTEXT/cloudbuild.json" \
  --gcs-source-staging-dir=gs://gen-lang-client-0491787004-security-staging-builds/source \
  --project=gen-lang-client-0491787004
```

Resolve and retain the resulting immutable image digest. Never deploy a mutable tag as release evidence. The build runs disposable PostgreSQL migration checks; it never contacts production DB. Retain the commit, digest, test reports and rollback digest together. Do not use the legacy default Dockerfile for this candidate: it runs Alembic at web startup.

## Production preflight — required before any deployment

1. Export current Cloud Run configuration and weighted revision traffic. Resolve the current image digest and retain it as rollback evidence.
2. Confirm project, region, service, actual SQL database/user/instance, bucket and runtime identity. Do not reuse staging OAuth, MFA key, database URL, users or storage.
3. Configure a separate production runtime DB role with DML/sequence permissions and read-only Alembic marker access; no schema CREATE, superuser, CREATEDB or CREATEROLE privileges. Use a separate migration identity. Check inherited role membership as well as direct grants.
4. Confirm backups, PITR and a restore rehearsal. Regional HA/failover is recommended for the target, but does not replace restore testing.
5. Review database migration compatibility with every revision that may serve or cold-start. Previous production images knew only revision 0020; advancing the marker to 0022 can break their startup. A zero-traffic revision does not isolate a shared database. Resolve that compatibility before running ANY migration.
6. Use an explicit one-shot migration job with exclusive execution/advisory locking and no automatic retry. Review rollback as application rollback plus forward-compatible schema, not destructive downgrade. No startup schema mutation.
7. Enable production OAuth for the actual origin, configure a unique MFA encryption secret and controlled recovery process, and enroll verified administrators. Never log keys or credentials.
8. Ensure appropriate private bucket permissions, Secret Manager references, Cloud SQL connector permissions and no production admin privileges on the app service account.
9. Review unresolved launch gaps: dependency/container scans, runtime root user hardening, edge/WAF and trusted proxy behavior, secure upload/quarantine, durable background queues, MFA recovery, restore/failover tests and full penetration assessment. This build alone does not certify those items.
10. Obtain the full load-test acceptance evidence below and reconcile the test budget. The previous US$20 testing authorization is not an unlimited production hosting budget.

## Required runtime environment

Set `APP_ENV=production`, `QB_SCHEMA_MANAGED=1`, `SECURITY_HARDENING=1`, `REQUIRE_STAFF_MFA=1`, `DB_POOL_ENABLED=1`, `DB_POOL_SIZE=5`.

Provide `DATABASE_URL` and `MFA_ENCRYPTION_KEY` only via production Secret Manager references. Configure the actual production `GOOGLE_CLIENT_ID`, `ADMIN_EMAILS`, HTTPS origin `APP_BASE_URL`, private `GCS_DATA_BUCKET`, and writable mounted `QB_DATA_DIR`. Preserve all reviewed existing application settings and bucket mounts.

Set explicit `EXPECTED_DB_NAME`, `EXPECTED_DB_USER`, `EXPECTED_CLOUDSQL_CONNECTION` and `EXPECTED_DATA_BUCKET` for the runtime guard. This image deliberately refuses to start without these values or without reviewed schema 0022. It does not provision missing tables or elevate DB privileges. Future migrations must update and test the schema guard deliberately.

## Zero-traffic deployment and promotion

Only after the preceding gates are complete, use a reviewed full configuration for a new revision, retain existing production traffic, and deploy with `--no-traffic` and a unique validation tag. Do not copy staging secrets into production. Confirm that creating a revision does not change the service-level IAM policy or overwrite unrelated environment variables.

Template, intentionally requiring explicit release variables:

```bash
: "${RELEASE_IMAGE:?Set the verified immutable image digest}"
: "${REVISION_SUFFIX:?Set a unique reviewed release suffix}"
gcloud run deploy question-bank-cloud-v4 \
  --project=gen-lang-client-0491787004 --region=asia-south1 \
  --image="$RELEASE_IMAGE" --revision-suffix="$REVISION_SUFFIX" \
  --no-traffic --tag=production-candidate \
  --cpu=2 --memory=2Gi --concurrency=10 \
  --min-instances=0 --max-instances=12 --timeout=300
```

This command assumes the reviewed production secrets, mounts, guard environment and identity have already been supplied. It will not work safely by itself against an unprepared service. Do not use it to bypass preflight.

Run bounded read-only health/authentication checks against the tagged revision. Use synthetic load only in isolated staging. Promote in an off-exam change window using explicit revision traffic weights (for example 1%, 10%, 50%, 100%) only with user authorization and healthy telemetry at each step. Preserve the recorded rollback revision. Never migrate or resize during an active exam.

## Exam window and scale-down procedure

Before registrations/start bursts, ensure database sizing is already stable, verify quotas, set the reviewed warm minimum and perform health checks. Monitor throughout the exam and submission grace period. After verifying no active attempts remain, restore the web minimum to zero. Let Cloud Run drain requests and scale horizontally down. Do not stop Cloud SQL or delete sessions/answers to reduce cost. Schedule any SQL vertical downsize for a separate maintenance window with backup/rollback preparation.

A scheduler/controller for these actions is NOT installed by this commit. Until implemented and verified, the exam-window warm-up/restore procedure is operated manually. Do not advertise automatic vertical scaling.

## Validation gate: 2,000 students for three hours

Run twice in isolated staging with one exam, 2,000 distinct users and 180 questions. The supplied staging-only scenario paces one answer approximately every 59 seconds, submits near 10,790 seconds, verifies 360,000 persisted answers and 2,000 correct scores, and revokes temporary sessions afterward. Ramp-up adds roughly three minutes. Its job must allow at least 12,600 seconds; do not reuse the ten-minute job timeout. Keep max retries zero and enforce a separate resource budget and restoration controller.

Do not run this three-hour workload as part of normal build/CI or against production. The default script uses a single API generator; complete the acceptance package with distributed browser/network tests and independent fixture provisioning if required. Stop promptly on failures; in-flight errors may continue briefly after the stop signal.

Acceptance criteria per run:

- 2,000 completed submissions and correct scores; 360,000 saved answers; no cross-user leakage.
- Zero unexpected request errors, dropped answers or unauthorized successes.
- Answer-save p95 <1 second and submission p95 <2 seconds; publish p99 and maximum too.
- CPU headroom, bounded connection waits, no prolonged DB saturation, no instance-cap exhaustion.
- Three-hour expiry, refresh, browser reload/reconnect, brief network loss, and staff MFA checks.
- A separate simultaneous-submission burst and cold-start ramp.
- Regional HA failover/restore rehearsal and evidence that a rolling app revision does not lose saved work.

A successful ten-minute run is not a three-hour soak test. The new heartbeat adds traffic; include it in browser load measurements. Threshold failures block the capacity claim even if every attempt eventually completes.

## Monitoring and rollback

Dashboard: API status/latency per operation, instance count/concurrency/CPU, SQL CPU/connections/lock waits/slow queries, connection checkout time, pending submissions, missing answers, job failures, and costs. Suggested investigation thresholds: DB CPU >70% for five minutes, save p95 >1 second, submission p95 >2 seconds, any unexpected 429/5xx during a scheduled exam, or rapidly growing connection waits. These alert policies still need deployment and verification; listing them here does not mean they exist.

On regression, stop promotion, restore recorded traffic weights and keep compatible schema. Do not terminate active exams, drop tables, roll back saved answers, or resize the DB as an emergency experiment. Preserve sanitized evidence and communicate the affected period. Secrets must never appear in reports.

## Cost and remaining decision

Scale-to-zero reduces idle web compute but does not remove Cloud SQL, storage, backups or network costs. A three-hour 2,000-student production plan needs a fresh cost estimate and validation budget using actual HA SQL regional pricing and expected payload/network volume. No such long-duration load run or production capacity purchase occurred during this preparation.

## Built candidate — 11 September 2026

Cloud Build `c1a76b9b-9fef-465c-99f7-11b1abe44fa3` succeeded, including disposable PostgreSQL migration and quota checks.

```text
asia-south1-docker.pkg.dev/gen-lang-client-0491787004/qb-security-staging/app@sha256:6a3d61f358c99fdde7550ea6f1549cbc2cf1f5f23fd07f377c251ac1833b963e
```

Local validation: 223 backend tests passed; exam heartbeat test passed; JavaScript/Python syntax and diff checks passed. The three-hour/2,000-student staging soak, production privilege preflight, security launch gaps and promotion gates remain outstanding. This image was built but not deployed to production.
