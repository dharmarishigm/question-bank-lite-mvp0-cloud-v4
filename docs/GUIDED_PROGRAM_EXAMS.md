# Guided program exams

## Refined requirement

Allow an administrator to add a program such as Navodaya using only its name, then immediately create a full or subject-wise exam. Offer Very Easy, Easy, Medium, Hard and Very Hard difficulty. Automatically retrieve the current official prospectus, validate AI-extracted section counts, totals, timing and marking against quoted source evidence, and populate the editable inputs. Generate suggested curriculum and Markdown authoring guidance with the configured LLM. Let the administrator review suggestions and edit every input. Compose the final prompt from those inputs, reuse matching approved questions, and generate missing questions through the existing AI question pipeline. Save generated questions in the canonical Question Bank for review. After the complete paper is reviewed, save a draft exam or explicitly publish it through the existing examination platform.

## Using the screen

1. Open **Programs → Add program**, enter the name, and save. Optional metadata is collapsed; the stable code is generated automatically.
2. Choose **Full Exam** or **Subject-wise**, class, language, difficulty and duration.
3. Enter subjects, counts, marks, penalties and optional topics. Subject-wise keeps one chosen subject. Full Exam uses every listed section, up to 200 questions total.
4. New programs automatically retrieve the official pattern and populate the curriculum, class, sections, marking, duration, instructions and AI prompt. The reference panel links the official prospectus and records when it was checked. **Refresh official pattern** performs a new lookup. AI curriculum and prompt suggestions populate their editable fields directly. If an official source cannot be confirmed, the screen reports the failure and permits a custom practice pattern.
5. Use **Build prompt from my inputs** or **Improve prompt with AI**, then edit the generation prompt. The final prompt automatically updates as formatted Markdown, including a subject table, all form inputs and official source references. Expand **View / copy Markdown source** for the raw text. Structured inputs take precedence over conflicting prose.
6. Select **Generate paper for review**. The request and results are stored, so you can leave and return while generation runs.
7. Review the paper, options, answers and worked solutions. Check the review acknowledgement, then save a draft or publish. Published exams are available in **Exam Admin**, where the existing scheduling, enrollment and opening controls continue to apply.

## Implementation and reuse

- `official_exam.py` retrieves live official documents, checks verbatim evidence and numeric consistency, and persists lookup results. Navodaya starts from the NVS portal and follows its current prospectus link; other programs use grounded Google Search discovery with restricted official-source hosts. Failed source checks never substitute model-memory rules.
- `program_exam.py` coordinates on-demand suggestions, frozen requests, background generation, exact-context retrieval and reviewed publication.
- `app.generate_ai_questions_core` is the same pipeline used by the existing Generate Questions by AI endpoint, including structured validation, duplicate filtering, generation history and visual rendering.
- New bank questions use `REVIEW_REQUIRED` until paper approval. Generated figures are included in the canonical statement so the existing exam snapshot and delivery renderer preserve them.
- Reuse requires an approved question with the same program, subject, level, language, difficulty, curriculum, topic constraints, pattern, instructions and editable prompt. It deliberately generates new content when those authoring constraints change. Counts, marks and duration may change without invalidating content reuse.
- Each section is filled in bounded batches. Incomplete or invalid results fail the job; no partial paper is published. Retrying failed or interrupted jobs is explicit. This uses the application's in-process background-task model, not an external worker queue.
- Approval checks the frozen questions against the current bank, preserves section marks and penalties, and calls the existing `publish_version` snapshot function. Duplicate approval returns the existing exam. A draft changed elsewhere must be reviewed in Exam Admin before publishing.
- The advanced immutable blueprint workspace remains available under **Advanced program workspace**.

## Deployment and validation

Migrations `0010_program_exams` and `0011_official_exam_lookups` add durable paper and official-source lookup tables. SQLite startup initializes it automatically; PostgreSQL deployments must run `alembic upgrade head` (already part of the container startup command). Local automated tests mock model responses; live model and deployment checks are recorded separately below.

Cloud Run uses instance-based CPU allocation and one minimum instance so in-process paper generation can continue after returning HTTP 202. Interrupted jobs can still require an explicit retry; a minimum instance is not a durable external queue.

```sh
QB_DATA_DIR=/tmp/meritiqra-guided-tests .venv/bin/python -m pytest -q
node --test tests/test_ui.cjs tests/test_pdf_selection.cjs
.venv/bin/python tests/validate_program_exam_ui.py
```

The browser acceptance test uses a temporary database and mocked AI responses, covering name-only creation, automatic official setup, section timings, live totals, Markdown rendering, AI suggestions, prompt edits, all five difficulty options, full/subject generation, review/publication, rendered questions and phone layout.

## GCP deployment — 10 September 2026 (IST)

