# Question corrections and in-exam concerns

Admins can open **Edit / AI correct / Regenerate** from the question bank, exam paper preview, blueprint preview, guided program paper review, digitisation review and comparison, generated batch drafts, saved batch questions, concern review and student-attempt review. The existing main question editor also offers AI correction/regeneration.

The shared editor allows changes to question text (Markdown/LaTeX), options, answer and solution. AI returns a proposal, change summary and uncertainties. Applying a proposal only fills the editor; updating requires admin review. Uploaded source crops can be included in the model request when available. Source access is restricted to image files in the upload directory, up to 4 MB; arbitrary paths and remote URLs are not fetched. AI cannot guarantee correctness or reconstruct missing visual evidence.

Bank updates check the original content to prevent overwriting concurrent changes, preserve source/generation metadata, snapshot the previous version, rebuild rendered content and invalidate cached explanations. All linked program-paper previews and saved-generation previews update to the corrected bank content. Reviewed corrections create a new published version for future attempts, copying the previously published version and changing only that question. Unrelated unpublished content and exam configuration are not included. Older published versions and attempt snapshots remain unchanged. Corrected review/draft papers require acknowledgment of their current revision before approval; stale review pages are rejected.

Students can **Flag question / Raise concern** while an exam is in progress. Reports identify wording/equation/digitisation, options, answers or another issue. A flag appears beside the question and in the question navigator, and survives resume. Reporting does not change selected answers or pause the timer. Reports are restricted to the student's own attempt and its questions. Admin resolution text is withheld until results are released. Admins use the existing Question concerns queue to correct and resolve reports.

Validation includes backend authorization, no-write AI proposals, stale update protection, revision history, cache invalidation, program review synchronization, active exam reporting, duplicate reports and attempt ownership. Browser checks cover mobile/desktop equation rendering, explicit suggestion acceptance and updates, shared batch/concern editing and flags across resume. AI browser tests use deterministic mocked proposals; live model output still requires human review.

## Student content protection

Student exam, result and analytics views disable normal copying, selection, dragging, saving and printing; editable answer/report fields remain usable. Print styles hide protected content even through the browser print menu. A repeated student-name/ID/date watermark discourages redistribution. The existing Android native `FLAG_SECURE` bridge is enabled for these views. Web controls cannot guarantee protection against OS screenshots, camera photos, developer tools or an authorized client recording content it can display.

Only admins can export report PDFs or create report share links. Previously created student report links are no longer downloadable. Student result access retains ownership and release checks; authenticated content responses use no-store/private caching. A database-backed rolling read quota permits 120 protected content reads/minute and 2,000/hour per student across workers/sessions, returning 429 with Retry-After. It does not apply to saving answers or submitting attempts. This limits bulk automated reads; it is not a guarantee against all scraping.

## Subject and section marks

Student and admin result details show subject-wise earned/maximum marks, percentage, question count and correct/incorrect/unanswered totals. A separate section table appears when section grouping differs from subjects. Calculations use the immutable attempt snapshot and stored marks awarded, including negative marking. The mobile table scrolls inside the report. Existing student copy/print/download restrictions apply to this breakdown.

## Administrator exam participation and current corrections

Admins can use **Take exams**, **My exam attempts** and **My results** from the
admin navigation, or the existing student workspace switch. Administrators can
enroll themselves in published/open exams even when student self-registration
is disabled. Exam opening times, proctor codes and attempt limits still apply.
Admin attempts are excluded from student leaderboards.

The active exam screen now includes the shared admin correction editor. Expanded
question-image views and explanation dialogs also provide the editor when a
question identity is available. Student accounts do not receive editor controls.
The main editor, saved AI batches, bank previews, program-paper previews and exam
previews reflect corrected content. Saved batch identity is resolved against bank
questions and their history so legacy previews do not retain old option text.

Existing active and completed attempts show **Correction available** with the
current approved question alongside the original. Recorded selections, option
ordering and scores remain based on the original attempt. Active attempts receive
only corrected wording/options, never the answer or solution. Released result
reviews also show the current answer and solution. Active pages check for new
corrections every 30 seconds and when returning to the tab; corrections made in
the same admin page appear immediately. Students' scores are not recalculated.

Validation covers admin participation and ownership, correction propagation across
multiple papers, stale review rejection, selective future-version creation,
immutable historical versions/answers/scores, absence of answer leakage in active
correction notices, legacy batch previews and desktop/mobile exam-taking.
