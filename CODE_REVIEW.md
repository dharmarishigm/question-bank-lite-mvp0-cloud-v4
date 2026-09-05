# Codebase review — 2026-09-05

Reviewed the first-party Python modules, browser JavaScript/HTML/CSS, tests, launch scripts, Dockerfile, configuration templates, and documentation. Vendored KaTeX internals and user documents were not audited. This is an offline code review, not a live cloud or browser integration certification.

## Changes and validation

- Updated the existing `.env` with all nine requested settings, preserving unrelated settings. The project and processor values are now the requested placeholders, replacing the existing values. `.env` is already in `.gitignore`.
- All 27 existing unittest tests passed using a temporary `QB_DATA_DIR`, without modifying the question database or making paid cloud calls.
- `node --check static/app.js` passed. Python syntax parsing passed for all application and test modules.
- Additional temporary reproductions confirmed deletion failure, stale verification, rejected generated asset URLs, text parsing corruption, spreadsheet shared-string corruption, column interleaving, and benchmark/math-check blind spots.
- Application logic has not been changed as part of this analysis.

## Architecture

The browser calls a single FastAPI application. SQLite stores questions, source document metadata, extraction runs, and pre-edit snapshots. Original files and rendered crops live on disk.

`app.py` handles uploads, local text/Office parsing, persistence, CRUD, import/export, and extraction orchestration. `pdf_import.py` performs local PDF segmentation, OCR fallback, and crop creation. `llm_extract.py` batches source pages for Vertex transcription, merges local fields, obtains source regions, and verifies individual questions. `gcp_documentai.py` supplies OCR/formula evidence. `verification.py` computes heuristic comparisons and statuses; `multimodal.py` builds content blocks and crops. `ocr.py` implements formula and page OCR backends. `static/app.js` implements editing, review, cropping, and rendering. `golden_benchmark.py` is the separate live evaluation runner.

Useful foundations include parameterized SQL, transactional batch imports, additive schema migrations, source hashes, retained original files, lazy cloud imports, and explicit extraction uncertainties. The main weaknesses are fidelity guarantees across UI transitions, parser edge cases, and missing integration coverage.

## Priority findings

### 1. Generated source and visual images disappear in the UI — high

Location: `static/app.js:28`; generated names in `multimodal.py:106` and `llm_extract.py:220`.

`safeUrl()` permits only hexadecimal characters, punctuation, and underscores in local upload filenames. Generated names such as `/uploads/q1-source-abcdef.png` and `/uploads/q1-diagram-abcdef.png` contain other letters and are rejected. Both returned an empty string in reproduction. This removes evidence from cards, visual assets, and source selection.

Fix: allow the actual generated filename format while retaining the `/uploads/` restriction and rejecting traversal.

### 2. Deleting a previously edited question fails — high

Location: `app.py:108`, `app.py:459`, `app.py:474`.

Editing inserts a `question_versions` record. Its foreign key has no cascade, and deletion removes only the parent question with foreign keys enabled. Create → edit → delete reproduced `IntegrityError: FOREIGN KEY constraint failed`. The UI also ignores the DELETE response status.

Fix: explicitly choose a version retention policy and implement transactional deletion or soft deletion; report failures in the UI.

### 3. Ordinary two-column papers are interleaved — high

Location: `pdf_import.py:137`.

Both the short-page branch and `flush_band()` sort by vertical position, interleaving left and right columns. A synthetic page with six lines per column produced `L0,R0,L1,R1,...`. On conventional column-first exam layouts, the next column's question can interrupt the current question and capture its remaining options. Existing ordering tests do not check complete question content on this layout.

Fix: detect column-first versus row-first layouts and test reconstructed questions and options, not just relative question labels.

### 4. Text/Office AI extraction reaches image-only processing — high

Location: `app.py:691`, `llm_extract.py:446`, `llm_extract.py:484`.

Text-like files are sent through `extract_source(..., 'text/plain', ...)`, but subsequent source handling assumes renderable PDF/image bytes. Local text segments have no image. The fallback calls `_render_page_image()`, which attempts to open plain text with Pillow. Model region cropping also requires an image. Thus even successful transcription cannot complete this path normally. Most text-path exceptions are silently replaced with local output without an AI-failure warning.

