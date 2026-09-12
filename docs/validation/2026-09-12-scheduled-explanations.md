# Scheduled explanations: implementation and operations

## Final design

Question generation produces the question, options, answer and worked solution.
English and Telugu teaching explanations are not requested in its response
schema and are not a prerequisite for review or publication.

After a question is persisted, missing explanations are added to the durable
`explanation_jobs` queue. Unsaved/discarded manual generation drafts do not incur
explanation work. Guided papers queue their persisted review questions.

Every five minutes, Cloud Scheduler starts the dedicated Cloud Run Job. One run
processes at most 10 questions by default. Each question gets one bilingual
provider request. Both languages are cached atomically; existing curated cache
entries are retained. Explanation buttons only read the cache or show a pending
message. They never invoke Gemini or charge student AI quota.

| Component | Resource/default |
|---|---|
| Worker | `qb-production-explanation-worker` |
| Scheduler | `qb-production-explanations` |
| Schedule | Every five minutes, Asia/Kolkata |
| Batch size | `EXPLANATION_JOB_BATCH_SIZE=10`, configurable 1–50 |
| Per-run starting-work budget | `EXPLANATION_JOB_BUDGET_SECONDS=240`, range 30–240 |
| Cloud Run Job timeout | 420 seconds; maximum one task, no execution-level retry |
| Per-question claim lease | 600 seconds |
| Attempts | `EXPLANATION_JOB_MAX_ATTEMPTS=5`, configurable 1–10 |
| Backoff | 5, 10, 20, 40, then at most 60 minutes |
| Worker model | Inherited production model configuration |

The worker may finish an already-started provider request after its work budget;
the 420-second task timeout and 600-second lease accommodate this. Overlapping
executions claim different jobs. An expired lease is recoverable after a crash.
After the attempt limit, an administrator can retry from **AI generation →
Scheduled explanation jobs**. Status is also available at
`GET /api/admin/explanation-jobs` (normal staff authentication/MFA).

Question edits invalidate existing explanations and supersede old queue claims.
Before writing, the worker checks its lease token and a hash of the current
question, options, answer, solution and visuals. It cannot save a result derived
from an older version. Errors store their type, not provider text or credentials.

## Deployment order

1. Run regression/browser checks and build the release using
   `BUILD_ONLY=1 bash scripts/deploy_gcp.sh`. Build validation checks the installed
   Gemini SDK and migrations against disposable PostgreSQL.
2. Execute `scripts/expand_explanation_jobs_schema.py` in a separate migration
   job using the privileged migration database connection. It only creates the
   queue/index, grants the existing runtime role access, and preserves the
   production Alembic rollback marker.
3. Deploy the application candidate with the verified image digest and no traffic.
   Its startup gate requires the queue table before it can become healthy.
4. Configure the worker with
   `scripts/configure_explanation_schedule.py --image <verified-image-digest>`.
   It inherits the existing worker's runtime identity and configuration references
   without retrieving secret values or modifying the existing worker.
5. Execute the worker once; verify completion and sanitized processed/succeeded/
   pending/failed counts in Cloud Run logs.
6. Promote the healthy application candidate. Rerun configuration with
   `--enable-schedule` to create/update the OAuth-authenticated Scheduler trigger.
   Invocation permission is scoped to the new Cloud Run Job, not the project.

The scheduler calls the authenticated Google Cloud Jobs API; there is no public
HTTP worker endpoint or MFA exception in the application.

## Validation

- 178 consolidated regression tests passed. Desktop/mobile browser acceptance
  also passed, including the pending explanation message and hidden save control.
- Regression tests cover queue deduplication, concurrent claims, expired leases,
  atomic bilingual cache writes, stale-question rejection, bounded retries,
  administrator-only retry, and no student quota consumption.
- A real provider test queued a synthetic Chemistry question in 0.002 seconds;
  the separate worker prepared both languages in 8.71 seconds. Both subsequent
  language reads returned cached content without AI.
- A separate real very-hard JEE Chemistry test completed three question-only
  questions with LaTeX and worked solutions in 67.89 seconds, including one
  provider token-limit recovery. All teaching explanation fields were empty.
  This is a workload observation, not a fixed latency guarantee.
- Production authenticated browser checks remain separate from these isolated
  provider tests and require the user's normal MFA session.

## Operations and rollback

Use the scheduler's pause/resume controls to stop/start new explanation batches.
Update `EXPLANATION_JOB_BATCH_SIZE` on the worker to change throughput and cost.
Queue status and failure counts should be monitored; a pending explanation is
not a failed exam. Review/publish continues while the queue is processing.

Rolling back the app does not require dropping the queue. Pause the scheduler
first if rolling back the worker. The additive schema is retained so queued
work and its audit state are recoverable. No production questions or exams are
deleted by this rollout.

## Production rollout receipt

- Application revision: `question-bank-cloud-v4-scheduled-explanations-c4654c1`,
  promoted to 100% traffic. Public `/api/health` returned this revision with `ok`.
- Image digest: `sha256:30823c3573a7752102bc765706b009c210c154a06184b16fb83c15e2f0449c3d`.
- Build `79466ddd-fbce-4245-a442-e073b0deaeca` passed, including actual PostgreSQL
  queue claims and atomic bilingual cache completion.
- Migration execution `qb-prod-explanation-queue-expand-20260912-xdz8s` succeeded;
  logs confirmed runtime grants and an unchanged rollback marker.
- First worker execution `qb-production-explanation-worker-4nhsr` succeeded:
  20 queued, 10 processed, 10 succeeded, 0 retries, 0 failures, 0 stale results.
- Scheduler `qb-production-explanations` enabled every five minutes.
  Authenticated Scheduler-to-Jobs API invocation returned HTTP 200 at
  `2026-09-12T10:15:07Z`.
- Candidate queue-status API returned HTTP 401 without authentication.
- 17 additional database/security tests passed alongside the 178-test regression
  suite. Authenticated production browser testing remains pending normal MFA.
