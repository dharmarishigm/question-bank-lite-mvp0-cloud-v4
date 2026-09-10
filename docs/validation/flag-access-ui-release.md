# FLAG access and presentation validation

Validated on 2026-09-10 before deployment:

- Full backend suite: 189 passed; additional Google role authorization test: 1 passed.
- Browser navigation audit: 91 desktop/tablet/mobile checks, no reported issues or JavaScript errors. Synthetic accounts and data only.
- Offline PDF: 24 questions plus answer keys, 8 pages; recurring contact, brand and enquiry links validated on every page. First page visually reviewed after density and border adjustments.
- Live bounded epidemiology request: `gemini-2.5-flash` in `asia-south1` succeeded using the simplified serving schema. Suggested values remain assumptions, not verified market evidence.
- `gemini-3.5-flash-lite` returned 404 for this project/region. Release defaults retain the working model.
- JavaScript syntax and deployment shell syntax passed; `git diff --check` passed.

Access requires verified Google identity and an active administrator FLAG grant. Existing self-service trials cannot unlock resources. Login role selection never grants administrator or FLAG permissions. Tutor calls and epidemiology suggestions use the existing per-user AI quota.

The security checks cover application authorization, CSRF, input validation and tested resource paths; they are not a penetration test or a complete cloud IAM audit.

Deployment build: `93f49bae-b922-4b07-999c-67441b326536` succeeded. Revision `question-bank-cloud-v4-epi-20260910172555` serves 100% traffic. Domain health at `https://meritiqra.com/healthz` returned `{"status":"ok"}` and the updated FLAG script was verified on the domain. The raw Cloud Run URL returned 404, so the deployment script now uses the public domain for health verification. No merge to develop performed.
