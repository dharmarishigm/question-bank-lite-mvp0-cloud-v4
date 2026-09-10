# FLAG learning workspace

Administrators use **FLAG access & materials** to grant or disable access by verified email. FLAG users may have no expiry; subscribers require a future expiry date. Expiry is entered in the administrator's local time and stored in UTC. Administrators can preview materials without a subscription. There is no payment processor integration.

Authorized members see **Learning handbook** and **Excel templates**. All material, page, image, workbook and explanation endpoints check the session and current membership. Revoked, expired and unverified users cannot retrieve content. Material URLs are authenticated application endpoints; no public GCS URLs or signed bearer links are issued.

## Handbook

The continuous reader loads pages as they approach the viewport. Select text within one page or choose **Area / diagram** and drag a rectangle. The AI uses that selection and the actual page context. Text instructions embedded in files are untrusted data. AI output is rendered through the existing Markdown renderer. The shared limit is 10 explanation requests per hour per user; reservation happens before provider calls, including failed calls.

Read page, selection, or explanation aloud using browser speech synthesis, with pause/resume, stop and speed controls. The English voice selector excludes other languages, prefers available natural/premium voices, and remembers the selected voice. Text is cleaned and read in sentence chunks. If no English voice is installed, the page explains how to enable one. Voice quality depends on the browser/device. No server audio generation is required.

## Excel templates

Workbook tiles open an authenticated, read-only worksheet viewer with sheet selection, row pagination, original cell styles, merged cells, and a value inspection bar. Formula text is returned only to administrators. The viewer displays saved Excel values; it does not recalculate formulas. Charts, images and native Excel controls are not included in the cell preview. Source workbooks are preserved byte for byte. External workbook links and macros are not executed by the viewer.

## Protection, trials and premium enquiries

Original downloads are administrator-only, including direct endpoint access; learner UI download links are removed. Learners receive page/cell views subject to entitlement checks and a 180-reads-per-minute quota. PDF images include a server-rendered user/date watermark. The browser adds a licensed-user watermark, blocks copy/cut/context menus/drag/save/print shortcuts outside editable inputs, hides content in print media, and blurs the reader when the page becomes hidden. Text selection remains available for AI explanations. The native protected-window API is used where supported. Frame embedding and browser display-capture permissions are denied. These are deterrents, not a guarantee against OS screenshots, cameras, developer tools or extraction of content already displayed to an authorized user.

A verified account without an administrator-managed membership can explicitly start one 3-day trial. The server allows only the first 10 PDF pages and the first 2 active workbooks ordered by title/id. Trial use is recorded permanently and cannot be restarted. An administrator-disabled or expired membership cannot bypass its restriction by starting a trial. Premium request buttons lead to `/enquiry?interest=FLAG`; subscription activation remains an administrator action and no payment is collected.

## Storage and uploads

Set `GCS_DATA_BUCKET` to the existing private application bucket. Originals use immutable object keys under `flag-private/`; metadata and access lists live in the application database. This prefix is outside the public uploads directory. Development/test may use `FLAG_LOCAL_DIR`; production refuses local fallback.

An administrator can upload a PDF, one .xlsx file or a ZIP of up to 50 .xlsx files, maximum 25 MB per upload. A PDF replaces the current handbook. Excel uploads replace matching filenames and retain other library items. The entire upload is validated before metadata is activated. Historical objects remain private for recovery. Access changes and uploads are audited.

## GATE ECE

The existing GATE ECE program uses the GATE 2027 EC reference with 65 questions, 100 marks and 180 minutes. General Aptitude carries 15 marks, Mathematics 13, and EC core 72. Eighteen editable subject/mark bands allow full or focused MCQ practice. Chapter question counts are practice allocations, not official weights. MSQ/NAT are not implemented.

`gate_setup.py` checks the live official pattern and syllabus when reachable. If TLS/network retrieval fails, the form receives the dated reviewed reference with an explicit live-verification warning. Certificate validation is never disabled. A readable changed pattern also carries a review warning. Later cycles require refreshing the reviewed preset; a fallback is never labelled a fresh verification.

## Validation

`tests/test_flag.py` covers entitlement, expiry, revocation, CSRF, private endpoints, replacement, workbook formulas/merges, invalid uploads, source selection and explanation quota. `tests/validate_flag_ui.py` reads the supplied handbook and ZIP, checks every visible worksheet, then tests desktop/mobile navigation, PDF selection, Markdown explanation rendering, area selection, membership and immediate revocation.
