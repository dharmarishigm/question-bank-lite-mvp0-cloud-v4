# Prompt Registry and DigitalIQBank Code Playbook

## 1. Refined product requirement

### 1.1 Configurable system prompts

Every AI system instruction used by the product must be stored in a central Prompt Registry rather than embedded in application code.

An Administrator must be able to:

- View prompts grouped by purpose and scope.
- Read a well-formatted preview of the prompt.
- Create a draft from an existing version, edit it, compare versions, and add a change note.
- Mark exactly one version as `ACTIVE` for each prompt purpose and scope.
- Retire or roll back to an earlier valid version without deleting history.
- See where a prompt is used and which model runs used each version.

Runtime AI calls must always resolve and use the Administrator-marked `ACTIVE` prompt. A missing or ambiguous active prompt is a configuration error: the AI operation must stop safely and tell the Administrator what must be configured. Runtime code must not silently fall back to a hard-coded business prompt.

Prompt versions are immutable after creation. Editing means creating a new `DRAFT` version. Activation is an explicit, audited Admin action. Every AI run stores the resolved prompt version ID, content hash, model, parameters, scope, and a frozen effective-prompt snapshot.

### 1.2 DigitalIQBank flow

The primary journey is:

`DigitalIQBank → Create workspace → Select PDF portion or whole document → Digitise → Side-by-side review → Save reviewed questions to Question Bank → Create exam from selected saved questions`

The review experience must use the same interaction and rendering standard as **Upload & Digitise**:

- Original PDF/image evidence on the left.
- Editable structured question on the right.
- A live, typeset preview of question text, options, answer, solution, LaTeX, chemical notation, tables, and supported symbolic content.
- Clear extraction confidence, verification issues, missing-data warnings, and review state.
- Page navigation, zoom, selection overlay, and source-region highlighting remain available during review.

Saving and finalizing are distinct actions. Only explicitly reviewed questions may be saved to the Question Bank. After at least one question has been saved, the workspace offers **Create exam with selected questions**. The exam must be created from the selected saved Question Bank IDs—not implicitly from every extracted item.

## 2. Current repository baseline

Reuse the existing implementation rather than creating a second workflow:

- `blueprint_prompts` already provides immutable, per-purpose versions for Program blueprints.
- `llm_extract.py` contains transcription and verification prompts, but they are hard-coded.
- `llm_generate.py`, `tutor_agent.py`, `blueprint_gemini.py`, `blueprint_setup.py`, `flag_api.py`, `epidemiology_model.py`, and parts of `app.py` also contain runtime prompt text.
- `grand_tests.py` and `static/grand-tests.js` already implement the DigitalIQBank workspace lifecycle, selected-portion digitization, review, Question Bank saving, finalization, and exam generation.
- The shared Upload & Digitise viewer and KaTeX rendering utilities already exist in the web application.

The implementation should generalize the prompt mechanism and converge the two review interfaces; it should not fork either feature.

## 3. Prompt Registry architecture

### 3.1 Data model

Add global registry tables through an Alembic migration. Do not overload `blueprint_prompts`, because that table is Program-specific and has narrower lifecycle semantics.

#### `prompt_definitions`

| Column | Meaning |
|---|---|
| `id` | Stable prompt identity |
| `key` | Unique machine key, for example `DIGITIZE_TRANSCRIBE` |
| `name` | Admin-facing name |
| `description` | Purpose and usage guidance |
| `scope_type` | `GLOBAL` or `PROGRAM` initially |
| `created_by`, `created_at` | Audit fields |

#### `prompt_versions`

| Column | Meaning |
|---|---|
| `id`, `prompt_definition_id` | Version identity |
| `scope_id` | Null for global; Program ID for Program override |
| `version_number` | Monotonic within definition and scope |
| `status` | `DRAFT`, `ACTIVE`, or `RETIRED` |
| `system_content` | System instruction sent separately to the model |
| `change_note` | Required author note |
| `content_hash` | Integrity and deduplication hash |
| `created_by`, `created_at` | Author audit |
| `activated_by`, `activated_at` | Activation audit |

