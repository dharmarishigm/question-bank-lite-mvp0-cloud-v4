"""Transactional email/SMS adapters. Live credentials remain environment-only."""
from __future__ import annotations
import json,os,smtplib,ssl,uuid
from email.message import EmailMessage
import requests
from identity_verification import decrypt

def destination(value):return decrypt(value) if value.startswith("gAAAA") else value

def fake_sender(channel,target,payload):return "fake_"+uuid.uuid4().hex

def smtp_sender(channel,target,payload):
    if channel!="EMAIL":raise RuntimeError("SMTP adapter only sends email")
    message=EmailMessage();message["From"]=os.environ["EMAIL_FROM"];message["To"]=destination(target);message["Subject"]=payload.get("subject") or "MeritIQra notification"
    message.set_content(payload.get("text") or _plain(payload))
    host=os.environ["SMTP_HOST"];port=int(os.getenv("SMTP_PORT","587"))
    with smtplib.SMTP(host,port,timeout=15) as client:
        client.starttls(context=ssl.create_default_context());client.login(os.environ["SMTP_USERNAME"],os.environ["SMTP_PASSWORD"]);client.send_message(message)
    return message.get("Message-ID") or "smtp_"+uuid.uuid4().hex

def http_sms_sender(channel,target,payload):
    if channel!="SMS":raise RuntimeError("SMS adapter only sends SMS")
    code=decrypt(payload["code_encrypted"]) if payload.get("code_encrypted") else payload.get("code","")
    values={"to":destination(target),"template_id":os.environ["SMS_OTP_TEMPLATE_ID"],"sender_id":os.environ["SMS_SENDER_ID"],"pe_id":os.environ["SMS_PE_ID"],"variables":{"otp":code,"minutes":payload.get("expires_minutes")}}
    response=requests.post(os.environ["SMS_API_URL"],headers={"Authorization":"Bearer "+os.environ["SMS_API_KEY"]},json=values,timeout=15);response.raise_for_status()
    result=response.json();return str(result.get("message_id") or result.get("id") or uuid.uuid4().hex)

def _plain(payload):
    event=payload.get("event","Notification").replace("_"," ").title()
    lines=[event]
    for key,value in payload.items():
        if key not in {"event","code","code_encrypted","subject","html","text"}:lines.append(f"{key.replace('_',' ').title()}: {value}")
    return "\n".join(lines)

def sender(channel,target,payload):
    if os.getenv("APP_ENV") in {"test","development"} and os.getenv("NOTIFICATION_PROVIDER","fake")=="fake":return fake_sender(channel,target,payload)
    if channel=="EMAIL":
        if os.getenv("EMAIL_PROVIDER","fake")=="smtp":return smtp_sender(channel,target,payload)
        if os.getenv("EMAIL_PROVIDER","fake")=="fake":return fake_sender(channel,target,payload)
        raise RuntimeError("Configured email provider adapter is unavailable")
    if channel=="SMS":
        if os.getenv("SMS_PROVIDER","fake")=="http":return http_sms_sender(channel,target,payload)
        if os.getenv("SMS_PROVIDER","fake")=="fake":return fake_sender(channel,target,payload)
        raise RuntimeError("Configured SMS provider adapter is unavailable")
    if channel=="PUSH":return fake_sender(channel,target,payload)
    raise RuntimeError("Unsupported notification channel")
