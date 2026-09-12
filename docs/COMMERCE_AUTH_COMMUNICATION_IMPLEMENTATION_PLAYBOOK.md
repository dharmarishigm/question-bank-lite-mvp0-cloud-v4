# MeritIQra Commerce, Authentication, and Communication Implementation Playbook

**Status:** implementation blueprint  
**Target application:** current FastAPI web/mobile platform  
**Primary market assumption:** India, INR, GST-ready  
**Recommended first payment provider:** Razorpay  
**Design goal:** after infrastructure credentials and admin configuration are supplied, products, prices, trials, payments, entitlements, OTP, email, SMS, result publication, and notifications work without code edits.

## 1. Outcomes and non-negotiable rules

Build one commerce and communication layer that supports:

- program-wise Trial and Premium access;
- grand-test purchases for one test and configurable bundles such as 3 and 5 tests;
- optional grand-test passes/subscriptions defined by the admin;
- Trial AI quota of **15 successful calls in a rolling 5-hour window**;
- Premium AI quota of **60 successful calls in a rolling 2-hour window**;
- admin-controlled catalog, price versions, discounts, quotas, notification templates, result-release rules, and provider selection;
- OTP/mobile verification and email verification;
- email/SMS/push messages for OTP, payment, subscription, expiry, and result release;
- organization-level “Enquire for pricing” instead of self-service checkout;
- one demo-book page linked from the public home page.

These rules are mandatory:

1. The server, never the browser, decides price, discount, tax, payment status, entitlement, and quota.
2. A payment redirect or client callback never grants access. Only a verified captured-payment event does.
3. Provider webhooks are signature-verified, persisted, idempotent, and safe to replay.
4. Product and price records used by an order are immutable snapshots. Editing a price creates a new version.
5. Provider secrets are stored in Secret Manager/environment variables, never in the database, logs, API responses, or admin browser.
6. Admin configuration stores secret **references** and non-secret settings; the UI can show `configured/not configured`, never secret values.
7. Notifications are generated through a transactional outbox after the business transaction commits.
8. Entitlements are the single authorization source. Do not scatter `is_premium` flags around the codebase.
9. Money is stored as integer minor units (`amount_minor`; paise for INR), never floating point.
10. All admin changes, entitlement changes, refunds, manual grants, result releases, and message resends are audited.

## 2. Fit with the current repository

The repository already provides:

- FastAPI route composition in `app.py`;
- a SQLite/local and PostgreSQL/Cloud SQL adapter in `database.py`;
- user, session, exam, enrollment, and attempt records in `platform_api.py`;
- program enrollment in `program_enrollment_schema.py`;
- grand-test authoring in `grand_tests.py` and `grand_test_schema.py`;
- exam state/version/audit support in `exam_conduct.py`;
- a database-backed rolling AI limiter in `explanation_quota.py`;
- Google Identity Services login in `platform_api.py`;
- mobile devices and a Firebase push hook in `mobile_api.py` and `mobile_notifications.py`;
- enquiry capture/admin follow-up in `engagement.py`;
- result PDF/share features in `result_features.py`.

Do not replace those features. Add the following bounded modules:

```text
commerce_schema.py          additive database schema
commerce_service.py         catalog, quote, order, entitlement business rules
commerce_api.py             student/admin commerce endpoints
payment_providers.py        provider interface + Razorpay adapter
payment_webhooks.py         raw-body verification and idempotent processing
identity_verification.py    phone/email OTP lifecycle
communication_schema.py     templates, preferences, outbox, delivery attempts
communication_service.py    render, enqueue, suppress, retry
communication_workers.py    outbox/payment reconciliation/background jobs
result_publication.py       release policy, release operation, notification fan-out
admin_settings.py           typed settings, validation, audit, health checks
```

Register the routers from `app.py`. Add schemas through reviewed Alembic migrations in production. Local additive initialization may remain available, but production must set `QB_SCHEMA_MANAGED=1` and migrate before deployment.

## 3. Product model

### 3.1 Product families

Use a generic catalog rather than hard-coded bundle names.

| Product type | Scope | Purchase behavior | Resulting entitlement |
|---|---|---|---|
| `PROGRAM_TRIAL` | one program | free, once per student/program | program Trial for configured duration |
| `PROGRAM_PREMIUM` | one program | one-time term initially; recurring can be added | program Premium until `ends_at` |
| `GRAND_TEST_SINGLE` | one specific test | one-time | access to that test |
| `GRAND_TEST_CREDIT_PACK` | eligible program/test collection | one-time | 1, 3, 5, or configurable credits |
| `GRAND_TEST_PASS` | eligible program/test collection | one-time term or recurring | access while pass is active, subject to rules |
| `ORGANIZATION_PLAN` | organization | enquiry/contract | seats, programs, quotas, dates from contract |

“Single/3/5 grand tests” should be three catalog products whose `credit_quantity` is 1, 3, and 5. Do not encode three special cases in application code. An admin can later add 10 without deployment.

