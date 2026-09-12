"""Additive commerce, identity verification, communication, and result-release schema."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_settings (
 key TEXT PRIMARY KEY, value_json TEXT NOT NULL, value_type TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 1, updated_by INTEGER, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS commerce_audit_log (
 id INTEGER PRIMARY KEY AUTOINCREMENT, actor_user_id INTEGER, action TEXT NOT NULL,
 entity_type TEXT NOT NULL, entity_id TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '',
 metadata_json TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_commerce_audit_entity ON commerce_audit_log(entity_type,entity_id,created_at);

CREATE TABLE IF NOT EXISTS products (
 id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '', product_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT',
 program_id INTEGER, grand_test_id INTEGER, entitlement_kind TEXT NOT NULL,
 term_days INTEGER, credit_quantity INTEGER, inclusion_rules_json TEXT NOT NULL DEFAULT '{}',
 display_metadata_json TEXT NOT NULL DEFAULT '{}', created_by INTEGER NOT NULL, updated_by INTEGER NOT NULL,
 created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_products_catalog ON products(status,product_type,program_id);
CREATE TABLE IF NOT EXISTS prices (
 id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL REFERENCES products(id),
 version INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'INR', list_amount_minor INTEGER NOT NULL,
 sale_amount_minor INTEGER NOT NULL, tax_behavior TEXT NOT NULL DEFAULT 'INCLUSIVE',
 tax_rate_bps INTEGER NOT NULL DEFAULT 0, valid_from REAL NOT NULL, valid_until REAL,
 status TEXT NOT NULL DEFAULT 'DRAFT', created_by INTEGER NOT NULL, approved_by INTEGER,
 created_at REAL NOT NULL, UNIQUE(product_id,version));
CREATE INDEX IF NOT EXISTS idx_prices_active ON prices(product_id,status,valid_from,valid_until);
CREATE TABLE IF NOT EXISTS discounts (
 id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, name TEXT NOT NULL, kind TEXT NOT NULL,
 value INTEGER NOT NULL, starts_at REAL NOT NULL, ends_at REAL, status TEXT NOT NULL DEFAULT 'DRAFT',
 max_redemptions INTEGER, max_per_user INTEGER NOT NULL DEFAULT 1, minimum_amount_minor INTEGER NOT NULL DEFAULT 0,
 first_purchase_only INTEGER NOT NULL DEFAULT 0, product_rules_json TEXT NOT NULL DEFAULT '{}',
 program_rules_json TEXT NOT NULL DEFAULT '{}', created_by INTEGER NOT NULL, created_at REAL NOT NULL,
 updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS discount_redemptions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, discount_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
 order_id TEXT NOT NULL UNIQUE, amount_minor INTEGER NOT NULL, redeemed_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_discount_redemptions_rule ON discount_redemptions(discount_id,user_id);
CREATE TABLE IF NOT EXISTS checkout_quotes (
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, product_id INTEGER NOT NULL REFERENCES products(id),
 price_id INTEGER NOT NULL REFERENCES prices(id), currency TEXT NOT NULL, subtotal_minor INTEGER NOT NULL,
 discount_minor INTEGER NOT NULL DEFAULT 0, tax_minor INTEGER NOT NULL DEFAULT 0, total_minor INTEGER NOT NULL,
 discount_id INTEGER, pricing_snapshot_json TEXT NOT NULL, expires_at REAL NOT NULL, consumed_at REAL,
 created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_quotes_user ON checkout_quotes(user_id,created_at);
CREATE TABLE IF NOT EXISTS orders (
 id TEXT PRIMARY KEY, order_number TEXT NOT NULL UNIQUE, user_id INTEGER NOT NULL, quote_id TEXT NOT NULL UNIQUE,
 product_id INTEGER NOT NULL, price_id INTEGER NOT NULL, status TEXT NOT NULL, currency TEXT NOT NULL,
 subtotal_minor INTEGER NOT NULL, discount_minor INTEGER NOT NULL, tax_minor INTEGER NOT NULL,
 total_minor INTEGER NOT NULL, customer_snapshot_json TEXT NOT NULL, product_snapshot_json TEXT NOT NULL,
 pricing_snapshot_json TEXT NOT NULL, idempotency_key TEXT NOT NULL, created_at REAL NOT NULL,
 paid_at REAL, cancelled_at REAL, UNIQUE(user_id,idempotency_key));
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id,created_at);
CREATE TABLE IF NOT EXISTS payment_attempts (
 id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id), provider TEXT NOT NULL,
 provider_order_id TEXT UNIQUE, provider_payment_id TEXT, status TEXT NOT NULL,
 amount_minor INTEGER NOT NULL, currency TEXT NOT NULL, failure_code TEXT, failure_message TEXT,
 created_at REAL NOT NULL, authorized_at REAL, captured_at REAL, updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_payment_attempts_order ON payment_attempts(order_id,created_at);
CREATE TABLE IF NOT EXISTS payment_webhook_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL, provider_event_id TEXT NOT NULL,
 signature_valid INTEGER NOT NULL, event_type TEXT NOT NULL, payload_json TEXT NOT NULL,
 received_at REAL NOT NULL, processed_at REAL, processing_status TEXT NOT NULL DEFAULT 'RECEIVED',
 processing_error TEXT, UNIQUE(provider,provider_event_id));
CREATE TABLE IF NOT EXISTS refunds (
 id TEXT PRIMARY KEY, order_id TEXT NOT NULL, payment_attempt_id TEXT NOT NULL,
 provider_refund_id TEXT UNIQUE, amount_minor INTEGER NOT NULL, status TEXT NOT NULL,
 reason TEXT NOT NULL, initiated_by INTEGER NOT NULL, created_at REAL NOT NULL, completed_at REAL);

CREATE TABLE IF NOT EXISTS entitlements (
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, source_type TEXT NOT NULL, source_id TEXT NOT NULL,
 entitlement_type TEXT NOT NULL, program_id INTEGER, grand_test_id INTEGER, tier TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'ACTIVE', starts_at REAL NOT NULL, ends_at REAL,
 rules_snapshot_json TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL,
 revoked_at REAL, revoked_by INTEGER, UNIQUE(user_id,source_type,source_id,entitlement_type));
CREATE INDEX IF NOT EXISTS idx_entitlements_access ON entitlements(user_id,status,entitlement_type,program_id,grand_test_id);
CREATE TABLE IF NOT EXISTS program_trials (
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, program_id INTEGER NOT NULL,
 entitlement_id TEXT NOT NULL UNIQUE, started_at REAL NOT NULL, expires_at REAL NOT NULL,
 UNIQUE(user_id,program_id));
CREATE TABLE IF NOT EXISTS grand_test_credit_wallets (
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, program_id INTEGER, source_entitlement_id TEXT NOT NULL,
 granted_credits INTEGER NOT NULL, remaining_credits INTEGER NOT NULL, expires_at REAL,
 status TEXT NOT NULL DEFAULT 'ACTIVE', created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_gt_wallet_user ON grand_test_credit_wallets(user_id,status,expires_at);
CREATE TABLE IF NOT EXISTS grand_test_credit_ledger (
 id TEXT PRIMARY KEY, wallet_id TEXT NOT NULL REFERENCES grand_test_credit_wallets(id), delta INTEGER NOT NULL,
 balance_after INTEGER NOT NULL, event_type TEXT NOT NULL, grand_test_id INTEGER,
 idempotency_key TEXT NOT NULL UNIQUE, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS grand_test_access (
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, grand_test_id INTEGER NOT NULL,
 source_entitlement_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ACTIVE',
 granted_at REAL NOT NULL, expires_at REAL, UNIQUE(user_id,grand_test_id));

CREATE TABLE IF NOT EXISTS verification_challenges (
 id TEXT PRIMARY KEY, user_id INTEGER, channel TEXT NOT NULL, purpose TEXT NOT NULL,
 destination_hash TEXT NOT NULL, destination_encrypted TEXT NOT NULL, code_hash TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'PENDING', attempts INTEGER NOT NULL DEFAULT 0,
 max_attempts INTEGER NOT NULL DEFAULT 5, resend_count INTEGER NOT NULL DEFAULT 0,
 expires_at REAL NOT NULL, next_send_at REAL NOT NULL, created_at REAL NOT NULL, verified_at REAL);
CREATE INDEX IF NOT EXISTS idx_verification_destination ON verification_challenges(destination_hash,channel,purpose,created_at);
CREATE TABLE IF NOT EXISTS verified_contacts (
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, channel TEXT NOT NULL,
 normalized_value_hash TEXT NOT NULL, encrypted_value TEXT NOT NULL, verified_at REAL NOT NULL,
 is_primary INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'ACTIVE',
 UNIQUE(channel,normalized_value_hash));
CREATE TABLE IF NOT EXISTS authentication_identities (
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, channel TEXT NOT NULL,
 normalized_value_hash TEXT NOT NULL, created_at REAL NOT NULL, last_used_at REAL NOT NULL,
 UNIQUE(channel,normalized_value_hash));

CREATE TABLE IF NOT EXISTS notification_templates (
 id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, channel TEXT NOT NULL,
 locale TEXT NOT NULL DEFAULT 'en-IN', version INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT',
 provider_template_id TEXT, subject_template TEXT, body_template TEXT NOT NULL,
 allowed_variables_json TEXT NOT NULL DEFAULT '[]', created_by INTEGER NOT NULL,
 approved_by INTEGER, created_at REAL NOT NULL, UNIQUE(event_type,channel,locale,version));
CREATE TABLE IF NOT EXISTS notification_preferences (
 user_id INTEGER NOT NULL, channel TEXT NOT NULL, category TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 1, updated_at REAL NOT NULL,
 PRIMARY KEY(user_id,channel,category));
CREATE TABLE IF NOT EXISTS notification_outbox (
 id TEXT PRIMARY KEY, event_id TEXT NOT NULL, user_id INTEGER, channel TEXT NOT NULL,
 template_id INTEGER, destination_encrypted TEXT NOT NULL, payload_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'PENDING', priority INTEGER NOT NULL DEFAULT 5,
 scheduled_at REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at REAL NOT NULL,
 provider_message_id TEXT, last_error TEXT, created_at REAL NOT NULL, sent_at REAL,
 UNIQUE(event_id,channel,template_id,destination_encrypted));
CREATE INDEX IF NOT EXISTS idx_outbox_due ON notification_outbox(status,next_attempt_at,priority);
CREATE TABLE IF NOT EXISTS notification_delivery_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, outbox_id TEXT NOT NULL, provider_event_id TEXT NOT NULL UNIQUE,
 status TEXT NOT NULL, payload_json TEXT NOT NULL, received_at REAL NOT NULL);

CREATE TABLE IF NOT EXISTS result_releases (
 id TEXT PRIMARY KEY, exam_id INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT',
 release_mode TEXT NOT NULL, scheduled_at REAL, released_at REAL, released_by INTEGER,
 audience_rules_json TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_result_releases_exam ON result_releases(exam_id,status);
CREATE TABLE IF NOT EXISTS result_release_recipients (
 release_id TEXT NOT NULL, user_id INTEGER NOT NULL, session_id INTEGER NOT NULL,
 status TEXT NOT NULL DEFAULT 'PUBLISHED', result_snapshot_hash TEXT NOT NULL,
 notified_at REAL, PRIMARY KEY(release_id,session_id));
CREATE INDEX IF NOT EXISTS idx_result_release_recipient ON result_release_recipients(user_id,session_id,status);
"""
