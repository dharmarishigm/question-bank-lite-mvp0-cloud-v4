import hashlib,hmac,os,sqlite3,tempfile
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
import app
from platform_api import init_platform

@pytest.fixture
def commerce_clients():
    with tempfile.TemporaryDirectory() as folder:
        path=str(Path(folder)/"commerce.db")
        with sqlite3.connect(path) as conn:conn.executescript(app.SCHEMA)
        env={"APP_ENV":"test","AUTH_MODE":"mock","ADMIN_EMAILS":"admin@example.test","PAYMENT_PROVIDER":"fake","OTP_EXPOSE_TEST_CODE":"1"}
        with patch.object(app,"DB_PATH",path),patch.dict(os.environ,env,clear=False):
            init_platform()
            with TestClient(app.app) as admin,TestClient(app.app) as student:
                for client,email in ((admin,"admin@example.test"),(student,"student@example.test")):
                    response=client.post("/api/auth/mock",json={"email":email});assert response.status_code==200,response.text
                    client.headers["X-CSRF-Token"]=client.cookies["qb_csrf"]
                yield admin,student

def seed_program(admin):
    response=admin.post("/api/programs",json={"code":"COMMERCE","name":"Commerce Test Program"});assert response.status_code==201,response.text
    return response.json()["id"]

def seed_product(admin,program_id,kind="PROGRAM_PREMIUM",credits=None):
    response=admin.post("/api/admin/products",json={"code":kind+(f"_{credits}" if credits else ""),"name":"Test Product","product_type":kind,"status":"ACTIVE","program_id":program_id,"entitlement_kind":"GRAND_TEST_CREDITS" if credits else "PROGRAM_ACCESS","term_days":90,"credit_quantity":credits})
    assert response.status_code==201,response.text;product=response.json()
    price=admin.post(f"/api/admin/products/{product['id']}/prices",json={"list_amount_minor":99900,"sale_amount_minor":69900,"status":"ACTIVE"});assert price.status_code==201,price.text
    return product

def test_admin_settings_are_typed_revisioned_and_audited(commerce_clients):
    admin,student=commerce_clients
    assert student.get("/api/admin/settings").status_code==403
    changed=admin.put("/api/admin/settings/commerce.enabled",json={"value":True,"revision":0,"reason":"Enable test commerce"});assert changed.status_code==200,changed.text
    assert admin.put("/api/admin/settings/commerce.enabled",json={"value":False,"revision":0,"reason":"Stale update"}).status_code==409
    assert admin.put("/api/admin/settings/otp.expiry_seconds",json={"value":10,"revision":0,"reason":"Unsafe"}).status_code==422

def test_trial_once_and_tier_quota_policy(commerce_clients):
    admin,student=commerce_clients;program_id=seed_program(admin)
    response=admin.post("/api/admin/products",json={"code":"TRIAL_COMMERCE","name":"Trial","product_type":"PROGRAM_TRIAL","status":"ACTIVE","program_id":program_id,"entitlement_kind":"PROGRAM_ACCESS","term_days":7});assert response.status_code==201,response.text
    trial=student.post("/api/trials",json={"program_id":program_id});assert trial.status_code==201,trial.text
    assert trial.json()["tier"]=="TRIAL"
    assert student.post("/api/trials",json={"program_id":program_id}).status_code==409
    with app.connect() as conn:
        from explanation_quota import quota_policy
        uid=student.get("/api/auth/me").json()["id"]
        assert quota_policy(conn,uid)==(15,18000,"TRIAL")

def test_fake_payment_is_idempotent_and_grants_once(commerce_clients):
    admin,student=commerce_clients;program_id=seed_program(admin);product=seed_product(admin,program_id)
    quote=student.post("/api/commerce/quotes",json={"product_id":product["id"]});assert quote.status_code==201,quote.text
    order=student.post("/api/commerce/orders",json={"quote_id":quote.json()["id"],"idempotency_key":"checkout-123"});assert order.status_code==201,order.text
    duplicate=student.post("/api/commerce/orders",json={"quote_id":quote.json()["id"],"idempotency_key":"checkout-123"});assert duplicate.status_code==200
    body=order.json();payment_id="fake_payment_1";signature=hmac.new(b"fake-secret",f"{body['provider_order_id']}|{payment_id}".encode(),hashlib.sha256).hexdigest()
    confirmed=student.post("/api/commerce/payments/confirm",json={"provider_order_id":body["provider_order_id"],"provider_payment_id":payment_id,"signature":signature});assert confirmed.status_code==200,confirmed.text
    assert student.post("/api/commerce/payments/confirm",json={"provider_order_id":body["provider_order_id"],"provider_payment_id":payment_id,"signature":signature}).status_code==200
    assert len(student.get("/api/me/entitlements").json()["items"])==1
    with app.connect() as conn:assert conn.execute("SELECT COUNT(*) n FROM notification_outbox").fetchone()["n"]==1

def test_phone_otp_is_hashed_single_use_and_updates_profile(commerce_clients):
    _,student=commerce_clients
    requested=student.post("/api/auth/otp/request",json={"channel":"SMS","destination":"9876543210","purpose":"PHONE_CHANGE"});assert requested.status_code==202,requested.text
    data=requested.json();assert data["test_code"]
    assert student.post("/api/auth/otp/verify",json={"challenge_id":data["challenge_id"],"code":"000000"}).status_code==422
    verified=student.post("/api/auth/otp/verify",json={"challenge_id":data["challenge_id"],"code":data["test_code"]});assert verified.status_code==200,verified.text
    assert student.post("/api/auth/otp/verify",json={"challenge_id":data["challenge_id"],"code":data["test_code"]}).status_code==409
    with app.connect() as conn:
        row=conn.execute("SELECT * FROM verification_challenges WHERE id=?",(data["challenge_id"],)).fetchone()
        assert row["code_hash"]!=data["test_code"] and "+919876543210" not in row["destination_encrypted"]

def test_phone_registration_and_login_create_one_account(commerce_clients):
    _,_=commerce_clients
    with TestClient(app.app) as mobile:
        requested=mobile.post("/api/auth/otp/request",json={"channel":"SMS","destination":"9123456789","purpose":"REGISTRATION"});assert requested.status_code==202,requested.text
        data=requested.json();verified=mobile.post("/api/auth/otp/verify",json={"challenge_id":data["challenge_id"],"code":data["test_code"]});assert verified.status_code==200,verified.text
        first=mobile.get("/api/auth/me");assert first.status_code==200,first.text;first_id=first.json()["id"]
    with app.connect() as conn:conn.execute("UPDATE verification_challenges SET next_send_at=0");conn.commit()
    with TestClient(app.app) as returning:
        requested=returning.post("/api/auth/otp/request",json={"channel":"SMS","destination":"+91 91234 56789","purpose":"LOGIN"});assert requested.status_code==202,requested.text
        data=requested.json();assert returning.post("/api/auth/otp/verify",json={"challenge_id":data["challenge_id"],"code":data["test_code"]}).status_code==200
        assert returning.get("/api/auth/me").json()["id"]==first_id