### 3.2 Suggested launch packaging

These are commercial starting points, not constants:

| Offering | Suggested list price | Introductory launch price | Term |
|---|---:|---:|---|
| Program Trial | ₹0 | ₹0 | 7 days, once per program |
| Program Premium | ₹999 | ₹699 | 90 days |
| Program Premium | ₹1,799 | ₹1,299 | 180 days |
| One Grand Test | ₹199 | ₹149 | redeem within 90 days |
| Three Grand Tests | ₹499 | ₹399 | redeem within 120 days |
| Five Grand Tests | ₹749 | ₹599 | redeem within 180 days |
| Grand Test Pass | ₹999 | ₹799 | 90 days, eligible catalog |
| Organization | — | Enquire | contracted |

The admin must be able to change values and availability. Before launch, validate pricing against content depth, exam segment, competitor pricing, taxes, refunds, and payment costs. Show the tax-inclusive customer payable amount before payment; retain a tax breakup on the invoice/order snapshot.

### 3.3 Trial and Premium matrix

| Capability | Trial | Premium |
|---|---|---|
| Program catalog/sample content | yes | yes |
| Program exams | admin-configured subset | all included published content |
| AI explanations | 15/rolling 5 hours | 60/rolling 2 hours |
| Grand tests | only if separately granted or purchased | only when program product explicitly includes them; otherwise separate |
| Result view | yes for attempted permitted exams | yes |
| Result PDF/share | configurable | yes by default |

Do not automatically include grand tests in Program Premium unless the catalog’s inclusion rule says so. This avoids accidental revenue leakage and gives the admin explicit control.

### 3.4 Product, price, and discount lifecycle

- Product: `DRAFT -> ACTIVE -> ARCHIVED`.
- Price: `DRAFT -> ACTIVE -> RETIRED`; an active price is never edited in place.
- Discount: `DRAFT -> ACTIVE -> PAUSED -> EXPIRED`.
- A checkout quote locks the price and eligible discount for 15 minutes.
- Existing purchases retain their original terms when catalog configuration changes.
- Deactivating a product prevents new sales; it never revokes existing entitlements.

Discounts support fixed amount or percentage, validity dates, global/per-user redemption limits, minimum amount, product/program allowlists, first-purchase-only, and optional coupon code. Enforce one discount per order at launch. Record both the rule and computed amounts in the quote/order snapshot.

## 4. Database design

Use UTC timestamps. Prefer PostgreSQL `TIMESTAMPTZ`; if the shared adapter requires epoch values initially, document the UTC epoch convention and migrate consistently.

### 4.1 Catalog and pricing

```text
products
  id, code UNIQUE, name, description, product_type, status
  program_id NULL, grand_test_id NULL
  entitlement_kind, term_days NULL, credit_quantity NULL
  inclusion_rules_json, display_metadata_json
  created_by, updated_by, created_at, updated_at

prices
  id, product_id, version, currency, list_amount_minor
  sale_amount_minor, tax_behavior, tax_rate_bps
  valid_from, valid_until NULL, status
  created_by, approved_by NULL, created_at
  UNIQUE(product_id, version)

discounts
  id, code NULL UNIQUE, name, kind, value
  starts_at, ends_at, status, max_redemptions NULL
  max_per_user, minimum_amount_minor, first_purchase_only
  product_rules_json, program_rules_json, created_by, created_at, updated_at

discount_redemptions
  id, discount_id, user_id, order_id UNIQUE, amount_minor, redeemed_at
```

### 4.2 Orders and payments

```text
checkout_quotes
  id UUID, user_id, product_id, price_id, currency
  subtotal_minor, discount_minor, tax_minor, total_minor
  discount_id NULL, pricing_snapshot_json, expires_at, consumed_at NULL

orders
  id UUID, order_number UNIQUE, user_id, quote_id UNIQUE
  product_id, price_id, status, currency
  subtotal_minor, discount_minor, tax_minor, total_minor
  customer_snapshot_json, product_snapshot_json, pricing_snapshot_json
  idempotency_key, created_at, paid_at NULL, cancelled_at NULL

payment_attempts
  id UUID, order_id, provider, provider_order_id UNIQUE
  provider_payment_id NULL, status, amount_minor, currency
  failure_code NULL, failure_message NULL
  created_at, authorized_at NULL, captured_at NULL, updated_at

payment_webhook_events
  id, provider, provider_event_id, signature_valid
  event_type, payload_json, received_at, processed_at NULL
  processing_status, processing_error NULL
  UNIQUE(provider, provider_event_id)

refunds
  id UUID, order_id, payment_attempt_id, provider_refund_id UNIQUE
  amount_minor, status, reason, initiated_by, created_at, completed_at NULL
```

