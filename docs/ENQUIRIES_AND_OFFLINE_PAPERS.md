# Enquiries and offline marketing papers

The public `/enquiry` page offers online-exam, FLAG premium and general enquiries. It displays the supplied phone **9391103630** and email **admin@meritiqra.com**, with online registration links. A consent checkbox, honeypot, expiring single-use arithmetic verification, and database-backed IP/email submission limits reduce automated spam. Arithmetic verification is a basic deterrent, not a bot-proof CAPTCHA. Personal details remain in the admin-only enquiry inbox; there are no automated emails or external messages.

Administrators open **Enquiries & premium requests**, filter new/contacted/resolved requests, and save private follow-up notes with stale-update protection. FLAG activation is managed separately under **FLAG access & materials** after the enquiry is reviewed. Contact details on the public page are not authentication credentials or a new administrator account.

In **Exam Admin**, every exam card offers **Offline marketing PDF**. Administrators can edit contact details and the short benefit message, and optionally add an answer-key section. The default student paper omits answers and solutions. The export reads the current question-bank content linked to the exam, including current corrections; it does not create an attempt or change the published exam. Review the PDF before distributing it.

Every A4 page contains a MeritIQra header and footer with product benefits, contact details, website and registration links, page numbers, and a QR code to `https://meritiqra.com/enquiry?exam=<id>`. This public URL does not reveal questions or enroll anyone. The app's existing Markdown and KaTeX renderer preserves equations; bundled font files allow rendering without remote font requests. Missing images and equation/rendering errors prevent incomplete exports. Only local question-upload images and bundled fonts are served to the isolated Chromium renderer. The server serializes PDF renders per worker and limits administrators to 20 exports per hour.

Chromium is installed during the container build via `python -m playwright install --with-deps chromium`, with `PLAYWRIGHT_BROWSERS_PATH=/opt/playwright`. Local validation uses the existing Playwright installation.

Validation: `tests/test_engagement.py`, `tests/validate_engagement_ui.py`, and `tests/validate_marketing_pdf.py`. The latter verifies recurring contact/link content on every page of a multi-page sample; inspect rendered pages and scan the QR before deployment.
