# Grand Test PDF workspace verification

Implemented using the user's expected/existing UI screenshots as references. Both pages now instantiate `createPdfDigitisationWorkspace` in `static/pdf-viewer.js`. Grand Test mounts a clone of the original toolbar/page-container markup with instance-scoped element lookup and state. It uses the original page rendering, CSS, normalized coordinate calculations, pointer capture, overlays, zoom, image retry, selection and digitisation handlers.

Grand Test retains its authenticated page URLs, revision checks, background digitisation, metadata review, Operator ownership and Admin-only generation/scheduling/publishing. Its backend already delegates to `digitise_pdf_crop` and `parse_pdf_paper`; no parallel extraction pipeline was added.

## Changes

- `static/pdf-viewer.js`: extracted instance-based shared workspace and mounting adapter; added shared zoom in/out and fit-width buttons; scoped selection cleanup; redraw removes only the latest selection, including selections drawn out of page order; tiny/cancelled draws preserve committed selections; added clear-all.
- `static/grand-tests.js`: consumes shared workspace; removed single-page navigation/rendering, independent zoom, drawing handlers and selection state; restored direct PDF upload/open alongside existing document-library flow.
- `static/grand-tests.css`: removed obsolete viewer CSS and prevented Grand Test form-label styling from changing shared toolbar layout.
- `static/index.html`: updated script cache versions.
- `tests/test_pdf_selection.cjs`: adapted helper loading for shared factory.
- `tests/test_grand_tests.py`: permission fixture now uses the existing Operator allowlist requirement.
- `tests/validate_grand_tests_ui.py`: browser coverage for both viewers, Admin/Operator, zoom/scroll coordinates, multiple portions, redraw, digitisation, review, scheduling and publication.

Pre-existing uncommitted changes were preserved. No new framework, PDF renderer, or backend digitisation implementation was introduced.

## Acceptance status

These checks use a real two-page PDF, real Chromium pointer/scroll interactions and real local API endpoints. AI extraction/classification responses are mocked. A passing digitisation check verifies request routing, batch contents and result handling, not production AI accuracy.

- [x] Scrollbar works (vertical and horizontal overflow verified).
- [x] Zoom In works.
- [x] Zoom Out works.
- [x] Fit Width works (the existing fit mode; Fit Page was not previously supported).
- [x] Portion Selection works.
- [x] Draw Portion Selection works.
- [x] Multiple selections work.
- [x] Redraw works without removing unrelated selections.
- [x] Digitalise Selected Portions works with mocked extraction.
- [x] Multiple selected portions are submitted in one operation.
- [x] Whole PDF Digitise works with mocked extraction.
- [x] Selection coordinates work after zoom (submitted coordinates compared with drawn bounds).
- [x] Selection coordinates work after scrolling (correct page and normalized bounds verified).
- [x] Grand Test uses shared Upload & Digitise behavior/components.
- [x] Operator permissions work (browser interaction plus backend ownership/access tests).
- [x] Generate Exam is Admin-only (UI and backend checks).
- [x] Existing Upload & Digitise passes targeted browser regression checks, including both digitisation actions.
- [ ] Entire existing application remains unaffected: only targeted regressions were tested. An unrelated pre-existing `NameError: idx` occurs in `app.py::_sample_exam_questions` when the sample endpoint uses fallback questions; confirmed present in HEAD.

Full acceptance remains incomplete: production AI extraction and the entire application have not been validated. The user's 76-page document was shown in screenshots but its PDF was not supplied; browser checks used a two-page fixture.

## Checks run

- `node --check static/pdf-viewer.js`
- `node --check static/grand-tests.js`
- `node tests/test_pdf_selection.cjs` — passed.
- `.venv/bin/python -m pytest tests/test_grand_tests.py tests/test_pdf_crop.py tests/test_pdf_preview.py tests/test_admin_workspace.py tests/test_crud.py -q` — 20 passed.
- `.venv/bin/python -m tests.validate_grand_tests_ui` — passed; unrelated sample endpoint diagnostic noted above.
- `git diff --check` — passed.

Desktop screenshots of both shared viewers were inspected and compared against the supplied expected layout. Mobile scheduling/publishing and page overflow were also checked. No deployment was performed.