Order states: `CREATED, PAYMENT_PENDING, PAID, PAYMENT_FAILED, CANCELLED, PARTIALLY_REFUNDED, REFUNDED`. Payment attempt states: `CREATED, AUTHORIZED, CAPTURED, FAILED, REFUNDED`.

### 4.3 Entitlements and grand-test credits

```text
entitlements
  id UUID, user_id, source_type, source_id
  entitlement_type, program_id NULL, grand_test_id NULL
  tier, status, starts_at, ends_at NULL
  rules_snapshot_json, created_at, revoked_at NULL, revoked_by NULL

grand_test_credit_wallets
  id UUID, user_id, program_id NULL, source_entitlement_id
  granted_credits, remaining_credits, expires_at NULL, status, created_at

grand_test_credit_ledger
  id UUID, wallet_id, delta, balance_after
  event_type, grand_test_id NULL, idempotency_key UNIQUE, created_at

grand_test_access
  id UUID, user_id, grand_test_id, source_entitlement_id
  status, granted_at, expires_at NULL, UNIQUE(user_id, grand_test_id)
```

Redeeming a test locks the wallet row, checks eligibility/expiry/balance, writes `-1` to the ledger, and creates access in one transaction. Never calculate wallet balance solely by a client value.

### 4.4 OTP and verified contacts

```text
verification_challenges
  id UUID, user_id NULL, channel, purpose, destination_hash
  destination_encrypted, code_hash, status
  attempts, max_attempts, resend_count
  expires_at, next_send_at, created_at, verified_at NULL

verified_contacts
  id UUID, user_id, channel, normalized_value_hash
  encrypted_value, verified_at, is_primary, status
  UNIQUE(channel, normalized_value_hash)
```

Never store plaintext OTP. Hash with an application pepper from Secret Manager and constant-time compare. Recommended defaults: 6 digits, 5-minute expiry, 5 verification attempts, 30-second resend delay, 5 sends/hour/destination, 20 sends/hour/IP, and 10 failed verifications/hour/IP. All values are admin-configurable within server-enforced safe bounds.

### 4.5 Communications

```text
notification_templates
  id, event_type, channel, locale, version, status
  provider_template_id NULL, subject_template NULL, body_template
  allowed_variables_json, created_by, approved_by, created_at

notification_preferences
  user_id, channel, category, enabled, updated_at

notification_outbox
  id UUID, event_id, user_id NULL, channel, template_id
  destination_encrypted, payload_json, status
  priority, scheduled_at, attempts, next_attempt_at
  provider_message_id NULL, last_error NULL, created_at, sent_at NULL
  UNIQUE(event_id, channel, template_id, destination_encrypted)

notification_delivery_events
  id, outbox_id, provider_event_id UNIQUE, status, payload_json, received_at
```

Transactional messages (OTP, payment receipt, entitlement activation, result availability) cannot be disabled when required to provide the service. Marketing messages require explicit consent and preference controls. Never put answers, marks, payment secrets, OTPs, or sensitive personal data into logs.

### 4.6 Result publication

Add a release boundary separate from exam `CLOSED` and attempt `SUBMITTED`:

```text
result_releases
  id UUID, exam_id, status, release_mode
  scheduled_at NULL, released_at NULL, released_by NULL
  audience_rules_json, template_set_id NULL, created_at, updated_at

result_release_recipients
  release_id, user_id, session_id, status
  result_snapshot_hash, notified_at NULL
  UNIQUE(release_id, session_id)
```

States: `DRAFT, SCHEDULED, PROCESSING, PUBLISHED, CANCELLED`. Result APIs must require both ownership and a published release recipient record. “Close exam” does not automatically expose results unless the configured release mode is `IMMEDIATE_AFTER_SUBMISSION`.

## 5. Admin configuration design

### 5.1 Two configuration planes

**Secret/infrastructure plane** (deployment owner only):

- `PAYMENT_PROVIDER=razorpay`
- `RAZORPAY_KEY_ID`
- `RAZORPAY_KEY_SECRET`
- `RAZORPAY_WEBHOOK_SECRET`
- `EMAIL_PROVIDER=ses` (or another implemented adapter)
- provider credentials/region
- `SMS_PROVIDER=<implemented DLT-capable adapter>`
- provider credential and DLT entity/header references
- `OTP_PEPPER`
- `CONTACT_ENCRYPTION_KEY`
- `PUBLIC_APP_BASE_URL`
- Firebase service credentials for push

Store these in Google Secret Manager and inject them into Cloud Run. A restart/revision is expected when secret bindings change.

**Business/admin plane** (database, admin UI, no deployment):

- active products, price versions, discount rules, tax settings;
- Trial duration and once-per-program rule;
- Trial/Premium quota limit and window;
- checkout quote lifetime;
- grand-test eligibility/credit expiry;
- OTP expiry/rate limits within safe bounds;
- sender display names, reply-to/support details;
- approved template selection per event/channel;
- notification routing and channel fallback;
- result-release policy;
- organization enquiry recipients/SLA text;
- demo-book title, cover, PDF/link, and home-page visibility.