Deployed to [MeritIQra](https://meritiqra.com/app) as `question-bank-cloud-v4-guided-20260909-200629`, serving 100% of traffic. Cloud Build `78e42b36-9626-4513-9b5c-f69d1950ea66` produced image digest `sha256:db4018bdc0c619e207f901f9ed7f69c709dc12fde7db5855a8d2ef13dd22ae2c`. Startup logs confirmed migration `0010_program_exams`.

Live checks verified health, the workspace, matching frontend assets, anonymous access denial, authenticated PostgreSQL paper-job queries and difficulty-aware prompt preview. No production paper was generated or published during validation. The direct revision URL returned a routing 404; checks passed through the custom domain.

Rollback traffic target: `question-bank-cloud-v4-setup-192b51e`. The additive migration can remain in place during application rollback. See [deployment evidence](validation/guided-exams-deployment.json).

## Official-source verification

The live Navodaya check on 10 September 2026 (IST) retrieved the NVS portal’s current `Final_Prospectus_2027.pdf`. It extracted the 2027–28 Class VI pattern: Mental Ability and Environmental Studies together 40 questions/50 marks/60 minutes, Arithmetic 20/25/30, Language 20/25/30; total 80 questions, 100 marks, 120 minutes, no negative marking. The combined section preserves the source’s 20 + 20 questions and 25 + 25 marks in its topic evidence. Curriculum and authoring instructions remain explicitly labelled AI guidance.

Validation: 148 Python tests, two JavaScript suites, desktop/mobile browser acceptance, and one successful real Gemini lookup plus AI guidance call. The lookup uses a checked timestamp and source link; refresh retrieves a new document instead of claiming a cached response is continuously live.

The official-source update is deployed as `question-bank-cloud-v4-official-20260909-202953` with 100% traffic. Build `e602e1f9-3475-46eb-926d-32eb25a163cc` produced digest `sha256:86e21c38e46691384ef8ed3890f87a84fad3cf2a99b0bb1dd0d1c1e65a783a9f`; startup applied migration `0011_official_exam_lookups`. Production health, assets, authenticated database queries and Markdown prompts passed. A real production AI lookup populated the official pattern and guidance in an inactive validation program, which was then archived. No production exam was created. Rollback target: `question-bank-cloud-v4-guided-20260909-200629`. See `docs/validation/official-pattern-deployment.json`.

## Archived program guard

The Programs screen defaults to active programs. Archived entries remain available through the status filter and show **View archived program** instead of **Create exam**. Opening one shows **Restore program and create exam**; generation controls and automatic AI lookup appear only after the explicit restore succeeds. Archiving an open program immediately refreshes its workspace. Backend archive restrictions remain enforced. The browser regression covers the active filter, archive transition, hidden form and successful explicit restore.

Deployed the archive guard as `question-bank-cloud-v4-archivefix-20260909-203952` with 100% traffic. Request logs identified the previously archived validation program as the user’s selected program; it was explicitly restored to unblock their existing inputs, and its prompt endpoint returned HTTP 200. Validation: 15 relevant backend tests, two JavaScript suites and browser archive/restore regression. See `docs/validation/archive-guard-deployment.json`.

## Grade 8 SOF Olympiad programs

Separate active Science (SOF ISO) and Maths (SOF IMO) programs use the SOF Level 1 Class 8 syllabus pages. Their class-band tables, total marks and timing are retrieved live and validated with verbatim evidence. The source pages are undated, so the reference makes no exam-year claim. They do not explicitly specify negative marking; the practice penalty defaults to an editable zero and this uncertainty is displayed. Curriculum generation receives the official syllabus text, including current/previous-class coverage rules.

The authority allowlist includes only the exact SOF hosts. Undated-source support is restricted to the inspected Grade 8 syllabus paths; other sources retain current-year validation. Separate timing quotes handle syllabus pages where timing and table text are not contiguous. Both live model lookups passed, along with 149 backend tests and two JavaScript suites.

Deployed as `question-bank-cloud-v4-sof8-20260909-205125`, serving 100% traffic. Both requested programs (IDs 5 and 6) are ACTIVE with READY official lookups and verified Markdown prompt previews. No question paper or exam was created. See `docs/validation/sof-grade8-deployment.json`.

## Full-paper recovery

Paper jobs now request at most five questions per durable checkpoint. Each accepted batch updates the saved job result and progress count; a retry reconstructs its pending questions and generates only the missing slots. Transient authoring failures receive bounded retries, and repeated empty/duplicate batches stop with preserved progress. The canonical Question Bank is updated atomically once the complete paper is ready.

The exact-context lookup recognizes both guided metadata and the nested metadata written by the standalone AI review screen. Saving a generated batch during paper generation attaches an identical matching question instead of failing with a duplicate error. Repeated identical generation requests join an existing active job. Reused question figures are included in the review and published exam snapshot.

Validation: 153 backend tests, JavaScript regression checks and the browser review/publish flow. Regression tests cover an 80-question build, mid-paper failure/resume, separately saved batches, duplicate clicks and preserved question figures.

Deployed as `question-bank-cloud-v4-paperfix-20260909-210926` with 100% traffic. Retried the user’s failed Navodaya paper #2 and verified `REVIEW_REQUIRED` with 80 distinct question IDs: 40 Mental Ability/EVS, 20 Arithmetic and 20 Language. All 80 were recovered from matching approved bank questions. Eighteen question figures are included; three sampled figure requests returned HTTP 200. The paper remains unpublished for user review. See `docs/validation/full-paper-recovery-deployment.json`.


## Class 9 SOF Olympiad programs

Added active programs 7 (Science / ISO) and 8 (Mathematics / IMO), with Class 9 Level 1 official-source setups. Both have 50 questions, 60 marks and 60 minutes. Sources are retrieved from the matching Class 9 SOF page; Class 8 syllabus sources are attached separately for prior-year coverage. Achievers guidance stays at Class 9. The undated pages do not establish a penalty, so the editable zero practice penalty is disclosed as an assumption.

Class/stage normalization accepts AI output “Level 1” only for a known SOF class page and still validates the actual source class. Program setup AI responses now have a 16,384-token allowance, avoiding truncated Mathematics guidance. Live source extraction and Markdown prompt previews passed for both programs. See `validation/sof-grade9-deployment.json`.

## Saved entrance-exam setups

Administrators can save all guided inputs with **Save exam setup**. A saved setup loads when the program is reopened and supports the existing Full Exam / Subject-wise selector, five difficulty levels, bank reuse, generation checkpoints, review and publication. Saving a setup neither generates questions nor publishes an exam. The authenticated `/api/programs/{id}/exam-setup` GET/PUT endpoints validate inputs, retain source lookup references and use optimistic revision checks. Migration 0012 adds durable setup storage. Inserts explicitly return `program_id` to work with the PostgreSQL adapter as well as SQLite.

The entrance programs use published 2026 official booklets and syllabuses checked on 10 September 2026 IST. NEET and both Telangana EAPCET streams use their MCQ counts and scoring. JEE Main and JEE Advanced are explicitly labelled MCQ practice adaptations: the current guided generator cannot reproduce numerical-answer, multiple-correct, partial-credit or two-session delivery. Their official reference rules and practice differences are included in the editable pattern, student instructions and authoring prompt. Advanced's combined practice setup has 102 single-correct questions and 306 practice marks; the official 2026 reference has 360 marks across two compulsory papers. No claim is made that an adapted paper reproduces the official exam format.

## Results and combined batch review (September 2026)

Exam leaderboards rank each student's best completed attempt by score percentage, then raw score; equal scores share competition ranks. Students can view rankings only for their exams after results are released. Individual result reports export to PDF. Explicitly created share links contain a summary without questions, answer keys or email addresses, expire after seven days, and can be revoked.

Question cards offer a concern form. Administrators can open the concern queue from Results, correct a question using the existing editor, and resolve or dismiss the concern with a note. Corrections retain AI provenance and question versions. Existing attempt snapshots and submitted scores remain unchanged and show correction notices. Reviewed corrections synchronize linked previews and create corrected published versions for future attempts; see QUESTION_CORRECTIONS.md.

Saved AI generations support selecting up to 20 batches, reviewing their questions together, editing drafts, and saving selected questions or all reviewed questions in one transaction (up to 500 selected questions). Invalid selections roll back the entire save. Already banked questions are linked without duplication, and retrying a save is safe.

Validation includes backend access-control, ranking, expiry/revocation, concern workflow, draft concurrency and atomic save tests, plus a desktop/mobile browser acceptance flow and rendered PDF inspection.

## Student explanation quota

Student accounts may start at most 10 new AI explanation calls in any rolling hour, shared across languages, explanation routes, login sessions and Cloud Run instances. Database transactions serialize reservations per user before provider calls. Failed provider attempts consume quota; saved structured explanations do not. The eleventh call returns HTTP 429 with a readable retry message and Retry-After header. Admin calls remain unchanged. Tests cover concurrent requests, independent users, expiry, both student routes, cache reuse and denial of the legacy admin route to students.

Homepage assessment descriptions now render escaped Markdown headings, emphasis, lists, links and tables. Exam, paper preview, generated review and answer-option images use proportional bounds, fit their containers and avoid enlarging small source images; inline formulas retain their own styling. Desktop/mobile browser checks covered Markdown escaping and wide, tall, small and option image layouts.
