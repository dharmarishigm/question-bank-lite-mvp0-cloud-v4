"""Typed, audited runtime settings. Secrets remain environment-only."""
from __future__ import annotations

import json, os, time
from contextlib import closing
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from platform_api import _auth, db, require_admin

router = APIRouter(prefix="/api/admin/settings", tags=["Commerce administration"])

@dataclass(frozen=True)
class SettingDefinition:
    kind: str
    default: Any
    minimum: int | None = None
    maximum: int | None = None

DEFINITIONS = {
    "commerce.enabled": SettingDefinition("bool", False),
    "commerce.access_gates": SettingDefinition("bool", False),
    "commerce.quote_ttl_seconds": SettingDefinition("int", 900, 60, 3600),
    "trial.duration_days": SettingDefinition("int", 7, 1, 90),
    "ai_quota.trial.limit": SettingDefinition("int", 15, 1, 1000),
    "ai_quota.trial.window_seconds": SettingDefinition("int", 18000, 300, 86400),
    "ai_quota.premium.limit": SettingDefinition("int", 60, 1, 5000),
    "ai_quota.premium.window_seconds": SettingDefinition("int", 7200, 300, 86400),
    "ai_quota.legacy.limit": SettingDefinition("int", 10, 1, 1000),
    "ai_quota.legacy.window_seconds": SettingDefinition("int", 3600, 300, 86400),
    "otp.expiry_seconds": SettingDefinition("int", 300, 60, 900),
    "otp.max_attempts": SettingDefinition("int", 5, 1, 10),
    "otp.resend_seconds": SettingDefinition("int", 30, 15, 300),
    "notifications.enabled": SettingDefinition("bool", False),
    "results.release_gate": SettingDefinition("bool", False),
    "demo_book.enabled": SettingDefinition("bool", False),
    "demo_book.title": SettingDefinition("str", "MeritIQra Demo Book"),
    "demo_book.url": SettingDefinition("str", ""),
}

def _validate(key: str, value: Any) -> Any:
    definition = DEFINITIONS.get(key)
    if not definition: raise HTTPException(422, f"Unknown setting: {key}")
    if definition.kind == "bool" and type(value) is not bool: raise HTTPException(422, f"{key} must be a boolean")
    if definition.kind == "int":
        if type(value) is not int: raise HTTPException(422, f"{key} must be an integer")
        if definition.minimum is not None and value < definition.minimum: raise HTTPException(422, f"{key} is below its safe minimum")
        if definition.maximum is not None and value > definition.maximum: raise HTTPException(422, f"{key} exceeds its safe maximum")
    if definition.kind == "str" and not isinstance(value, str): raise HTTPException(422, f"{key} must be text")
    return value

def get_setting(key: str, default: Any = None, conn=None) -> Any:
    definition = DEFINITIONS.get(key)
    fallback = definition.default if definition else default
    owns = conn is None
    connection = conn or db()
    try:
        row = connection.execute("SELECT value_json FROM admin_settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value_json"]) if row else fallback
    finally:
        if owns: connection.close()

class SettingUpdate(BaseModel):
    value: Any
    revision: int = Field(ge=0)
    reason: str = Field(min_length=3, max_length=500)

@router.get("")
def list_settings(request: Request):
    require_admin(_auth(request))
    with closing(db()) as conn:
        rows = {r["key"]: r for r in conn.execute("SELECT * FROM admin_settings").fetchall()}
    return {"items":[{"key":key,"value":json.loads(rows[key]["value_json"]) if key in rows else definition.default,
                      "type":definition.kind,"revision":rows[key]["revision"] if key in rows else 0,
                      "minimum":definition.minimum,"maximum":definition.maximum}
                     for key,definition in DEFINITIONS.items()]}

@router.put("/{key:path}")
def update_setting(key: str, body: SettingUpdate, request: Request):
    admin = require_admin(_auth(request, True)); value = _validate(key, body.value); now = time.time()
    with closing(db()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT revision FROM admin_settings WHERE key=?", (key,)).fetchone()
        current = int(row["revision"]) if row else 0
        if current != body.revision: raise HTTPException(409, "Setting changed. Refresh before saving.")
        if row:
            conn.execute("UPDATE admin_settings SET value_json=?,value_type=?,revision=revision+1,updated_by=?,updated_at=? WHERE key=?",
                         (json.dumps(value), DEFINITIONS[key].kind, admin["id"], now, key))
        else:
            conn.execute("INSERT INTO admin_settings(key,value_json,value_type,revision,updated_by,updated_at) VALUES(?,?,?,?,?,?)",
                         (key,json.dumps(value),DEFINITIONS[key].kind,1,admin["id"],now))
        conn.execute("INSERT INTO commerce_audit_log(actor_user_id,action,entity_type,entity_id,reason,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)",
                     (admin["id"],"SETTING_UPDATED","SETTING",key,body.reason,json.dumps({"previous_revision":current}),now))
        conn.commit()
    return {"key":key,"value":value,"revision":current+1}

@router.get("/integrations/readiness")
def readiness(request: Request):
    require_admin(_auth(request))
    providers = {
        "payments":{"provider":os.getenv("PAYMENT_PROVIDER","fake"),"configured":bool(os.getenv("RAZORPAY_KEY_ID") and os.getenv("RAZORPAY_KEY_SECRET")) if os.getenv("PAYMENT_PROVIDER")=="razorpay" else True,"webhook_configured":bool(os.getenv("RAZORPAY_WEBHOOK_SECRET")) if os.getenv("PAYMENT_PROVIDER")=="razorpay" else True},
        "email":{"provider":os.getenv("EMAIL_PROVIDER","fake"),"configured":os.getenv("EMAIL_PROVIDER","fake")=="fake" or bool(os.getenv("EMAIL_FROM"))},
        "sms":{"provider":os.getenv("SMS_PROVIDER","fake"),"configured":os.getenv("SMS_PROVIDER","fake")=="fake" or bool(os.getenv("SMS_API_KEY"))},
        "otp":{"pepper_configured":bool(os.getenv("OTP_PEPPER")) or os.getenv("APP_ENV") in {"test","development"},"encryption_configured":bool(os.getenv("CONTACT_ENCRYPTION_KEY")) or os.getenv("APP_ENV") in {"test","development"}},
    }
    issues=[]
    for name,value in providers.items():
        if value.get("configured") is False: issues.append(f"{name} provider configuration is incomplete")
    if not providers["otp"]["pepper_configured"]: issues.append("OTP_PEPPER is missing")
    if not providers["otp"]["encryption_configured"]: issues.append("CONTACT_ENCRYPTION_KEY is missing")
    return {**providers,"blocking_issues":issues}