Use typed settings, not a free-form key/value dump. Each setting definition has type, validation, minimum/maximum, default, whether restart is required, and whether it is secret. Updates require admin CSRF protection, optimistic concurrency, audit reason, and an `ADMIN` role. Consider a second approval for price activation, discounts above a threshold, refunds, and manual entitlements.

### 5.2 Readiness endpoint

Implement `GET /api/admin/integrations/readiness`, returning no secrets:

```json
{
  "payments": {"provider":"razorpay","configured":true,"webhook_configured":true,"mode":"test"},
  "email": {"provider":"ses","configured":true,"sender_verified":true},
  "sms": {"provider":"...","configured":false,"dlt_templates_complete":false},
  "otp": {"pepper_configured":true,"encryption_configured":true},
  "blocking_issues":["SMS provider credentials are missing"]
}
```

Add “Send test email/SMS”, “Create ₹1 test order”, and “Validate webhook” admin actions. Test messages/orders must be labeled and audited.

## 6. Authorization and entitlement checks

Implement one `AccessDecision` service used by catalog, enrollment, exam start, grand-test redemption, results, and AI endpoints:

```text
authorize(user, action, resource, now) ->
  allowed, reason_code, entitlement_id, limits, upgrade_options
```

Useful reason codes: `NO_ENTITLEMENT`, `TRIAL_EXPIRED`, `SUBSCRIPTION_EXPIRED`, `GRAND_TEST_NOT_REDEEMED`, `QUOTA_EXCEEDED`, `RESULT_NOT_RELEASED`, `ACCOUNT_INACTIVE`.

Check access both when enrolling and when starting/resuming an attempt. A URL or stale browser state must never bypass the server check. Define a policy for an entitlement that expires during an active test; recommended: allow the already-started timed attempt to finish, but prevent new attempts.

## 7. AI quota implementation

Replace the hard-coded `LIMIT = 10` and `WINDOW_SECONDS = 3600` in `explanation_quota.py` with a policy resolved from the user’s effective entitlement:

```text
Trial:   limit=15, window_seconds=18_000
Premium: limit=60, window_seconds=7_200
```

Use a rolling window and reserve atomically before provider invocation. Add:

- `feature_key` to usage records (for example `AI_EXPLANATION`);
- `entitlement_id` and policy snapshot to make usage explainable;
- a reservation state: `RESERVED, CONSUMED, RELEASED`;
- a short reservation timeout, so infrastructure failures can release quota;
- an API response with `limit`, `remaining`, `window_seconds`, and `retry_after_seconds`;
- an admin override with expiry and audit, not a permanent hidden bypass.

Count a call when the AI request is accepted for execution. Release only on a confirmed platform/provider failure before usable output; do not release for user cancellation after output generation. Quota is per user and feature across devices/workers, not per session.

## 8. Payment gateway: prerequisites and setup

### 8.1 Business prerequisites

Before requesting live activation, prepare:

- legal entity/proprietor details and PAN;
- bank account and proof;
- business address and authorized representative;
- public HTTPS domain;
- product/pricing page with clear deliverables and duration;
- Terms of Service, Privacy Policy, refund/cancellation policy, contact page;
- GST registration/tax advice as applicable and invoice numbering policy;
- support email and phone;
- settlement/refund/reconciliation owner.

Complete Razorpay account/KYC, generate separate Test and Live keys, decide automatic capture, and configure Test and Live webhook endpoints/secrets separately.

### 8.2 Server integration sequence

1. Client requests `POST /api/commerce/quotes` with only product ID and optional coupon.
2. Server validates active product/price/discount, eligibility, currency, tax, and duplicate ownership; persists a 15-minute quote.
3. Client requests `POST /api/commerce/orders` with quote ID and an idempotency key.
4. Server consumes the quote once, creates a local order, then creates a Razorpay Order server-side using the local order number as receipt.
5. Server stores the provider order ID and returns only checkout-safe fields (`key_id`, provider order ID, amount, currency, display name).
6. Browser/mobile opens hosted checkout. Card/UPI credentials never touch MeritIQra.
7. Client sends checkout IDs/signature to `POST /api/commerce/payments/confirm` for a fast status update. The server verifies HMAC using the **server-stored local provider order ID**.
8. Razorpay posts to `POST /api/webhooks/razorpay`. Read the raw request body, validate `X-Razorpay-Signature`, deduplicate on provider event ID, store the event, and return quickly.
9. A transaction locks the order/payment rows. On verified `payment.captured`/`order.paid`, it marks the order paid, creates the entitlement/credits, redeems the discount, inserts notification outbox events, and commits.
10. Client polls `GET /api/commerce/orders/{id}` or refreshes `/me/entitlements`; it never grants itself access.

### 8.3 Webhook and reconciliation requirements

