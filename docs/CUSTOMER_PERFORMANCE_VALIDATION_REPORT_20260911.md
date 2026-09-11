# MeritIQra — Exam Performance Validation Report

**Test date:** 11 September 2026  
**Environment:** Isolated Google Cloud staging, Mumbai region  
**Assessment:** Internal synthetic API load testing; not an independent certification

## Executive assessment

Two later, complete 1,000-student synthetic exams passed on the tuned staging configuration. Each run completed all 1,000 submissions, persisted all 20,000 expected answers, correctly scored all attempts, and returned HTTP 200 for all 43,000 measured requests. Together, the runs produced 86,000 successful requests with no observed request errors. A prior 100-student baseline also passed.

Larger tests exposed capacity constraints. After an authenticated rate-limit correction, 1,000 and 2,000 active students were reached, but neither group completed the full exam workload. Google Cloud Run reported unavailable serving instances and returned HTTP 429 responses under sustained traffic. Those configurations did not pass. Subsequent tuning validated the specific 1,000-student workload described below twice; 2,000- and 10,000-student capacity remain unvalidated.

Production was excluded from the tests. Temporary staging capacity used for the 2,000-student attempt was restored afterward.

## Scope and method

Each run used one synthetic exam containing 20 multiple-choice questions, with a configured duration of 10 minutes. Each virtual student had a distinct account, enrollment, authenticated session, and CSRF token. The generator used the application APIs to start an attempt, retrieve questions, save answers, read session state, and submit near 590 seconds after starting.

Students saved an answer approximately every 29 seconds. The 100-student run ramped over approximately 30 seconds, the 1,000-student runs over 120 seconds, and the 2,000-student run over 180 seconds. Submissions were similarly spread across each ramp window; these were not single-instant submission bursts.

An active student denotes an open exam attempt with realistic pauses between requests. It does not mean every student continuously issues requests at the same instant. A complete run would generate approximately 43 measured requests per student.

The generator stopped on student failures. In-flight requests could still fail after the stop signal. A stopped test is reported as a failure even when its aggregate request success rate was high.

## Test environment

The application ran on Cloud Run with PostgreSQL on a separate staging Cloud SQL instance. Normal staging settings allowed up to three application instances, each with two vCPUs and 2 GiB memory, concurrency 20, and a bounded database connection pool. The staging database had one vCPU and approximately 3.75 GiB memory.

For the 2,000-student attempt only, the application maximum was raised to 10 instances, minimum instances to three, and per-instance concurrency reduced to 10. The database was not resized. Configured maximum instances describe the limit, not proof that all instances were simultaneously running. The load generator was a separate one-task job with two vCPUs and 2 GiB memory.

Because environment limits changed between runs, these are diagnostic capacity experiments rather than a controlled comparison of software performance alone.

## Results

| Run | Target students | Peak active | Completed and correctly scored | HTTP 200 | HTTP 429 | Full exam result |
|---|---:|---:|---:|---:|---:|---|
| Baseline | 100 | 100 | 100 | 4,300 | 0 | Passed |
| Initial larger attempt | 1,000 | 464 | 0 | 1,832 | 3 | Stopped during ramp-up |
| After account-based quota fix | 1,000 | 1,000 | 0 | 24,225 | 19 | Failed during sustained traffic |
| Temporarily expanded staging | 2,000 | 2,000 | 0 | 21,071 | 255 | Failed during sustained traffic |
| Tuned configuration, run 1 | 1,000 | 1,000 | 1,000 | 43,000 | 0 | Passed |
| Tuned configuration, run 2 | 1,000 | 1,000 | 1,000 | 43,000 | 0 | Passed |

An earlier 100-student harness setup attempt was stopped on its first request because the generator omitted a required CSRF cookie. It was corrected before the successful baseline. Application CSRF protection was not disabled.

### Response times

Milliseconds measured by the load generator. p95 means approximately 95% of recorded responses were at or below that value. Figures include measured error responses and cover only the requests made before each test stopped. They are not service-level commitments.

| Operation | 100 students p95 | 1,000 after fix p95 | 2,000 p95 | 2,000 p99 |
|---|---:|---:|---:|---:|
| Start exam | 167.5 | 382.0 | 521.6 | 886.7 |
| Read session/questions | 161.9 | 8,854.1 | 10,177.4 | 11,516.8 |
| Save answer | 128.1 | 7,984.0 | 8,970.4 | 11,307.0 |
| Submit exam | 277.6 | Not reached | Not reached | Not reached |

The larger runs demonstrate acceptable initial starts followed by degraded sustained reads and writes. Reaching the target number of active sessions alone is insufficient evidence of usable exam capacity.

## Findings and remediation

### Shared-network rate-limit behavior

The initial 1,000-student attempt charged all authenticated requests from a shared source IP to one quota. That is unsuitable for many legitimate students behind a school or office network.

The boundary was changed so verified, active accounts have independent ingress quotas. Public requests and missing or invalid sessions remain IP-limited. Per-operation limits, authorization, MFA, CSRF, and session expiry remain enforced. Regression tests verify that forged cookies cannot select a new account quota.

The corrected run passed the former 464-user stopping point and improved start p95 from approximately 3.9 seconds to 382 ms. The tests support this narrower improvement, not an overall capacity certification.

### Sustained serving-capacity constraint

In the later 1,000- and 2,000-student attempts, Cloud Run logs explicitly reported that requests were aborted because no instance was available. Sustained read/save latency also increased materially.

