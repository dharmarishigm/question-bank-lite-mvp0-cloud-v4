# Saved generations and publication workspace

## Saved AI generations

Generate Questions by AI → Saved Generations now supports:

- Search across exam name, subject, chapter and topic.
- Exact, case-insensitive subject and class/level filters.
- Difficulty and status, including batches awaiting program-paper review.
- Server-side filtering across the entire history, 25 runs per page.
- Matching totals, empty states, reset and previous/next navigation.
- Existing review, input reuse and regeneration actions.
- Review up to 20 selected batches together on the visible page. Changing
  filters or pages clears that page's selection.

The existing `/api/ai/runs` response remains a list for compatibility. Optional
query parameters are `q`, `subject`, `level`, `difficulty`, `status`, `offset`
and `limit`; the `X-Total-Count` response header gives the matching total.

## Exam Admin publication queue

The Ready for review & publish queue lists complete program papers awaiting
review and approved drafts whose associated exam is still a draft. Published,
failed, incomplete, archived-program and inactive-program papers are excluded.
The queue is paginated and its list payload does not load all question bodies.

Review & publish opens the shared Programs reviewer directly within Exam Admin.
Questions, answers, solutions, correction tools and the frozen prompt remain
available. Publishing requires the explicit review checkbox and uses the same
server-side approval validation, completeness checks and version safeguards.
Manual exam drafts continue to use their existing Manage / Review & publish
controls. Nothing is automatically published by visiting the queue.

Admin-only read routes:

- `/api/programs/papers/review-queue?offset=0&limit=12`
- `/api/programs/{program_id}/exam-papers/{paper_id}`

## Layout and validation

Authoring metadata, filters, history rows and exam cards use tighter spacing and
responsive grids. Changes are scoped to admin authoring views. Tables remain
horizontally scrollable on phones while the page itself stays within the viewport.

Backend coverage: filters beyond the first 100 records, pagination, permissions,
query isolation, review/draft/publish lifecycle and archived-program exclusion.
Browser coverage: filter/reset/empty results, selected-batch review, explicit
publication confirmation, queue removal after publication and desktop/mobile
layout. The original Programs generation/review flow is also checked.
