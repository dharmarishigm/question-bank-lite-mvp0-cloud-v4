"""Catalog, pricing, entitlement, trial, and grand-test credit rules."""
from __future__ import annotations

import json, secrets, time
from dataclasses import dataclass
from fastapi import HTTPException

PRODUCT_TYPES={"PROGRAM_TRIAL","PROGRAM_PREMIUM","GRAND_TEST_SINGLE","GRAND_TEST_CREDIT_PACK","GRAND_TEST_PASS","ORGANIZATION_PLAN"}
ENTITLEMENT_KINDS={"PROGRAM_ACCESS","GRAND_TEST_ACCESS","GRAND_TEST_CREDITS","GRAND_TEST_PASS","ORGANIZATION_ACCESS"}

def token(prefix: str) -> str: return prefix+secrets.token_urlsafe(18)

def audit(conn, action, entity_type, entity_id="", *, actor=None, reason="", metadata=None):
    conn.execute("INSERT INTO commerce_audit_log(actor_user_id,action,entity_type,entity_id,reason,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)",
                 (actor,action,entity_type,str(entity_id),reason,json.dumps(metadata or {},separators=(',',':')),time.time()))

def active_entitlement(conn,user_id,*,program_id=None,grand_test_id=None,now=None):
    now=now or time.time();clauses=["user_id=?","status='ACTIVE'","starts_at<=?","(ends_at IS NULL OR ends_at>?)"];params=[user_id,now,now]
    if grand_test_id is not None:
        clauses.append("(grand_test_id=? OR entitlement_type='GRAND_TEST_PASS')");params.append(grand_test_id)
    elif program_id is not None:
        clauses.append("program_id=?");params.append(program_id)
    return conn.execute("SELECT * FROM entitlements WHERE "+" AND ".join(clauses)+" ORDER BY CASE tier WHEN 'PREMIUM' THEN 0 WHEN 'TRIAL' THEN 1 ELSE 2 END,ends_at DESC",params).fetchone()

def effective_tier(conn,user_id,program_id=None,now=None):
    row=active_entitlement(conn,user_id,program_id=program_id,now=now)
    return (row["tier"] if row else "LEGACY").upper(), row

def grant_from_product(conn,user_id,product,source_type,source_id,now=None):
    now=now or time.time(); term=product["term_days"]; ends=now+int(term)*86400 if term else None
    eid=token("ent_");tier="TRIAL" if product["product_type"]=="PROGRAM_TRIAL" else "PREMIUM"
    conn.execute("INSERT INTO entitlements(id,user_id,source_type,source_id,entitlement_type,program_id,grand_test_id,tier,status,starts_at,ends_at,rules_snapshot_json,created_at) VALUES(?,?,?,?,?,?,?,?, 'ACTIVE',?,?,?,?) ON CONFLICT(user_id,source_type,source_id,entitlement_type) DO NOTHING",
                 (eid,user_id,source_type,str(source_id),product["entitlement_kind"],product["program_id"],product["grand_test_id"],tier,now,ends,product["inclusion_rules_json"],now))
    row=conn.execute("SELECT * FROM entitlements WHERE user_id=? AND source_type=? AND source_id=? AND entitlement_type=?",(user_id,source_type,str(source_id),product["entitlement_kind"])).fetchone()
    eid=row["id"]
    credits=int(product["credit_quantity"] or 0)
    if product["entitlement_kind"]=="GRAND_TEST_CREDITS" and credits:
        wid=token("gtw_")
        conn.execute("INSERT INTO grand_test_credit_wallets(id,user_id,program_id,source_entitlement_id,granted_credits,remaining_credits,expires_at,status,created_at) VALUES(?,?,?,?,?,?,?,'ACTIVE',?)",
                     (wid,user_id,product["program_id"],eid,credits,ends,now))
        conn.execute("INSERT INTO grand_test_credit_ledger(id,wallet_id,delta,balance_after,event_type,idempotency_key,created_at) VALUES(?,?,?,?,?,?,?)",
                     (token("gtl_"),wid,credits,credits,"GRANT",f"grant:{eid}",now))
    if product["entitlement_kind"]=="GRAND_TEST_ACCESS" and product["grand_test_id"]:
        conn.execute("INSERT INTO grand_test_access(id,user_id,grand_test_id,source_entitlement_id,status,granted_at,expires_at) VALUES(?,?,?,?, 'ACTIVE',?,?) ON CONFLICT(user_id,grand_test_id) DO NOTHING",
                     (token("gta_"),user_id,product["grand_test_id"],eid,now,ends))
    audit(conn,"ENTITLEMENT_GRANTED","ENTITLEMENT",eid,metadata={"user_id":user_id,"product_id":product["id"],"source_type":source_type})
    return dict(row)

