# UI spacing and IQraMentor delivery

## Architecture and scope

MeritIQra uses FastAPI, SQLite locally, PostgreSQL/Cloud SQL in production, and shared HTML/CSS/vanilla JavaScript. `app.py` serves public pages and Question Bank functions; `platform_api.py` handles authentication, roles, exams, and results; `exam_conduct.py` owns snapshots, proctoring, and release policy. Google Identity Services and opaque HTTP-only sessions remain intact. Vertex AI is the existing provider. No frontend framework or external agent framework was introduced.

Work is on `codex/feature-ui-density-iqramentor`, based on `d5ca886`. No changes are committed to main.

## UI audit and implementation

| Surface | Problem found | Implemented change |
| --- | --- | --- |
| Public home, exam listings, feature and audience sections, footer | 650px hero minimum; 88px section padding; oversized cards | Flexible hero, 48px desktop/32px mobile sections, smaller headings and cards; marketing hierarchy retained |
| Student/admin dashboards | Large metric cells; no next learning action | Compact metrics, evidence-backed learner insight and Explore Exams action |
| Available Exams / My Exams | 220px minimum tile heights | Content-sized responsive tiles with compact metadata |
| Performance Lab | Repeated heading; vertically stacked chart, mastery and recommendations; every attempt repeated below chart | Single heading, six KPIs, chart beside recommendations, collapsible values, mastery/evidence grid and responsive attempt cards |
| Results / attempt review | Giant gradient result hero, oversized score and tags | Compact result summary, smaller cards, preserved question line-height; result/question tutor entry points |
| Profile / registrations | Excessive shared form spacing | Consistent compact responsive form gaps and padding |
| Question Bank | Wide minimum filter columns, excessive card gaps; initial student page fetched admin filters | Responsive compact filters, two-column desktop question cards, role-aware initialization |
| AI generation | Long vertical form sections | Two-column desktop content fields, compact metadata/advanced controls |
| Upload/digitization and question editing | Large surrounding margins | Shared compact shell; original crops and readable question content preserved |
| Exam generation | Blueprint table expanded the entire page at 820px and 390px | Constrained fieldsets and local table scrolling; mobile action bar no longer overlays form |
| Exam management / students / registrations / sessions / admin results | Large shared table cells and actions | Compact cells, responsive overflow and grouped existing actions |
| Formal exam session | Reading and integrity constraints | Question readability preserved; assistant hidden and blocked server-side |
| Shared navigation | Mobile menu control inside transformed hidden sidebar | Menu control moved into header; mobile toggle and desktop collapse work |

The new `static/workspace-density.css` is a final shared stylesheet. Spacing tokens use 12px gaps and 14px surface padding, a 236px sidebar, and a 26px desktop page title. Operational content can use up to 1680px including padding. Narrow screens use two KPI columns and a full-width tutor drawer.

At 1440×900 using ten synthetic released attempts, the previous Performance Lab recommendation panel began at y=1540. The new panel begins at y=377; the chart, all six KPIs, and recommendations are visible in the first viewport. Topic mastery also starts within that viewport. Before-page height was 1972px; the compact page is approximately 1595px including the new evidence and recent-attempt content. Dataset and viewport affect these measurements.

## Analytics and recommendations

`performance_service.py` reads at most 20 recent released attempts within at most 365 days (defaults: ten attempts). It batches answer and legacy metadata reads, avoiding per-question queries. New exam snapshots now retain subject/chapter/topic/subtopic/difficulty metadata. Existing snapshots fall back to current question metadata; their old taxonomy cannot be reconstructed if metadata has subsequently changed.

It computes score averages, accuracy among answered questions, completion, correct/incorrect/unanswered totals, lost marks, elapsed assessment seconds per question, recent trend, topic/chapter/difficulty/type summaries, strengths and learning gaps. Improvement means latest score minus the mean of previous selected scores, in percentage points. Difficulty/type filters affect question metrics; whole-attempt scores remain intact and are labelled accordingly.

A topic needs five answered questions before classification. Accuracy below 60% produces a gap; `gap_score = 1 - accuracy/100`. Confidence is moderate at 5–19 answered questions and high at 20+. Accuracy at least 80% produces a strength. Recommendations explain their sample/accuracy evidence and offer existing open exams in the same subject. They do not invent targeted question sets. Without enough evidence, the action is to build a baseline. The seven-day plan is a deterministic suggested schedule, not a calendar commitment.

An exam benchmark uses the latest released attempt per distinct learner on the identical published exam version. The threshold is 30 learners. Percentile uses midpoint treatment of ties: `100 × (below + tied/2) / cohort_size`. Only aggregates leave the query. No national, state or institution ranking is claimed. A selected examination with version evidence is required; otherwise the insufficient-evidence message is shown.

Readiness is explicitly unavailable because syllabus coverage and reliable question timing are not recorded. Elapsed assessment time is labelled; it is not portrayed as topic dwell time. No fabricated speed risk, false precision, or exam-success prediction is displayed.

## IQraMentor architecture, privacy and APIs

One orchestrator in `tutor_agent.py` handles authentication → integrity guard → bounded performance context → optional released question review → Vertex AI → structured response/history. The model has no database credentials, arbitrary tools, URL fetcher, or ability to execute queries. Approved reads are implemented by `performance`, `benchmark`, and `review` with server-derived identity.