This confirms a serving-capacity symptom. These tests alone do not establish whether database utilization, connection waits, blocking application work, autoscaling behavior, or a combination is the underlying bottleneck. Subsequent profiling and remediation for the 1,000-student workload are documented below; further profiling is still required before larger capacity claims.

## Security and data integrity evidence

The backend regression suite passed 213 tests at the quota change and 214 after the answer-saving worker-thread change. Targeted checks covered Admin access denial for Students, MFA enforcement, session expiry and rotation, CSRF, rate-limit behavior, and forged identity headers/cookies. Separate local browser tests exercised Student navigation restrictions and Admin MFA flows with disposable accounts.

The 100-student load run verified every submitted score against the expected answers. The stopped larger runs did not reach final submission and therefore do not establish score correctness at those load levels.

This work is not a full penetration test, independent audit, payment security assessment, or formal security certification.

## Cleanup and production isolation

Temporary test sessions were revoked, synthetic accounts disabled, and dummy exams closed after each completed or aborted execution. Synthetic exam/audit records were retained as test evidence.

After the 2,000-student attempt, staging was verified back at a maximum of three instances, minimum zero, and concurrency 20. Database size was unchanged. No production traffic, configuration, accounts, or database contents were modified by these tests.

## Cost projection

The 2,000-student attempt was budgeted at approximately **US$1–3 additional cost**, within an approved US$20 testing budget. The estimate allowed for temporary app capacity, a bounded load-generator job, requests, and logging, without a database resize or assumed free-tier credits.

This is a planning estimate, not a verified invoice. Billing data can arrive later; actual charges and applicable taxes must be reconciled separately. The estimate used Google's published Cloud Run pricing: https://cloud.google.com/run/pricing.

## Limitations

- Synthetic API clients ran in the same cloud region; these results do not measure internet latency from students' devices.
- A single generator was used per run, not a geographically distributed fleet.
- Google sign-in throughput, browser rendering, PDF/AI processing, video proctoring, and payment workflows were excluded.
- Each test used a small, fixed 20-question exam and a staging dataset.
- A burst of all submissions at the exact same instant was not tested.
- No 10,000-user run has been executed or validated.
- Results are point-in-time observations of the tested configuration, not a guarantee for production or arbitrary workloads.

## Recommended next validation (updated)

The completed profiling found 100% database CPU during the failed larger test, with all 10 app instances active and approximately 51 database connections. Synchronous database work in the async answer-saving handler was moved to a worker thread. The complete 1,000-student test then passed twice using a temporary two-vCPU database and revised application limits.

Before increasing the capacity claim, repeat with realistic browser clients and geographically distributed generators, larger exam payloads, and a synchronized submission burst. Run a new 2,000-student test only with an approved capacity plan and budget. These results do not justify a 10,000-student claim.

## Customer-facing statement supported by this evidence

“Two isolated staging tests each successfully completed a 10-minute, 20-question exam for 1,000 concurrent simulated students using the tested tuned configuration. Across both runs, all 86,000 measured requests succeeded, all 40,000 expected answers were persisted, and all 2,000 submissions were correctly scored. The tests used paced API traffic and staggered submissions; they do not establish a production SLA or 2,000-/10,000-user capacity. Production was not modified by these tests.”

## Tuned 1,000-student configuration and repeat results

- Application: two vCPUs and 2 GiB memory per instance; maximum six instances, minimum two; per-instance concurrency 10; pool size five per instance with no overflow.
- Database: PostgreSQL Enterprise, zonal, two vCPUs and 7.5 GiB memory.
- Existing authenticated per-account and operation quotas remained enabled. Public and invalid-session requests remained IP-limited.
- Answer saving retained authorization, CSRF validation, audit recording, and transaction commit while moving blocking persistence off the event loop.
- Same 20-question, 10-minute API workload; 1,000 distinct students ramped over approximately two minutes; one bounded same-region generator per run.
- Observed database CPU samples during the first successful sustained period were approximately 40–56%, compared with 100% in the prior failed test.

| Operation | Run 1 p95 (ms) | Run 1 p99 (ms) | Run 2 p95 (ms) | Run 2 p99 (ms) |
|---|---:|---:|---:|---:|
| Start exam | 184.9 | 412 | 226.8 | 593.3 |
| Read session/questions | 226.4 | 357.8 | 205.1 | 309.7 |
| Save answer | 192.8 | 301.7 | 171.3 | 268.6 |
| Submit exam | 335.5 | 482.2 | 329 | 405.7 |

Both runs met the proposed p95 targets of below one second for saving answers and below two seconds for submission. There were outliers: the maximum measured answer-save latency was 6,852.4 ms in run 1 and 1,062.5 ms in run 2. Percentile results must not be represented as an upper bound on every request.

The application fix and infrastructure increase were tested together; their independent contributions were not isolated. The successful 1,000-student result applies to this configuration, not the restored smaller staging database or unchanged production deployment. Two finite successful runs are validation evidence, not a guarantee of unlimited reliability.

Temporary capacity restoration was verified: staging database RUNNABLE at its original one-vCPU/3.75-GiB tier, app maximum three instances, minimum zero, concurrency 20. Staging health and the production app returned HTTP 200 afterward. Production was not modified. Actual cost has not been reconciled with billing; the US$20 budget is an authorization limit rather than an observed invoice total.