Database constraints must guarantee one active version per `(prompt_definition_id, scope_id)`. Versions must never be updated in place except for lifecycle metadata during an atomic activation transaction.

#### `prompt_run_bindings`

| Column | Meaning |
|---|---|
| `run_type`, `run_id` | Owning AI operation |
| `prompt_version_id` | Resolved immutable version |
| `effective_content_hash` | Integrity check |
| `effective_prompt_snapshot` | Frozen rendered system prompt |
| `model`, `parameters_json` | Reproducibility data |
| `created_at` | Execution time |

If an existing run table already owns equivalent fields, add `prompt_version_id` and preserve its current provenance columns rather than duplicating records unnecessarily.

### 3.2 Initial prompt keys

Seed the exact current production content as version 1, then activate it during migration/bootstrap:

- `DIGITIZE_TRANSCRIBE`
- `DIGITIZE_VERIFY`
- `QUESTION_GENERATE`
- `QUESTION_GUIDANCE`
- `TUTOR_EXPLAIN`
- `IQRA_MENTOR`
- `BLUEPRINT_ANALYZE`
- `BLUEPRINT_SETUP`
- `BLUEPRINT_REFINE`
- `QUESTION_AUTHOR`
- `INDEPENDENT_SOLVE`
- `FLAG_MENTOR`
- `EPIDEMIOLOGY_FORECAST`

The inventory must be confirmed with a repository scan before merging. Any text passed as `system_instruction`, or serving the same privileged behavioral role, belongs in this registry.

### 3.3 Runtime resolver

Create one service, for example `prompt_registry.py`, with a small API:

```python
resolved = resolve_active_prompt(
    key="DIGITIZE_TRANSCRIBE",
    program_id=program_id,
    actor=user,
)
```

Resolution order is:

1. Active Program-scoped override, when the operation has a Program.
2. Active global version.
3. Fail with a typed `PromptNotConfigured` error.

The resolver returns version ID, content, hash, and scope. The caller passes `content` only through the provider's dedicated `system_instruction` field. Source documents, selected text, metadata, and user-entered instructions remain in the user/content channel and must never be interpolated into the system prompt.

The run and its prompt binding must be persisted before or atomically with dispatch. Retries reuse the frozen version from the original run; they must not pick up a newly activated prompt halfway through a job.

### 3.4 Admin API

Add Admin-only routes:

```text
GET    /api/admin/prompts
GET    /api/admin/prompts/{key}
POST   /api/admin/prompts/{key}/versions
GET    /api/admin/prompts/{key}/versions/{version_id}
POST   /api/admin/prompts/{key}/versions/{version_id}/activate
POST   /api/admin/prompts/{key}/versions/{version_id}/retire
GET    /api/admin/prompts/{key}/compare?from={id}&to={id}
GET    /api/admin/prompts/{key}/usage
```

Creating a version requires the last known version number to enforce optimistic locking. Activation must atomically retire the previous active version, activate the chosen version, and write an audit event. Non-Admins receive `403`. Prompt content must never be exposed through learner or Operator APIs.

### 3.5 Admin Prompt Registry UI

Add a dedicated **Prompt Registry** Admin navigation item—not a textarea hidden inside an AI-generation form.

The index view shows name, key, scope, active version, last changed by/at, and usage locations. The detail view provides:

- A readable rendered view with headings, lists, tables, code blocks, preserved whitespace, and safe escaping.
- A separate plain-text editor for a new draft.
- Side-by-side or unified version diff.
- Draft, activate, retire, and rollback actions with explicit confirmation.
- An “effective prompt” panel showing the resolved Global/Program version without exposing secrets or user data.

Render prompt Markdown through the application's safe renderer. Never inject raw prompt HTML. Long prompts need a table of contents, line wrapping, copy action, and full-screen reading mode. The editor and rendered preview must be visually distinct so an Admin cannot confuse previewing with saving.

## 4. DigitalIQBank review implementation

