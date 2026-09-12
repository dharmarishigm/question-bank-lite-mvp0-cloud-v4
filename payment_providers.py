"""Payment provider boundary; provider secrets never leave this module."""
from __future__ import annotations
import hashlib,hmac,os
import requests

class PaymentProvider:
    name="base"
    def create_order(self,*,amount_minor,currency,receipt,notes):raise NotImplementedError
    def verify_checkout(self,*,order_id,payment_id,signature):raise NotImplementedError
    def verify_webhook(self,raw_body,signature):raise NotImplementedError
    def fetch_order(self,order_id):return None
    def refund(self,payment_id,amount_minor,notes):raise NotImplementedError

class FakePaymentProvider(PaymentProvider):
    name="fake"
    def create_order(self,*,amount_minor,currency,receipt,notes):return {"id":"fake_order_"+receipt,"amount":amount_minor,"currency":currency,"status":"created"}
    def verify_checkout(self,*,order_id,payment_id,signature):return hmac.compare_digest(signature,hmac.new(b"fake-secret",f"{order_id}|{payment_id}".encode(),hashlib.sha256).hexdigest())
    def verify_webhook(self,raw_body,signature):return hmac.compare_digest(signature,hmac.new(b"fake-webhook",raw_body,hashlib.sha256).hexdigest())
    def refund(self,payment_id,amount_minor,notes):return {"id":"fake_refund_"+payment_id,"status":"processed","amount":amount_minor}

class RazorpayProvider(PaymentProvider):
    name="razorpay"
    def __init__(self):
        self.key_id=os.environ["RAZORPAY_KEY_ID"];self.key_secret=os.environ["RAZORPAY_KEY_SECRET"]
        self.webhook_secret=os.environ["RAZORPAY_WEBHOOK_SECRET"]
    def create_order(self,*,amount_minor,currency,receipt,notes):
        response=requests.post("https://api.razorpay.com/v1/orders",auth=(self.key_id,self.key_secret),json={"amount":amount_minor,"currency":currency,"receipt":receipt,"notes":notes},timeout=15)
        response.raise_for_status();return response.json()
    def verify_checkout(self,*,order_id,payment_id,signature):
        expected=hmac.new(self.key_secret.encode(),f"{order_id}|{payment_id}".encode(),hashlib.sha256).hexdigest()
        return bool(signature) and hmac.compare_digest(signature,expected)
    def verify_webhook(self,raw_body,signature):
        expected=hmac.new(self.webhook_secret.encode(),raw_body,hashlib.sha256).hexdigest()
        return bool(signature) and hmac.compare_digest(signature,expected)
    def fetch_order(self,order_id):
        response=requests.get("https://api.razorpay.com/v1/orders/"+order_id,auth=(self.key_id,self.key_secret),timeout=15);response.raise_for_status();return response.json()
    def refund(self,payment_id,amount_minor,notes):
        response=requests.post(f"https://api.razorpay.com/v1/payments/{payment_id}/refund",auth=(self.key_id,self.key_secret),json={"amount":amount_minor,"notes":notes},timeout=15);response.raise_for_status();return response.json()

def provider():
    selected=os.getenv("PAYMENT_PROVIDER","fake").lower()
    if selected=="fake":return FakePaymentProvider()
    if selected=="razorpay":return RazorpayProvider()
    raise RuntimeError(f"Unsupported payment provider: {selected}")