Fix: implement a text-specific verification/evidence path or convert supported Office documents into a renderable representation. Surface fallback reasons consistently.

### 5. Verification is not tied to the saved content — high

Location: `app.py:459`, `static/app.js:817`, `static/app.js:927`.

The API accepts an edited statement with the previous `VERIFIED` status and confidence unchanged; reproduced directly. Normal editor saves change extracted items to `HUMAN_REVIEWED`, but OCR insertion mutates a draft without setting `human_modified`, so its previous verification can survive import. Crop digitization assigns `HUMAN_REVIEWED` automatically even when extraction returns failed/unverified content. Selecting an include checkbox also marks a draft human-modified through the generic input listener.

Fix: invalidate verification on semantic changes server-side; bind evidence to a content hash/version and record human approval as an explicit action.

### 6. Editing silently drops options beyond F — high

Location: `static/app.js:88`, `static/app.js:130`.

Extraction accepts up to 12 options and the import review supports 12. The main editor reads and writes only six. Opening and saving a question with seven or more options discards the remainder. The editor type selector also omits `assertion_reason`, `paragraph`, and `other`, so it cannot round-trip all supported types.

Fix: dynamically render all options and support the complete shared question-type enum.

### 7. Plain-text parsing merges questions and mistakes prose for options — high

Location: `app.py:527`, `app.py:548`.

Question splitting depends on blank paragraphs. Two numbered questions separated only by newlines reproduced one question. The option pattern accepts a single letter followed by a space: `A particle moves at speed v.` became an option and lost its leading article in the statement. DOCX extraction emits XML text runs on separate lines without reliable paragraph structure, which further exposes this issue.

Fix: segment on explicit question-start lines and require unambiguous option delimiters, retaining paragraph/run structure for DOCX.

### 8. XLSX import replaces shared strings with numeric indexes — high

Location: `app.py:290`.

The shared-string table is read but never resolved. A cell pointing to `Question text` reproduced output `0`. Inline strings and sheet/cell structure are also omitted. Legacy `.doc`, `.ppt`, and `.xls` are accepted but simply decoded as UTF-8 bytes rather than parsed.

Fix: implement actual format readers and reject unsupported formats with a clear message.

### 9. Docker builds include local configuration and user data — high when distributing images

Location: `Dockerfile:6`.

`COPY . .` is used with no `.dockerignore`. The build therefore includes `.env`, the question database, original documents, crops, and the local virtual environment. `.gitignore` does not exclude Docker build context files.

Fix: add a `.dockerignore` or copy only required runtime source/assets, and supply configuration and data at runtime.

### 10. A segmentation warning can downgrade FAILED to REVIEW — high

Location: `llm_extract.py:490`.

After `status_from()` assigns `FAILED` for critical mismatches, the segmentation-disagreement branch unconditionally assigns `REVIEW`. A question absent from local segmentation can therefore display a less severe status despite critical verifier issues.

Fix: compute final status after collecting all issues and preserve critical-failure precedence.

## Additional findings

11. **Scientific comparison misses changed values** (`verification.py:34`). `formula_matches_candidate('x^2=4', 'x^2=9')` returned true because any matching token within each category is sufficient. This is a weak secondary check, not evidence of formula equivalence. Compare complete normalized token structures and add changed-sign/value/exponent examples.

12. **Benchmark misses verified wrong answers** (`golden_benchmark.py:45`). `answer_ok` is calculated but omitted from `silent_verified_errors`. A VERIFIED question with the wrong answer reproduced zero silent errors. Extra questions and solutions/visuals are also outside the failure criteria, and an empty corpus exits successfully. Add explicit acceptance criteria for all claimed fidelity dimensions.

13. **Toolbar action buttons enter the snippet handler** (`static/app.js:316`). Upload document and Digitize image are inside `.toolbar` but have neither `data-upload` nor `data-snippet`. Their click bubbles into `insertSnippet(..., undefined)`, which can append the literal `undefined` before failing on `text.length`. Only dispatch recognized snippet buttons.

