# Corrected question rendering — 2026-09-12

Application commit: `93854ad`.

## Behavior

Saved, approved corrections replace the primary question content in bank/edit
views, saved AI previews, guided program papers, DigitalQBank saved rows,
source/fullscreen comparisons, live exams, released student/admin reviews and
tutor context. Unapproved bank drafts do not replace attempt content. Source
evidence and unrelated unsaved authoring edits are preserved.

Active attempts synchronize their effective snapshot before reads, answer saves
and submission. Statement/options changes invalidate the old visible-content
revision, preserve the previous question and response in the audit log, and
require the affected answer to be reviewed again. Stale browser/mobile saves
return 409. Answer-key/solution-only corrections keep selections. Timing, marks,
section membership and published-version identity remain unchanged.

Submitted attempts retain their stored snapshots, responses, marks and rankings.
Their primary review shows current corrected content, with an explicit original
question/recorded-answer/grading notice. This release does not regrade completed
attempts. Concurrent submissions are internally snapshot-consistent; a submit
already in flight can complete on the version it read before an overlapping
correction commits.

English/Telugu cache entries are invalidated only for changed content; the
scheduled worker rebuilds them. No-op review keeps existing cache entries. The
legacy Like endpoint can acknowledge matching existing cache only: pending
messages, stale dialog text and arbitrary client text cannot become cached
explanations. Question-view refresh makes no AI calls.

Active/unreleased responses never expose answer/solution fields, raw answer
snapshots or answer-figure URLs. Released review can include answer figures.
Ordinary question diagrams remain visible, and hydrating identical legacy
figure metadata does not clear existing answers.

## Verification

- 226 consolidated Python regression tests passed, including deletion, active
  correction/scoring, historical grading, cache, mobile and security coverage.
- Three isolated Chromium acceptance scripts passed: question correction,
  guided-paper creation, and the complete in-exam correction/re-answer/result
  workflow. Desktop and 390px mobile layouts passed; mobile screenshot inspected.
- Extended browser checks passed for cross-tab dirty-editor preservation,
  DigitalQBank saved-row refresh without losing unrelated draft text/selection,
  source/fullscreen preview refresh and explanation invalidation.
- Changed JavaScript syntax checks and `git diff --check` passed.
- Independent review found and resolved answer-figure exposure, a concurrent
  deleted-workspace reread, and a nested database-pool checkout risk.
- The prior unrelated result/registration fixture failures are documented in
  `exam-deletion-20260912.md`. The mobile fixture was updated only for existing
  scheduled-start/explicit-consent requirements; no safety rule was weakened.

## Release

Cloud Build: `8b9f4135-c13a-43af-9883-0d995752952d`. The release gate exercises the
real reviewed correction save, cache invalidation, stale-revision rejection,
active reset/re-answer/grading and immutable completed-history SQL against a
guarded disposable PostgreSQL database. All checks passed. Candidate health and
cache-busted script references were verified before promotion.

Production now serves `question-bank-cloud-v4-current-question-93854ad` at 100%
traffic. Public `/api/health` returned `status: ok` with that exact revision, and
the immediate revision-specific error-log query returned no errors.

Image digest: `sha256:5a8fbc1d0c2ed7ad2df1aa95df4ba8f4b4190a1ce68a0f1c2ca82eff53444e11`.

No production exam/question was edited or deleted for testing. Authenticated
production browser testing remains dependent on the user's normal MFA session;
local browser tests do not substitute for that access. The explanation schedule
and worker remain unchanged. Refresh the app after rollout to load the revised
answer-revision client; backend checks reject stale clients after a correction.
