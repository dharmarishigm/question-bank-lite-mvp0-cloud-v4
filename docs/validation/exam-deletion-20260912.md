# Exam deletion repair — 2026-09-12

## Production finding

Production error logs at 10:59:33 and 11:00:53 UTC show `delete_exam` failing on
`grand_tests_exam_id_fkey` when deleting the parent exam. The reported endpoint
was `/api/admin/exams/41`. The Grand Test UI already instructs administrators to
delete the generated exam before deleting its workspace, but the exam route did
not detach that workspace. Guided paper jobs had the same missing cleanup.

## Change

Application commit: `38ed436`.

- Lock the exam and check registration, attempt, pending registration and question
  concern history before deleting anything. History returns HTTP 409.
- Detach Grand Test and guided paper links into `REVIEW_REQUIRED`; keep their
  source documents, reviewed questions, frozen prompts and generation results.
- Increment the Grand Test revision and remove the obsolete guided draft hash.
- Delete only the unused exam and its existing exam-owned delivery records.
  Keep question-bank questions, English/Telugu caches and explanation queue jobs.
- Preserve audit history and add `EXAM_DELETED` on successful deletion.
- Roll back all cleanup on failure. Foreign-key conflicts and database locking
  conflicts return HTTP 409, without leaking database details.

No schema migration, AI prompt, payment configuration, MFA policy, or explanation
worker/scheduler change is part of this fix. Exam 41 was not deleted for testing.

## Local validation

- 9 new deletion tests passed with SQLite foreign keys enabled, covering source
  preservation, unrelated exams, repeated deletion, four history guards, admin
  and CSRF checks, late foreign-key rollback, and real guided draft/published
  paper recreation from saved questions without provider calls.
- 77 related tests passed across guided exam generation, Grand Tests, explanation
  queue/runtime, question correction, security boundaries, role matrix and MFA.
- `git diff --check` passed.
- A broader exploratory run encountered 9 existing fixture failures in
  `test_result_features.py` (5) and `test_registration_identity.py` (4). These
  fail before deletion: missing scheduled start times return 422, or missing
  explicit attempt consent returns `CONSENT_REQUIRED`. Both guards exist in the
  previous HEAD (`e988138`); no product safety rules or unrelated fixtures were
  changed to mask these failures.

## Release verification

Cloud Build `928f3332-8c7d-468c-898a-cba26105c9cc` runs actual deletion SQL against
an explicitly guarded disposable PostgreSQL database, including workspace/cache
preservation and rollback on registration, attempt, concern and external-FK
history. All checks passed. Promoted `question-bank-cloud-v4-exam-delete-38ed436`
to 100% production traffic; both candidate and public `/api/health` returned
`status: ok` with that exact revision.

Image digest: `sha256:1aefad198778763da0f058c1a287eb1981b64a154d6a6154079ffe9dcdd9b7f0`.

Authenticated production deletion is intentionally not used as a smoke test;
the administrator can retry the original action after rollout. The prior
production browser session still requires the user's normal MFA completion.