### 4.1 Shared review component

Extract the mature Upload & Digitise comparison UI into a shared component, for example:

```text
static/question-source-review.js
static/question-source-review.css
```

Both Upload & Digitise and DigitalIQBank must mount this component. Its input contract should include:

```javascript
{
  source, pages, sourceRegions, question,
  editable, issues, confidence,
  onChange, onReviewedChange
}
```

Do not duplicate rendering logic in `static/grand-tests.js`.

### 4.2 Review layout and rendering

Desktop uses a resizable two-column layout:

| Original source | Structured question |
|---|---|
| PDF/image page, zoom, page navigation, highlighted crop/region | Edit fields plus live rendered preview |

On narrow screens the panes become explicit **Source** and **Question preview** tabs; do not squeeze both panes below a usable width.

Every editable field that may contain notation has a rendered counterpart. Use the existing safe `renderInto`/KaTeX path. Support `$...$`, `$$...$$`, escaped LaTeX, and the application's supported chemistry notation. A rendering failure must show the raw source and a localized warning; it must not blank the question or block correction.

The evidence pane should automatically navigate to and highlight the question's `source_regions`. When exact regions are missing, show the source page and a “region unavailable” warning rather than pretending there is a precise match.

### 4.3 Review state

The **Reviewed** checkbox becomes invalid whenever a material field changes after review. Material fields include statement, options, answer, solution, classification, program, and advanced content. The Admin/Operator must re-check it after seeing the updated rendered preview.

Persist at least:

- `reviewed`
- `reviewed_by`
- `reviewed_at`
- `reviewed_payload_hash`
- source document and source region references
- transcription prompt version and verifier prompt version
- extraction/verification issues and confidence

The backend, not only JavaScript, verifies that the submitted hash still matches the reviewed payload before saving.

### 4.4 Save to Question Bank

Keep **Save selected questions** and **Save all reviewed questions**. Both actions:

- Accept explicit workspace question IDs.
- Reject unreviewed, incomplete, stale, or already-saved selections safely.
- Save atomically and idempotently.
- Return the mapping from workspace question ID to Question Bank ID.
- Preserve source evidence and prompt/run provenance on the saved question.

The UI must clearly label saved items and keep unsaved items editable.

### 4.5 Create exam from selected saved questions

Once the workspace contains saved questions, show a persistent action:

**Create exam with selected questions**

The Admin selects only saved questions, reviews the selection count and total marks, and enters exam metadata. The request contains explicit Question Bank IDs and their display order.

Suggested route:

```text
POST /api/grand-tests/{workspace_id}/exams
```

Suggested body:

```json
{
  "revision": 12,
  "question_ids": [101, 108, 109],
  "name": "Algebra Revision Test",
  "duration_minutes": 45
}
```

Backend rules:

- Admin only.
- Every ID must be a saved question linked to this workspace.
- At least one question is required; duplicates are rejected.
- Display order follows the submitted list.
- Creation is transactional and idempotent under a client request key.
- The resulting exam starts as `DRAFT` and opens in the existing Exam Admin review/scheduling flow.

This replaces the current all-questions implication in `POST /api/grand-tests/{gid}/generate`. Keep the old route temporarily as a compatibility adapter, then remove it after UI and callers migrate.

## 5. Delivery sequence

### Phase 0 — inventory and characterization

- Inventory every privileged prompt and its caller.
- Add characterization tests proving the exact current prompt text and runtime behavior.
- Record the existing Upload & Digitise review DOM/rendering contract.

### Phase 1 — Prompt Registry foundation

- Add migration, seed definitions/version 1, resolver, audit events, and Admin API.
- Migrate `llm_extract.py` and `llm_generate.py` first because they are directly involved in this requirement.
- Persist prompt bindings on extraction, verification, and generation runs.
- Remove migrated prompt constants only after seed parity tests pass.

### Phase 2 — Prompt Registry UI

- Build list, detail, readable preview, draft editor, diff, activation, rollback, and usage views.
- Add authorization, optimistic-locking, accessibility, mobile, and XSS tests.