- Accept only HTTPS in production.
- Verify against the raw bytes before JSON parsing.
- Support secret rotation: retain previous webhook secret for the provider retry window.
- Treat events as unordered and duplicated; transitions are monotonic.
- Return 2xx only after durable receipt. Process expensive work asynchronously.
- Redact payloads before operational logging; retain restricted raw payload only if required.
- Reconcile `PAYMENT_PENDING` orders with provider APIs every 10–15 minutes, then daily against settlements.
- Alert on signature failures, processing failures, amount/currency mismatch, captured payment without entitlement, and local/provider reconciliation mismatch.
- A refund revokes or shortens unused entitlement according to the published refund policy. If a grand-test credit has been redeemed/attempted, route to admin review rather than silently deleting results.

### 8.4 Payment test matrix

- success (UPI/card in provider test mode);
- customer cancellation;
- failed payment and retry creating a new payment attempt under the same order policy;
- delayed webhook after client closes the tab;
- webhook before client confirmation;
- duplicate webhook 10 times;
- invalid signature;
- amount/currency mismatch;
- service crash after payment capture but before entitlement commit, then replay;
- partial/full refund;
- already-owned product;
- expired quote/discount and redemption-limit race;
- concurrent clicks with same and different idempotency keys.

## 9. SMS and mobile OTP setup

### 9.1 India prerequisites

For application-to-person SMS in India, register the business as a Principal Entity on a telecom DLT platform, register a sender header, register each content template, and arrange any required consent templates/consents. The text sent by the application must match the approved template, including fixed text and variable placement. The SMS provider must support passing PE ID, header/sender ID, content template ID, and route/category.

Prepare separate DLT templates for:

- login/registration OTP;
- phone change OTP;
- payment confirmation;
- subscription activation/expiry reminder;
- result available;
- refund confirmation.

Do not reuse an OTP/authentication template for marketing.

### 9.2 OTP flow

1. Normalize phone to E.164; for India require a valid `+91` mobile number.
2. Apply IP, account, device, and destination rate limits before generating a code.
3. Generate with a cryptographically secure RNG.
4. Store only the peppered hash plus encrypted destination and challenge metadata.
5. Enqueue the approved SMS template; do not return the code except in development/test mode.
6. Verification atomically checks purpose, destination, unused status, attempts, and expiry.
7. On success, mark used, add/update `verified_contacts`, bind to the user, and revoke competing active challenges.
8. OTP never directly creates a Premium entitlement or marks a payment paid.

Use generic responses (“If this number can receive messages, an OTP was sent”) where account enumeration is possible. Add CAPTCHA/risk challenge after suspicious velocity. Support codes are never able to reveal OTP values.

### 9.3 Mobile authentication choice

Launch with both:

- existing Google Identity login for convenient web/mobile sign-in; and
- phone OTP sign-in/verification through the new challenge service.

Keep one user record and multiple verified identities. Define an explicit account-linking flow: an authenticated user verifies the new identity, sees masked existing-account information if conflict occurs, and completes a second proof or support review. Never auto-merge accounts merely because names match.

For native Android, prefer the provider/native SDK or system browser flow when required; do not embed secrets in the APK. Store session tokens in OS secure storage, rotate/revoke sessions, and enforce the same server-side entitlement rules as web.

## 10. Transactional email setup

### 10.1 Prerequisites

Use a transactional provider such as Amazon SES behind `EmailProvider`. Do not use a personal Gmail password or mailbox as the production sender.

1. Create a sending subdomain such as `mail.meritiqra.com`.
2. Verify the domain with the provider.
3. Publish SPF and DKIM records; publish DMARC first in monitoring mode, then tighten after reviewing reports.
4. Configure a custom MAIL FROM/bounce domain if supported.
5. Request production sending access and raise limits based on measured volume.
6. Set `From`, `Reply-To`, support, legal address, and brand details.
7. Configure bounce/complaint/delivery webhooks.
8. Create separate provider credentials for staging and production; staging may send only to allowlisted addresses.

Google sign-in does not grant Gmail mailbox access and none is required. It supplies authenticated identity/profile data; transactional email is sent by the email provider to Gmail or any valid recipient domain.

### 10.2 Email verification

Prefer a signed, one-time verification link (15–30 minute expiry) for initial email verification. If the product requires a numeric email OTP, reuse `verification_challenges` with channel `EMAIL`. Links/codes are purpose-bound, single-use, rate-limited, and invalidate older challenges.

### 10.3 Required templates

Create versioned, approved HTML and plain-text templates for:

- verify email / email OTP;
- welcome and Trial activation;
- payment received and payment failed;
- Premium activation and renewal/expiry reminders;
- grand-test credit purchase and redemption;
- result published;
- refund initiated/completed;
- organization enquiry acknowledgement and admin alert;
- security events such as phone/email change.