14. **Digitize image keeps only the first extracted question** (`static/app.js:383`). It announces the full question count but copies only `questions[0]`, without updating extraction/provenance metadata. Additional questions are inaccessible through this action, and editing an existing item can retain its old metadata. Route multiple results through the review list and replace metadata consistently.

15. **Crop digitization leaves stale editable fields** (`static/app.js:612`). It replaces `parsed[idx]` and refreshes the preview but does not rebuild the textareas/options. Subsequent editing or OCR insertion can restore pre-crop text. Crop boxes are relative to an existing question crop but are stored as if they were source-page coordinates. Regenerate fields and preserve the coordinate transform and original page identity.

16. **The list stops at 200 questions without pagination** (`static/app.js:201`, `app.py:394`). The API reports a total but defaults to 200 returned rows; the UI never sends an offset or renders page controls. Older questions cannot be browsed or printed from the unfiltered list. Add pagination and clarify print scope.

17. **Saving one draft does not remove it from bulk import** (`static/app.js:953`). A saved draft remains selected, and its Save button is re-enabled after 1.5 seconds. Subsequent bulk save or repeated single save inserts duplicates. Track imported IDs and make repeated saves idempotent or explicit.

18. **Preview confirmation survives text edits** (`static/app.js:287`). Textarea input updates the preview without clearing `previewConfirmed`; non-textarea controls do clear it. Snippet insertion also does not invalidate confirmation. Reset confirmation consistently when editable content changes.

19. **Markdown links bypass URL validation** (`static/app.js:67`). A `javascript:` destination is emitted into an anchor unchanged; confirmed by evaluating the renderer. HTML escaping does not validate URL schemes. Restrict link and image schemes. Browser execution of this case was not tested.

20. **Resource limits are applied too late** (`app.py:497`, `app.py:662`, `llm_extract.py:392`). Uploads are fully read before checking size. The page limit is checked only in the AI path, after local PDF rendering/OCR has already run. ZIP contents are decompressed without a bound. Repeated parses retain crops even if import is cancelled. Bound reads, decompression, pages, and render dimensions before processing; define cleanup for abandoned runs.

21. **Source coverage is not independently checked** (`llm_extract.py:444`). Existing local segments take precedence unless the local item is flagged garbled, even if Gemini identifies additional continuation pages. Region/crop failures can be silently skipped; visual fallback always uses the first question image, which may be the wrong page. Preserve the union of required pages, flag failed crops, and select page-matched fallbacks.

22. **Configuration status means values are present, not service readiness** (`llm_extract.py:102`, `gcp_documentai.py:42`). Placeholder IDs report available, and credentials/API access/model availability are not validated. Forced formula OCR backends also report available without checking dependencies. Distinguish configured from operational status. The requested model string was preserved, but model/region support was not tested.

23. **Confidence is presented as measured correctness** (`static/app.js:443`, `static/app.js:506`). The displayed percentage is a model-provided score modified by hand-written penalties, without calibration data. Label it verification confidence and reserve accuracy claims for measured benchmark results.

## Testing and maintainability

The existing suite is small and offline. It covers selected PDF helpers, extraction schemas/chunking, content blocks/crops, and verification helpers. It does not cover browser workflows, CRUD/version deletion, full text/Office AI flows, Document AI response parsing, or multi-step import/edit/save behavior. Some tests import `app` and invoke persistence without isolating storage themselves; the review runner supplied temporary storage externally.

Runtime dependencies are unpinned, there is no separate reproducible development/test dependency setup, and launch scripts install only when the virtual environment is first created. The application also initializes/migrates SQLite at module import. These choices make upgrades and test isolation harder. The local-only/no-authentication scope is explicit in the README; it should not be represented as a production deployment solely because GCP is configured.

Prioritize source-image rendering, deletion, column/text parsing, verification invalidation, and option preservation first. Then address Office processing, Docker context isolation, remaining UI state transitions, and benchmark coverage. Re-run the offline suite with focused regression tests; use a labeled live corpus before making extraction-accuracy claims.
