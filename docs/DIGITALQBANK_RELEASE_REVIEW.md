# DigitalQBank release review — 11 September 2026

## Deployment result

- Service: `question-bank-cloud-v4`, project `gen-lang-client-0491787004`, region `asia-south1`.
- Revision: `question-bank-cloud-v4-dqb-validated-0911-health`.
- Image digest: `sha256:96968dc856804f2e901190d8fbac0bcb3a8b4d56735a8614029962736adb0e10`.
- Final Cloud Build: `2dc39745-f0be-4510-a7d1-623c32f70575` — SUCCESS, including disposable PostgreSQL validation.
- Traffic: 100% to the new revision; Ready, ConfigurationsReady and RoutesReady are True.
- Both the default Cloud Run URL and `https://meritiqra.com/api/health` returned `status: ok` and the expected new revision.
- The candidate served a byte-for-byte match of the validated `static/grand-tests.js`.
- Previous serving revision retained for rollback: `question-bank-cloud-v4-epi-20260911072215`.

## Confirmed issues fixed

- Migration 0020 swallowed ALTER TABLE errors, leaving PostgreSQL transactions aborted. It now inspects existing columns before adding missing ones and backfills update audit fields.
- The 0020 revision identifier exceeded Alembic's standard 32-character version column. The unshipped revision is now `0020_dqb_document_controls`; the migration filename stays unchanged.
- Both new migrations use the PostgreSQL DDL translator for SQLite-style table definitions.
- Library upload fetched its response after closing the database connection. The response is now fetched inside the connection scope.
- An Operator could create a workspace from a hidden library document by submitting its ID directly. Creation, workspace access, page access, and workspace listing now enforce availability for linked library documents.
- Admin availability buttons passed invalid arguments to the API helper. They now use the authenticated JSON wrapper and recover their enabled state on failure.
- Program dropdowns now load filtered documents from the backend and show loading, empty and retry states.
- Library progress used summed workspace page rows and could overcount a PDF. It now resolves the latest status for each page within the selected Program and supplies pending defaults for untouched pages.
- The Admin table now displays the supplied progress and status metadata, uploader, dates and workspace links.
- Page status writes now enforce workspace revision checks and reject edits during digitisation or after exam generation. The browser updates its revision after a successful status write and tracks the page when scrolling.
- Replacing a workspace's source no longer retains status rows belonging to the previous PDF. Existing status history is retained.
- The sample exam fallback raised an undefined `idx` error; this path now initializes the fallback numbering.
- Public `/api/health` checks database connectivity and reports the revision. The tagged run.app URL returned Google's HTML 404 for `/healthz` while application routes worked, so deployment smoke checks now use `/api/health`.

## Verification

- Full backend suite: 198 passed.
- New regression tests cover library upload, availability filtering, direct hidden-document denial, Program filtering, page-status counts and optimistic locking.
- Browser workflow passed: Admin library upload and availability, Program dropdown, PDF scrolling/zoom/selection/redraw, both digitisation actions, review, scheduling, publishing, Operator access and Upload & Digitise regression. AI output is mocked.
- Actual PostgreSQL 16 validation runs inside Cloud Build before image publication. It upgrades the migration chain, simulates an older 0018 library missing new columns, upgrades to head, and repeats the upgrade. Serial IDs and final schema revision are checked.
- JavaScript syntax, shell syntax and `git diff --check` passed.
- Deployment uses an immutable image digest, a no-traffic revision and a tagged candidate smoke check before traffic moves. It preserves production environment settings.

## Earlier playbook items not fully implemented

The earlier completion messages overstated coverage. This release addresses confirmed defects and deployment blockers; it is not proof that every item in the earlier playbooks is complete.

- The library is based on Program document registrations; it is not yet a consolidated inventory of every source uploaded through unrelated Upload & Digitise workflows.
- File-size persistence, a complete digitisation-run audit trail, and history browsing are incomplete. Manual page-status and availability changes have audit records; automatic status transitions do not yet have equivalent history.
- Previous/Next controls remain DigitalQBank additions around the shared viewer rather than common controls in both viewers.
- Unsaved-change confirmation/browser-history navigation is incomplete.
- Upload messaging reports files in progress rather than byte-level transfer progress with persistent per-file results.
- Live authenticated production workflows and production AI extraction quality are not exercised by the mocked browser tests.

These gaps should be tracked separately from deployment readiness and should not be reported as verified features.