All templates use an allowlist of variables. Escape user content, disallow arbitrary template code, preview desktop/mobile/plain text, and send a test before activation. Receipts include order number, product, paid amount/tax, date, support/refund link, and invoice link when applicable—but never payment credentials.

## 11. Notification event architecture

Business services publish domain events in the same database transaction:

```text
TRIAL_STARTED
PAYMENT_CAPTURED
PAYMENT_FAILED
ENTITLEMENT_ACTIVATED
ENTITLEMENT_EXPIRING
ENTITLEMENT_EXPIRED
GRAND_TEST_REDEEMED
RESULT_PUBLISHED
REFUND_COMPLETED
ORGANIZATION_ENQUIRY_RECEIVED
CONTACT_CHANGED
```

The outbox dispatcher selects due rows using row locking/skip-locked semantics on PostgreSQL, renders the active approved template, sends through the configured adapter, and records the provider ID. Retry transient errors with exponential backoff and jitter; suppress permanent failures. Suggested maximum: 8 attempts over 24 hours for transactional messages. OTP uses a high-priority queue and much shorter retry horizon because it expires.

Suggested routing:

| Event | Email | SMS | Push |
|---|---|---|---|
| OTP | optional by channel | primary for phone OTP | no |
| Payment captured | primary | concise confirmation | optional |
| Subscription activated | primary | optional | yes |
| Expiry reminders | primary | opt-in/configured | yes |
| Result published | primary | configured fallback | yes |
| Refund completed | primary | optional | optional |

Delivery failure must not roll back a captured payment, entitlement, or result publication. The outbox makes the message retryable independently.

## 12. Result publication and communication

1. Admin closes the exam and reviews scoring/corrections.
2. Admin opens a release preview: recipient count, withheld attempts, template previews, scheduled time, and visible result fields.
3. Admin chooses `IMMEDIATE`, `SCHEDULED`, or a configured automatic policy and confirms with a reason.
4. The release worker snapshots eligible attempt/result hashes and transitions the release to `PROCESSING`.
5. Recipient rows are inserted idempotently; result APIs now allow those published recipients.
6. One `RESULT_PUBLISHED` event per recipient is inserted into the outbox.
7. Release becomes `PUBLISHED`; dashboard displays delivery counts separately from publication success.
8. Releasing again does not duplicate messages unless admin explicitly selects “Resend notification”; resends are audited.

Email/SMS should say that the result is available and link to authenticated access. Do not put full scores or sensitive report links in SMS. Existing time-limited shared PDF links remain an explicit student action, not the default notification URL.

## 13. Organization-level plans

Extend the current enquiry flow with interest `ORGANIZATION` and fields:

- organization name/type;
- contact person and verified work email/phone;
- expected student/seat count;
- programs/exams of interest;
- desired start date/term;
- message and consent;
- source/campaign.

The public pricing card says “Organization plan — custom seats, programs, quotas, support — Enquire for details.” It opens a dedicated page, not checkout. Admin workflow: `NEW -> QUALIFIED -> PROPOSAL_SENT -> WON/LOST`. If won, an admin creates an organization contract and seat entitlements; do not use consumer coupon codes to simulate enterprise contracts.

## 14. Demo book on the home page

Add one public “Try the demo book” card to `static/home.html` with cover, title, short syllabus description, page count, and `View demo` call-to-action. The linked viewer must:

- use only content explicitly approved for public distribution;
- expose a curated sample PDF or HTML pages—not a private upload URL;
- be accessible without login, responsive, keyboard usable, and mobile tested;
- have `Cache-Control` appropriate for public content and a stable versioned asset URL;
- include an admin setting to publish/unpublish, set title/cover/document, and preview;
- collect no student data unless the visitor separately starts registration/enquiry.

If the source book is copyrighted or licensed, obtain written permission and define allowed pages before upload. Watermarking is optional but not a substitute for permission.

## 15. APIs

### Student/public APIs

```text
GET  /api/catalog?program_id=
POST /api/trials                         start eligible program trial
GET  /api/me/entitlements
GET  /api/me/ai-quota
POST /api/grand-tests/{id}/redeem
POST /api/commerce/quotes
POST /api/commerce/orders
POST /api/commerce/payments/confirm
GET  /api/commerce/orders/{id}
GET  /api/me/orders
POST /api/auth/otp/request
POST /api/auth/otp/verify
POST /api/auth/email-verification/request
POST /api/auth/email-verification/verify
POST /api/organization-enquiries
```

### Provider callbacks

```text
POST /api/webhooks/razorpay
POST /api/webhooks/email/{provider}
POST /api/webhooks/sms/{provider}
```

Provider webhook routes have signature authentication, not cookie/CSRF authentication. They still require strict body limits, content types, rate controls, and durable event logging.

### Admin APIs

