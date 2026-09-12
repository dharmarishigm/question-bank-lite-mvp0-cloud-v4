"""Price quotes, orders, checkout verification, and idempotent webhooks."""
from __future__ import annotations
import hashlib,json,secrets,time
from contextlib import closing
from fastapi import APIRouter,HTTPException,Request,Response
from pydantic import BaseModel,Field
from platform_api import _auth,db,require_admin
from admin_settings import get_setting
from commerce_service import audit,grant_from_product,token
from communication_service import enqueue
from payment_providers import provider

router=APIRouter(prefix="/api",tags=["Payments"])

class QuoteRequest(BaseModel):product_id:int;coupon:str|None=Field(default=None,max_length=64)

@router.post("/commerce/quotes",status_code=201)
def quote(body:QuoteRequest,request:Request):
    user=_auth(request,True);now=time.time()
    with closing(db()) as conn:
        row=conn.execute("SELECT p.*,pr.id price_id,pr.currency,pr.list_amount_minor,pr.sale_amount_minor,pr.tax_behavior,pr.tax_rate_bps FROM products p JOIN prices pr ON pr.product_id=p.id WHERE p.id=? AND p.status='ACTIVE' AND pr.status='ACTIVE' AND pr.valid_from<=? AND (pr.valid_until IS NULL OR pr.valid_until>?) ORDER BY pr.version DESC LIMIT 1",(body.product_id,now,now)).fetchone()
        if not row:raise HTTPException(404,"Product or active price not found")
        if row["product_type"] in {"PROGRAM_TRIAL","ORGANIZATION_PLAN"}:raise HTTPException(422,"This product is not available through checkout")
        discount=0;discount_id=None
        if body.coupon:
            d=conn.execute("SELECT * FROM discounts WHERE upper(code)=upper(?) AND status='ACTIVE' AND starts_at<=? AND (ends_at IS NULL OR ends_at>?)",(body.coupon.strip(),now,now)).fetchone()
            if not d:raise HTTPException(422,"Coupon is invalid or expired")
            total_uses=conn.execute("SELECT COUNT(*) n FROM discount_redemptions WHERE discount_id=?",(d["id"],)).fetchone()["n"]
            user_uses=conn.execute("SELECT COUNT(*) n FROM discount_redemptions WHERE discount_id=? AND user_id=?",(d["id"],user["id"])).fetchone()["n"]
            if (d["max_redemptions"] is not None and total_uses>=d["max_redemptions"]) or user_uses>=d["max_per_user"]:raise HTTPException(422,"Coupon redemption limit has been reached")
            if d["first_purchase_only"] and conn.execute("SELECT 1 FROM orders WHERE user_id=? AND status='PAID'",(user["id"],)).fetchone():raise HTTPException(422,"Coupon is for first purchases only")
            base=int(row["sale_amount_minor"])
            if base<int(d["minimum_amount_minor"]):raise HTTPException(422,"Order does not meet the coupon minimum")
            discount=min(base,(base*int(d["value"])//10000) if d["kind"]=="PERCENT_BPS" else int(d["value"]));discount_id=d["id"]
        subtotal=int(row["sale_amount_minor"]);tax=0
        if row["tax_behavior"]=="EXCLUSIVE":tax=(subtotal-discount)*int(row["tax_rate_bps"])//10000
        total=subtotal-discount+tax;qid=token("quo_");ttl=int(get_setting("commerce.quote_ttl_seconds",conn=conn))
        snapshot={"product_code":row["code"],"product_name":row["name"],"list_amount_minor":row["list_amount_minor"],"sale_amount_minor":subtotal,"tax_rate_bps":row["tax_rate_bps"]}
        conn.execute("INSERT INTO checkout_quotes(id,user_id,product_id,price_id,currency,subtotal_minor,discount_minor,tax_minor,total_minor,discount_id,pricing_snapshot_json,expires_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(qid,user["id"],body.product_id,row["price_id"],row["currency"],subtotal,discount,tax,total,discount_id,json.dumps(snapshot),now+ttl,now));conn.commit()
    return {"id":qid,"currency":row["currency"],"subtotal_minor":subtotal,"discount_minor":discount,"tax_minor":tax,"total_minor":total,"expires_at":now+ttl}

class OrderRequest(BaseModel):quote_id:str;idempotency_key:str=Field(min_length=8,max_length=100)

@router.post("/commerce/orders")
def create_order(body:OrderRequest,request:Request,response:Response):
    user=_auth(request,True);now=time.time()
    with closing(db()) as conn:
        existing=conn.execute("SELECT * FROM orders WHERE user_id=? AND idempotency_key=?",(user["id"],body.idempotency_key)).fetchone()
        if existing:return dict(existing)
        q=conn.execute("SELECT q.*,p.name product_name,p.code product_code,p.product_type,p.program_id,p.grand_test_id,p.entitlement_kind,p.term_days,p.credit_quantity,p.inclusion_rules_json FROM checkout_quotes q JOIN products p ON p.id=q.product_id WHERE q.id=? AND q.user_id=?",(body.quote_id,user["id"])).fetchone()
        if not q:raise HTTPException(404,"Quote not found")
        if q["consumed_at"] or q["expires_at"]<=now:raise HTTPException(409,"Quote has expired or was already used")
        oid=token("ord_");number="MIQ-"+time.strftime("%Y%m%d",time.gmtime(now))+"-"+secrets.token_hex(4).upper()
        product_snapshot={k:q[k] for k in ("product_name","product_code","product_type","program_id","grand_test_id","entitlement_kind","term_days","credit_quantity","inclusion_rules_json")}
        conn.execute("UPDATE checkout_quotes SET consumed_at=? WHERE id=? AND consumed_at IS NULL",(now,q["id"]))
        conn.execute("INSERT INTO orders(id,order_number,user_id,quote_id,product_id,price_id,status,currency,subtotal_minor,discount_minor,tax_minor,total_minor,customer_snapshot_json,product_snapshot_json,pricing_snapshot_json,idempotency_key,created_at) VALUES(?,?,?,?,?,?,'PAYMENT_PENDING',?,?,?,?,?,?,?,?,?,?)",(oid,number,user["id"],q["id"],q["product_id"],q["price_id"],q["currency"],q["subtotal_minor"],q["discount_minor"],q["tax_minor"],q["total_minor"],json.dumps({"email":user["email"],"name":user["display_name"]}),json.dumps(product_snapshot),q["pricing_snapshot_json"],body.idempotency_key,now));conn.commit()
    try:remote=provider().create_order(amount_minor=q["total_minor"],currency=q["currency"],receipt=number,notes={"local_order_id":oid})
    except Exception as exc:raise HTTPException(502,"Payment provider is temporarily unavailable") from exc
    pid=token("pay_")
    with closing(db()) as conn:
        conn.execute("INSERT INTO payment_attempts(id,order_id,provider,provider_order_id,status,amount_minor,currency,created_at,updated_at) VALUES(?,?,?,?, 'CREATED',?,?,?,?)",(pid,oid,provider().name,remote["id"],q["total_minor"],q["currency"],now,now));conn.commit()
    response.status_code=201
    return {"id":oid,"order_number":number,"status":"PAYMENT_PENDING","provider":provider().name,"provider_order_id":remote["id"],"amount_minor":q["total_minor"],"currency":q["currency"],"key_id":__import__('os').getenv("RAZORPAY_KEY_ID","")}

def fulfill(conn,order,payment_id,now):
    if order["status"]=="PAID":return
    product=conn.execute("SELECT * FROM products WHERE id=?",(order["product_id"],)).fetchone()
    conn.execute("UPDATE orders SET status='PAID',paid_at=? WHERE id=? AND status<>'PAID'",(now,order["id"]))
    conn.execute("UPDATE payment_attempts SET status='CAPTURED',provider_payment_id=?,captured_at=?,updated_at=? WHERE order_id=?",(payment_id,now,now,order["id"]))
    entitlement=grant_from_product(conn,order["user_id"],product,"ORDER",order["id"],now)
    quote=conn.execute("SELECT discount_id,discount_minor FROM checkout_quotes WHERE id=?",(order["quote_id"],)).fetchone()
    if quote and quote["discount_id"]:
        conn.execute("INSERT INTO discount_redemptions(discount_id,user_id,order_id,amount_minor,redeemed_at) VALUES(?,?,?,?,?) ON CONFLICT(order_id) DO NOTHING",(quote["discount_id"],order["user_id"],order["id"],quote["discount_minor"],now))
    enqueue(conn,event_id="payment:"+order["id"],user_id=order["user_id"],channel="EMAIL",destination=json.loads(order["customer_snapshot_json"])["email"],payload={"event":"PAYMENT_CAPTURED","order_number":order["order_number"],"amount_minor":order["total_minor"],"currency":order["currency"],"entitlement_id":entitlement["id"]})
    audit(conn,"PAYMENT_CAPTURED","ORDER",order["id"],metadata={"provider_payment_id":payment_id})

class Confirmation(BaseModel):provider_order_id:str;provider_payment_id:str;signature:str

@router.post("/commerce/payments/confirm")
def confirm(body:Confirmation,request:Request):
    user=_auth(request,True)
    with closing(db()) as conn:
        order=conn.execute("SELECT o.* FROM orders o JOIN payment_attempts p ON p.order_id=o.id WHERE p.provider_order_id=? AND o.user_id=?",(body.provider_order_id,user["id"])).fetchone()
        if not order:raise HTTPException(404,"Order not found")
        if not provider().verify_checkout(order_id=body.provider_order_id,payment_id=body.provider_payment_id,signature=body.signature):raise HTTPException(400,"Payment signature is invalid")
        fulfill(conn,order,body.provider_payment_id,time.time());conn.commit()
    return {"order_id":order["id"],"status":"PAID"}

@router.get("/commerce/orders/{order_id}")
def order_status(order_id:str,request:Request):
    user=_auth(request)
    with closing(db()) as conn:row=conn.execute("SELECT * FROM orders WHERE id=? AND user_id=?",(order_id,user["id"])).fetchone()
    if not row:raise HTTPException(404,"Order not found")
    return dict(row)

class RefundRequest(BaseModel):
    amount_minor:int|None=Field(default=None,gt=0)
    reason:str=Field(min_length=5,max_length=500)

@router.post("/admin/orders/{order_id}/refund",status_code=202)
def refund_order(order_id:str,body:RefundRequest,request:Request):
    admin=require_admin(_auth(request,True));now=time.time()
    with closing(db()) as conn:
        order=conn.execute("SELECT * FROM orders WHERE id=? AND status IN ('PAID','PARTIALLY_REFUNDED')",(order_id,)).fetchone()
        payment=conn.execute("SELECT * FROM payment_attempts WHERE order_id=? AND status='CAPTURED' ORDER BY captured_at DESC LIMIT 1",(order_id,)).fetchone()
        if not order or not payment:raise HTTPException(404,"Captured order not found")
        amount=body.amount_minor or int(order["total_minor"])
        if amount>int(order["total_minor"]):raise HTTPException(422,"Refund exceeds the paid amount")
        if amount==int(order["total_minor"]):
            ent=conn.execute("SELECT * FROM entitlements WHERE source_type='ORDER' AND source_id=? AND status='ACTIVE'",(order_id,)).fetchone()
            if ent:
                wallet=conn.execute("SELECT * FROM grand_test_credit_wallets WHERE source_entitlement_id=?",(ent["id"],)).fetchone()
                if wallet and wallet["remaining_credits"]!=wallet["granted_credits"]:raise HTTPException(409,"Grand-test credits were used; refund requires manual review")
    try:remote=provider().refund(payment["provider_payment_id"],amount,{"local_order_id":order_id,"reason":body.reason})
    except Exception as exc:raise HTTPException(502,"Refund provider is temporarily unavailable") from exc
    rid=token("ref_");processed=remote.get("status") in {"processed","refunded"}
    with closing(db()) as conn:
        conn.execute("BEGIN IMMEDIATE");conn.execute("INSERT INTO refunds(id,order_id,payment_attempt_id,provider_refund_id,amount_minor,status,reason,initiated_by,created_at,completed_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(rid,order_id,payment["id"],remote["id"],amount,"COMPLETED" if processed else "PENDING",body.reason,admin["id"],now,now if processed else None))
        if processed:
            full=amount==int(order["total_minor"]);conn.execute("UPDATE orders SET status=? WHERE id=?",("REFUNDED" if full else "PARTIALLY_REFUNDED",order_id))
            if full:
                conn.execute("UPDATE entitlements SET status='REVOKED',revoked_at=?,revoked_by=? WHERE source_type='ORDER' AND source_id=? AND status='ACTIVE'",(now,admin["id"],order_id));conn.execute("UPDATE grand_test_credit_wallets SET status='REVOKED' WHERE source_entitlement_id IN (SELECT id FROM entitlements WHERE source_type='ORDER' AND source_id=?)",(order_id,))
            enqueue(conn,event_id="refund:"+rid,user_id=order["user_id"],channel="EMAIL",destination=json.loads(order["customer_snapshot_json"])["email"],payload={"event":"REFUND_COMPLETED","order_number":order["order_number"],"amount_minor":amount,"currency":order["currency"]})
        audit(conn,"REFUND_INITIATED","REFUND",rid,actor=admin["id"],reason=body.reason,metadata={"order_id":order_id,"amount_minor":amount});conn.commit()
    return {"id":rid,"status":"COMPLETED" if processed else "PENDING","provider_refund_id":remote["id"]}

@router.post("/webhooks/razorpay")
async def razorpay_webhook(request:Request):
    raw=await request.body();signature=request.headers.get("x-razorpay-signature","")
    if not provider().verify_webhook(raw,signature):raise HTTPException(400,"Invalid webhook signature")
    payload=json.loads(raw);event_id=request.headers.get("x-razorpay-event-id") or hashlib.sha256(raw).hexdigest();kind=str(payload.get("event",""));now=time.time()
    with closing(db()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing=conn.execute("SELECT * FROM payment_webhook_events WHERE provider=? AND provider_event_id=?",(provider().name,event_id)).fetchone()
        if existing:return {"accepted":True,"duplicate":True}
        conn.execute("INSERT INTO payment_webhook_events(provider,provider_event_id,signature_valid,event_type,payload_json,received_at,processing_status) VALUES(?,?,1,?,?,?,'RECEIVED')",(provider().name,event_id,kind,raw.decode("utf-8"),now))
        event_payload=payload.get("payload") or {};payment_entity=(event_payload.get("payment") or {}).get("entity") or {};order_entity=(event_payload.get("order") or {}).get("entity") or {}
        entity=payment_entity or order_entity;provider_order_id=payment_entity.get("order_id") or order_entity.get("id");payment_id=payment_entity.get("id","")
        if kind in {"payment.captured","order.paid"} and provider_order_id:
            order=conn.execute("SELECT o.* FROM orders o JOIN payment_attempts p ON p.order_id=o.id WHERE p.provider_order_id=?",(provider_order_id,)).fetchone()
            if order:
                received=payment_entity.get("amount") if payment_entity else order_entity.get("amount_paid")
                if received is not None and int(received)!=int(order["total_minor"]):raise HTTPException(409,"Webhook amount mismatch")
                fulfill(conn,order,payment_id,now)
        conn.execute("UPDATE payment_webhook_events SET processing_status='PROCESSED',processed_at=? WHERE provider=? AND provider_event_id=?",(now,provider().name,event_id));conn.commit()
    return {"accepted":True}