def start_trial(conn,user_id,program_id,now=None):
    from admin_settings import get_setting
    now=now or time.time()
    existing=conn.execute("SELECT * FROM program_trials WHERE user_id=? AND program_id=?",(user_id,program_id)).fetchone()
    if existing: raise HTTPException(409,"Trial has already been used for this program")
    product=conn.execute("SELECT * FROM products WHERE product_type='PROGRAM_TRIAL' AND program_id=? AND status='ACTIVE' ORDER BY id DESC LIMIT 1",(program_id,)).fetchone()
    if not product: raise HTTPException(404,"Trial is not available for this program")
    data=dict(product)
    if not data.get("term_days"): data["term_days"]=int(get_setting("trial.duration_days",conn=conn))
    entitlement=grant_from_product(conn,user_id,data,"TRIAL",f"program:{program_id}",now)
    conn.execute("INSERT INTO program_trials(id,user_id,program_id,entitlement_id,started_at,expires_at) VALUES(?,?,?,?,?,?)",
                 (token("trl_"),user_id,program_id,entitlement["id"],now,entitlement["ends_at"]))
    return entitlement

def redeem_grand_test(conn,user_id,grand_test_id,program_id=None,now=None):
    now=now or time.time()
    existing=conn.execute("SELECT * FROM grand_test_access WHERE user_id=? AND grand_test_id=? AND status='ACTIVE' AND (expires_at IS NULL OR expires_at>?)",(user_id,grand_test_id,now)).fetchone()
    if existing:return dict(existing)
    params=[user_id,now]
    program_clause=""
    if program_id is not None: program_clause=" AND (program_id IS NULL OR program_id=?)";params.append(program_id)
    wallet=conn.execute("SELECT * FROM grand_test_credit_wallets WHERE user_id=? AND status='ACTIVE' AND remaining_credits>0 AND (expires_at IS NULL OR expires_at>?)"+program_clause+" ORDER BY expires_at IS NULL,expires_at,id LIMIT 1",params).fetchone()
    if not wallet: raise HTTPException(403,"No eligible grand-test credit is available")
    new_balance=int(wallet["remaining_credits"])-1
    conn.execute("UPDATE grand_test_credit_wallets SET remaining_credits=? WHERE id=? AND remaining_credits=?",(new_balance,wallet["id"],wallet["remaining_credits"]))
    access_id=token("gta_")
    conn.execute("INSERT INTO grand_test_access(id,user_id,grand_test_id,source_entitlement_id,status,granted_at,expires_at) VALUES(?,?,?,?, 'ACTIVE',?,?)",
                 (access_id,user_id,grand_test_id,wallet["source_entitlement_id"],now,wallet["expires_at"]))
    conn.execute("INSERT INTO grand_test_credit_ledger(id,wallet_id,delta,balance_after,event_type,grand_test_id,idempotency_key,created_at) VALUES(?,?,?,?,?,?,?,?)",
                 (token("gtl_"),wallet["id"],-1,new_balance,"REDEEM",grand_test_id,f"redeem:{user_id}:{grand_test_id}",now))
    audit(conn,"GRAND_TEST_REDEEMED","GRAND_TEST_ACCESS",access_id,metadata={"wallet_id":wallet["id"],"grand_test_id":grand_test_id})
    return dict(conn.execute("SELECT * FROM grand_test_access WHERE id=?",(access_id,)).fetchone())

@dataclass
class AccessDecision:
    allowed: bool
    reason_code: str
    entitlement_id: str | None = None
    tier: str | None = None

def authorize(conn,user_id,action,*,program_id=None,grand_test_id=None,now=None):
    from admin_settings import get_setting
    if not get_setting("commerce.access_gates",conn=conn): return AccessDecision(True,"GATES_DISABLED",tier="LEGACY")
    ent=active_entitlement(conn,user_id,program_id=program_id,grand_test_id=grand_test_id,now=now)
    if ent:return AccessDecision(True,"ENTITLED",ent["id"],ent["tier"])
    if grand_test_id is not None:
        access=conn.execute("SELECT * FROM grand_test_access WHERE user_id=? AND grand_test_id=? AND status='ACTIVE' AND (expires_at IS NULL OR expires_at>?)",(user_id,grand_test_id,now or time.time())).fetchone()
        if access:return AccessDecision(True,"ENTITLED",access["source_entitlement_id"],"PREMIUM")
    return AccessDecision(False,"NO_ENTITLEMENT")

def exam_scope(conn,exam_id):
    grand=conn.execute("SELECT id,program_id FROM grand_tests WHERE exam_id=?",(exam_id,)).fetchone()
    if grand:return {"program_id":grand["program_id"],"grand_test_id":grand["id"]}
    program=conn.execute("SELECT program_id FROM program_exam_jobs WHERE exam_id=? ORDER BY id DESC LIMIT 1",(exam_id,)).fetchone()
    return {"program_id":program["program_id"] if program else None,"grand_test_id":None}

def authorize_exam(conn,user_id,exam_id,action="START_EXAM"):
    scope=exam_scope(conn,exam_id)
    return authorize(conn,user_id,action,program_id=scope["program_id"],grand_test_id=scope["grand_test_id"])

def verified_student_identity(conn,user):
    if bool(user["email_verified"]):return True
    return bool(conn.execute("SELECT 1 FROM verified_contacts WHERE user_id=? AND status='ACTIVE'",(user["id"],)).fetchone())