```text
/api/admin/products
/api/admin/prices
/api/admin/discounts
/api/admin/orders
/api/admin/refunds
/api/admin/entitlements
/api/admin/settings
/api/admin/notification-templates
/api/admin/notification-outbox
/api/admin/result-releases
/api/admin/integrations/readiness
/api/admin/integrations/test-message
/api/admin/organization-enquiries
```

Every mutation uses existing admin authorization plus CSRF/session checks, optimistic versioning, validation, and an audit reason. Do not allow the admin UI to manufacture a paid order; manual grants are a distinct audited source type.

## 16. Implementation phases

### Phase 0 — decisions and accounts (2–5 business days plus provider approvals)

- Confirm legal seller, tax/invoice/refund policies, INR launch, and product terms.
- Choose Razorpay, email provider, DLT-capable SMS provider, and operational owners.
- Start payment KYC, DLT PE/header/templates, sender-domain DNS verification, and production email access early; approvals can be the critical path.
- Define the exact demo content and secure rights.
- Finalize initial prices and Trial eligibility.

**Exit:** owners, accounts, policy documents, DNS access, DLT plan, product matrix, and secrets strategy approved.

### Phase 1 — schema, settings, audit, provider contracts (3–5 days)

- Add migrations for catalog, orders/payments, entitlements, OTP, outbox, releases, and audits.
- Implement typed admin settings and readiness checks.
- Define `PaymentProvider`, `EmailProvider`, and `SmsProvider` interfaces plus fake adapters.
- Add structured logging with correlation IDs and redaction.

**Exit:** migrations pass on SQLite and PostgreSQL; fake providers pass unit tests; secret values never appear in APIs/logs.

### Phase 2 — entitlements, products, pricing, quota (4–7 days)

- Build admin catalog/price/discount UI and public catalog.
- Implement quote snapshots and discount eligibility.
- Implement Trial activation and AccessDecision.
- Gate program enrollment, exam start, grand tests, result features, and AI explanations.
- Change AI policies to 15/5h Trial and 60/2h Premium.

**Exit:** free flows and manual test entitlements work; expired/no-access states cannot be bypassed; concurrent quota tests pass.

### Phase 3 — Razorpay test integration (4–7 days)

- Add server-side provider order creation, hosted checkout, confirmation HMAC, raw webhook verification, event idempotency, entitlement fulfillment, reconciliation, refunds, and admin order view.
- Exercise the complete payment matrix in provider Test mode.

**Exit:** a captured test payment creates exactly one entitlement even after replay/crash; failures never create access.

### Phase 4 — OTP and identity (4–7 days, parallel with external DLT approval)

- Implement challenge lifecycle, encrypted contacts, limits, verification, account linking, and fake SMS tests.
- Register exact DLT templates and map provider template IDs in admin.
- Integrate web and native mobile flows.

**Exit:** production-like OTP load/abuse tests pass; account enumeration and auto-merge are prevented.

### Phase 5 — email/SMS/outbox (4–6 days)

- Add templates/preview/approval, outbox worker, retries, delivery webhooks, bounce/complaint suppression, admin delivery view, and test-message actions.
- Wire payment, subscription, expiry, result, refund, and security events.

**Exit:** messages are idempotent, provider failures do not corrupt business state, and delivery status is observable.

### Phase 6 — result release, organization enquiry, demo book (3–5 days)

- Implement release state machine, recipient snapshots, scheduled worker, and result authorization.
- Extend enquiry/admin pipeline for organizations.
- Add configurable home-page demo card/viewer.

**Exit:** unpublished results are inaccessible; a release notifies each recipient once; demo and organization flows pass accessibility/mobile review.

### Phase 7 — staging, security, and go-live (5–10 days)

- Seed launch products and templates in staging.
- Run E2E, concurrency, webhook replay, backup/restore, provider outage, and reconciliation tests.
- Perform privacy/security review and vulnerability scan.
- Complete a low-value live transaction/refund with internal accounts.
- Roll out to staff, then a small student cohort, then general availability behind feature flags.

**Exit:** dashboards/alerts/runbooks are active, finance reconciles the transaction, support handles a scripted incident, and rollback flags are verified.

## 17. Configuration-first launch checklist

When code is deployed, the administrator follows this order:

1. Deployment owner injects database, base URL, encryption/OTP keys, and Test provider secrets.
2. Admin readiness page must show all Test integrations green.
3. Admin creates programs’ Trial and Premium products.
4. Admin creates version 1 prices and activates them.
5. Admin creates grand-test 1/3/5 products, terms, eligible tests, and prices.
6. Admin configures Trial/Premium AI policies and validates safe bounds.
7. Admin creates/activates discounts, if any.
8. Admin maps approved email/SMS templates and sends test messages.
9. Admin sets result-release default and organization enquiry routing.
10. Admin uploads/selects the approved demo asset and previews the home page.
11. QA completes Trial, Premium purchase, grand-test credit redemption, OTP, email, result release, refund, and expiry flows.
12. Deployment owner injects Live credentials; admin readiness must show Live and all checks green.
13. Enable checkout for internal users, run a real low-value purchase/refund, reconcile, then enable publicly.