### Phase 3 — shared side-by-side reviewer

- Extract the Upload & Digitise reviewer into the shared component.
- Reconnect Upload & Digitise without behavior changes and pass its existing regression suite.
- Mount the same component in DigitalIQBank and add live notation preview and source-region navigation.

### Phase 4 — selected-question exam creation

- Add reviewed-payload hashes and provenance persistence.
- Add the explicit saved-question selection API and UI.
- Open the created draft in Exam Admin; preserve the existing scheduling/publishing workflow.

### Phase 5 — remaining prompt migration and cleanup

- Move tutor, Program, FLAG, and forecasting prompts into the registry.
- Add a CI guard that fails when new production Python/JavaScript introduces direct system-prompt constants or literal `system_instruction` content outside approved bootstrap fixtures.
- Remove compatibility adapters after usage confirms no remaining callers.

## 6. Test and acceptance matrix

### Prompt Registry

- Admin can create a draft; Operator and Student cannot read or mutate registry content.
- Two concurrent edits cannot produce conflicting version numbers.
- Exactly one active Global or Program-scoped version exists per prompt key.
- Activation and rollback are audited.
- An AI request uses the active Admin-selected version and stores its version ID/hash/snapshot.
- A retry uses the original frozen version after a newer version is activated.
- Missing active configuration fails closed; no hard-coded fallback is used.
- Prompt preview safely renders Markdown-like content, long lines, code, LaTeX text, and malicious HTML.

### DigitalIQBank

- User can create a workspace from an allowed Program PDF.
- User can digitise one crop, multiple selections, or the whole PDF.
- Review shows original evidence and live rendered content side by side.
- Mathematical and symbolic notation is visually typeset in statement, options, answer, and solution.
- Invalid LaTeX shows raw content and a warning without losing edits.
- Editing a reviewed question clears its reviewed state.
- Backend rejects a payload changed after review.
- Only selected reviewed questions are saved; repeated submission does not duplicate them.
- Exam creation accepts only selected saved questions belonging to the workspace and preserves order.
- Created exam is a draft visible in Exam Admin and follows existing review, schedule, and publish controls.
- Desktop and mobile browser tests cover comparison, save selection, exam creation, and navigation back to the workspace.

### Regression and release gates

- Existing Upload & Digitise browser tests remain green after component extraction.
- Existing DigitalIQBank authorization, availability, page-status, optimistic-locking, and publishing tests remain green.
- SQLite and PostgreSQL migration tests pass from a clean database and from the current production revision.
- Python tests, JavaScript syntax checks, browser acceptance, migration validation, and `git diff --check` pass.

## 7. Definition of done

The requirement is complete only when:

1. No in-scope runtime system prompt is owned by business code.
2. Every AI operation resolves an Admin-activated version and records immutable provenance.
3. Admins can safely read, draft, compare, activate, retire, and roll back prompt versions.
4. DigitalIQBank review provides the same shared source-versus-result experience as Upload & Digitise, including rendered LaTeX/symbolic notation.
5. An Admin can create a draft exam from an explicit subset of reviewed, saved workspace questions.
6. Authorization, audit, concurrency, rendering, migration, and end-to-end tests pass in both supported databases and responsive layouts.

## 8. Workspace, Program, and exam lifecycle controls

- Admins and Operators can delete their accessible DigitalIQBank workspaces while no exam is attached. A workspace with a generated exam is protected until the exam is deleted.
- The Programs workspace exposes the existing `DELETE /api/programs/{program_id}` archive/delete action to Admins; version and audit history are retained.
- Exam Admin exposes the existing Admin-only exam delete action. Exams with registrations, attempts, or pending registrations are protected and must be closed/archived instead.
- Learner catalogs expose only `OPEN` exams that are publicly self-registerable or explicitly enrolled for that learner. Draft, archived, and admin-only `PUBLISHED` papers are not exposed through learner APIs. Admins and proctors retain full visibility.
