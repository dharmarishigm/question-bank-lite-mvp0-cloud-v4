# Homepage identity and web regression fixes

The homepage now resolves `/api/auth/me` without caching personal data in public HTML. Signed-in users see their display name and Student/Admin role, with email, dashboard and sign-out actions in an account menu. Guest login controls remain available to anonymous visitors. Public authentication configuration now parses the JSON response correctly.

PDF investigation found production upload requests succeeding (200) while stored-page rendering failed (400). A directly inspected source object was intact: 2,052,897 bytes, 36 pages, with a renderable first page. Stored PDFs now use a bounded Python byte read and PyMuPDF stream opening, with canonical source-directory fallback, rather than direct file opening on the mounted storage. Re-uploading a deduplicated source restores a missing local file. Missing sources produce a clear re-upload instruction. Page responses are private/no-store.

Digitization results are placed inside the upload workspace and scrolled into view. OCR-status loading no longer prevents an already extracted result from rendering. The original source preview remains available. Live synthetic testing uploaded and rendered a three-page PDF and successfully digitized it through the existing Gemini extraction/verification pipeline.

Telugu explanation normalization unwraps nested prose arrays/objects and fenced or double-encoded JSON without stripping mathematical braces. Telugu generation has an 8,192-token allowance to reduce truncation. Incomplete JSON produces a retryable error instead of raw JSON in the lesson. Live Telugu generation returned valid structured content and rendered Telugu text. The explanation hero is no longer sticky, its blue background has been replaced by a compact pale panel, and modal stacking prevents the site menu or assistant from covering the explanation.

Admin/AI layouts use aligned responsive question-card grids, compact explanation sections and larger mobile menu touch targets. Four-option cards use two columns where appropriate. PDF review content no longer behaves like a page-covering overlay.

Browsers without a Fullscreen API (including affected iPhone Safari versions) use labelled exam focus mode with the same server session, timer and scoring. This does not claim to hide browser chrome when iOS does not provide that capability. Browsers that support fullscreen continue requesting it. Unsupported fullscreen does not generate a spurious fullscreen-exit violation.

Validation: 91 backend tests pass; both existing Node UI suites pass. Added regressions cover restoring missing PDF source bytes and Telugu structured-text normalization. The baseline had one stale assertion for an old asset-version string introduced by the previous cache-busting deployment; it now checks that the workspace loads a versioned platform script. Browser tests cover Admin/Student homepage identity, phone overflow, menu visibility, three-page PDF rendering, real digitization, real Telugu explanations and the no-Fullscreen-API exam start path. Evidence screenshots are in `/tmp/meritiqra-webfix-evidence` on the development machine. Physical iPhone hardware was not available.

These web fixes are delivered before the larger Android addition; Android work continues separately on the same Codex feature branch.

## Deployment verification

Commit `8f46db5` was built by Cloud Build `0081ae98-bd05-4156-881b-9eb2aa051766` and deployed as Cloud Run revision `question-bank-cloud-v4-00043-vap`, with 100% production traffic. Image digest: `sha256:d5df388d1a43de8ac826b83b6b97fcaf0d07a5857104be1e4d0f7c10aa35eea4`. Live `/`, `/app`, `/practice-exams`, `/robots.txt`, `/sitemap.xml` and `/healthz` returned 200; downloaded UI assets matched the commit byte-for-byte, anonymous `/api/auth/me` returned 401, and mock authentication remained disabled. See `docs/validation/webfix-live.json`. WebKit phone menu/overflow validation also passed. The subsequent additive Android deployment is documented separately.