## 18. Security, privacy, reliability, and operations

### Security/privacy

- Encrypt phone/email destinations at rest where stored outside the user profile; retain hashes for lookup/rate limiting.
- Use purpose-specific OTP challenges and CSRF protection on browser mutations.
- Apply least privilege to Secret Manager, database, provider dashboards, refund permissions, and production logs.
- Never store card/UPI details; hosted checkout keeps PCI scope smaller.
- Add retention jobs: expire/delete OTP records, age provider payloads per policy, retain invoices/audits as legally required.
- Record consent version/time/source for marketing and organization enquiries.
- Provide account data export/deletion workflows compatible with legal retention obligations.

### Observability

Track:

- quote-to-checkout and checkout-to-capture conversion;
- payment success/failure by provider method and error class;
- webhook age, signature failure, duplicate count, and processing lag;
- paid-order-without-entitlement count (target zero);
- OTP send/verify success, latency, resend/abuse rate;
- email/SMS delivery, bounce, complaint, suppression, and retry age;
- AI quota usage/denial by tier;
- result release completion and notification backlog;
- expiring entitlements and credit liability.

Page immediately on captured payment without entitlement, webhook backlog beyond five minutes, widespread OTP failure, result release stuck in processing, or outbox queue growth. Use correlation IDs: `request_id`, `order_id`, `payment_attempt_id`, `provider_event_id`, and `event_id`.

### Runbooks

Create operator runbooks for:

- payment captured but user sees pending;
- duplicate debit claim;
- refund request/provider refund stuck;
- provider webhook outage/signature rotation;
- OTP not received and DLT template rejection;
- email bounce/complaint or domain reputation issue;
- accidental price/discount activation;
- incorrect entitlement/manual revoke;
- result published early or to wrong audience;
- secret rotation and compromised credential;
- outbox backlog and replay;
- database restore/reconciliation after incident.

## 19. Definition of done

The capability is complete only when all are true:

- Admin can configure and activate program Trial/Premium and grand-test 1/3/5 offerings without code changes.
- Student sees the exact payable price/tax/discount before checkout.
- Captured payment produces exactly one correct entitlement under retry, replay, and crash tests.
- Trial is once per user/program and expires correctly.
- AI quotas enforce 15/5h and 60/2h across sessions and workers.
- Grand-test credits cannot go negative and concurrent redemption is safe.
- Phone/email verification is purpose-bound, expiring, rate-limited, encrypted/hashed, and audited.
- Email/SMS/push events are template-driven, idempotent, retried, and observable.
- Results remain inaccessible until their release and notify eligible students once.
- Organization visitors submit a tracked enquiry rather than entering consumer checkout.
- Demo book is rights-cleared, public, responsive, accessible, and admin-controlled.
- Test and Live credentials are separated; no secret appears in source, database settings, browser, or logs.
- Refund, reconciliation, incident, backup/restore, and secret-rotation runbooks have been exercised.

## 20. Recommended delivery order for Codex implementation tasks

Use small reviewed changes in this order:

1. `commerce-schema-and-migrations`
2. `typed-admin-settings-and-audit`
3. `catalog-prices-discounts-admin`
4. `entitlement-access-decision`
5. `trial-and-ai-quota-policy`
6. `grand-test-credit-wallet`
7. `payment-provider-contract-and-fake`
8. `razorpay-orders-confirm-webhook`
9. `payment-reconciliation-refunds`
10. `verification-challenges-and-contacts`
11. `sms-provider-and-dlt-template-mapping`
12. `email-provider-domain-and-delivery-events`
13. `notification-template-outbox-worker`
14. `result-release-and-notifications`
15. `organization-enquiry-pipeline`
16. `home-page-demo-book`
17. `end-to-end-security-load-and-go-live`

Each change must include migration forward/rollback strategy, API authorization tests, unit tests for state transitions, PostgreSQL concurrency tests where money/quota/credits are involved, UI empty/error/loading states, admin audit events, metrics, and an operational note.

## 21. Official setup references

- Razorpay Standard Checkout prerequisites: <https://razorpay.com/docs/payments/payment-gateway/web-integration/standard/>
- Razorpay Standard Checkout integration: <https://razorpay.com/docs/payments/payment-gateway/web-integration/standard/integration-steps/>
- Razorpay webhook guidance: <https://razorpay.com/docs/webhooks/>
- Razorpay webhook validation/idempotency: <https://razorpay.com/docs/webhooks/validate-test/>
- TRAI sender/PE, header, content-template, and consent guidance: <https://www.trai.gov.in/advice-to-senders>
- Amazon SES developer guide (domain identity/DKIM and production setup): <https://docs.aws.amazon.com/ses/latest/dg/Welcome.html>
- Google Identity Services overview: <https://developers.google.com/identity/gsi/web/guides/overview>