Model configuration: `VERTEX_MODEL_TUTOR`, falling back to existing `VERTEX_MODEL_PRIMARY`, then `gemini-3.5-flash`; existing `GCP_PROJECT_ID` and `GCP_REGION`. Provider timeout is 30 seconds, maximum output is 1500 tokens, temperature 0.2. Six bounded conversation messages are included. Personal metrics are computed by the backend. A stable system prompt prohibits invented learner facts, cross-user data, integrity overrides, and unsupported ranks. Provider failures return a clearly labelled deterministic evidence summary, without exposing provider errors or secrets.

- `GET /api/tutor/insights`: bounded learner performance/report context; exam, subject, difficulty, type, attempt-count and date-range filters.
- `POST /api/tutor/chat`: strict input schema; optional owned conversation, released attempt and question; returns message, recommendations, report and data period.
- `GET /api/tutor/sessions`: latest 30 owned conversations.
- `GET /api/tutor/sessions/{id}`: latest 40 owned messages.

Every route resolves identity from the authenticated cookie. Chat writes require the existing CSRF token. Client identity fields are rejected. All conversation queries enforce ownership, and administrators are denied tutor APIs rather than given an override. Cross-user attempts/questions return 404. Anonymous API access returns 401; the UI shows a sign-in prompt and never requests personalized endpoints.

All `IN_PROGRESS` sessions block tutor reads and writes, including chat history. There is no existing explicit policy permitting practice tutoring, so the default fails closed. The guard runs again after model generation to detect an exam started during that request. Review data is available only after immediate release or exam closure under AFTER_EXAM_CLOSE. Hidden answer snapshots never enter tutor context. Eight messages per learner per minute are allowed; requests are reserved before provider calls so failures count toward the limit. Simultaneous requests can marginally exceed this soft rate limit.

Migration `0005_tutor` adds private `tutor_sessions` and `tutor_messages` tables and indexes for ownership/history and `(user_id, submitted_at)` attempt reads. It is additive and supports the existing PostgreSQL adapter and SQLite initialization. Existing questions, exams and scores are not rewritten.

## Chat, reports and proactive insights

`static/mentor.js` supplies a 420px desktop drawer and a mobile drawer with internal conversation scrolling, accessible labels, Escape dismissal, history, new-chat control, starter prompts, and a structured in-app report. User/model content is rendered as text, never injected as HTML. Reports include recent performance, strengths, gaps, difficulty, elapsed timing, trend, benchmark, readiness status, recommendations and the seven-day plan. No PDF is generated.

`static/performance-workspace.js` integrates dashboard insights, learner analytics filters, released-attempt cards, practice navigation and contextual tutor prompts. Result and question-review buttons carry attempt/question IDs which are independently checked by the server. Administrators retain existing platform analytics and never see student chat history.

## Validation

- 88 backend tests pass: all 74 existing tests plus 14 tutor tests.
- New coverage includes anonymous/CSRF rejection, no-history learner, grounded gaps, small samples, active exams, result release, question ownership, cross-user session/attempt requests, admin denial, strict identity input, bounded filters, stored history, rate limits, provider failure, an exam started during generation, snapshot metadata and benchmark threshold/math/query execution.
- Both existing Node UI suites pass; edited JavaScript syntax and Python compilation checks pass.
- Chromium audit: student dashboard, available exams, my exams, results, Performance Lab, profile; administrator dashboard, Question Bank, AI generation, upload/digitization, exam generation, management, results and Performance Lab at 1440×900, 820×1180 and 390×844. After fixes: zero uncaught JavaScript errors and zero document horizontal overflow across 42 combinations. Tables intentionally allow local scrolling.
- 45 screenshots captured locally, including desktop/mobile mentor and anonymous sign-in state. Live Vertex AI generated a response grounded in the synthetic learner history.
- A baseline checkout at `d5ca886` was run against a copy of the same synthetic database for the before/after comparison.
- New standalone browser audit: `tests/validate_workspace_ui.py`. It only permits localhost targets and creates synthetic exam fixtures. Playwright is an optional local QA dependency, not a production dependency.

## Local startup

Normal application: `./run_local.sh` (existing Google authentication configuration applies).

Isolated UI test server:

```sh
QB_DATA_DIR=/tmp/meritiqra-ui-validation APP_ENV=development AUTH_MODE=mock \
ADMIN_EMAILS=admin@example.test APP_BASE_URL=http://127.0.0.1:8018 \
.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8018
```

Then run `.venv/bin/python tests/validate_workspace_ui.py`. Never enable mock authentication on a deployed service.

## Files

Created: `performance_service.py`, `tutor_agent.py`, `migrations/versions/0005_tutor.py`, `static/workspace-density.css`, `static/performance-workspace.js`, `static/mentor.js`, `tests/test_tutor.py`, `tests/validate_workspace_ui.py`, and this report.

Modified: `app.py`, `platform_api.py`, `exam_conduct.py`, `static/index.html`, `static/home.html`, `static/app.js`, `static/platform-ui.js`, `static/public-site.css`, `.dockerignore` (retain the tracked public logo in the image).

## Remaining limitations

No reliable syllabus coverage, per-question timing, national/state/institution cohort metadata, or tutoring-permitted practice policy exists yet. Readiness and unsupported comparisons stay unavailable. Older snapshot metadata fallback reflects current taxonomy. The existing admin-wide analytics path is unchanged; the bounded query improvements target learner/tutor traffic. Chat is retained in the application database; automated retention/deletion UI is not part of this delivery. Google OAuth/proctor-device interaction and real-student Gemini quality require authenticated production acceptance; automated tests use synthetic learners. LLM prose can be imperfect; the structured report remains the source for exact figures.

Deployment record is appended after Cloud Run verification.
