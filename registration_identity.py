"""Canonical registration reservations; existing learner history is never merged or deleted."""
import re,time
from contextlib import closing
from fastapi import HTTPException

SCHEMA="""
CREATE TABLE IF NOT EXISTS registration_identities (
 id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, address TEXT NOT NULL,
 owner_email TEXT NOT NULL, created_at REAL NOT NULL, UNIQUE(kind,address));
"""

def email_key(value):
    return str(value or '').strip().lower()

def phone_key(value):
    digits=re.sub(r'\D','',str(value or ''))
    if len(digits)==12 and digits.startswith('91'):digits=digits[2:]
    if len(digits)==10:return '+91'+digits
    return '+'+digits if digits else ''

def claim(conn,kind,address,email):
    if not address:return
    owner=email_key(email)
    conn.execute('INSERT INTO registration_identities(kind,address,owner_email,created_at) VALUES(?,?,?,?) ON CONFLICT(kind,address) DO NOTHING',(kind,address,owner,time.time()))
    # The update serializes claims across Cloud Run instances, including an already-existing row.
    conn.execute('UPDATE registration_identities SET created_at=created_at WHERE kind=? AND address=?',(kind,address))
    row=conn.execute('SELECT owner_email FROM registration_identities WHERE kind=? AND address=?',(kind,address)).fetchone()
    if row['owner_email']!=owner:raise HTTPException(409,'This mobile number is already registered. Use the existing account or a different number.')

def reserve_email(conn,email):claim(conn,'EMAIL',email_key(email),email)
def reserve_phone(conn,phone,email):claim(conn,'PHONE',phone_key(phone),email)

def seed(conn):
    records=[(r['email'],r['phone_number']) for r in conn.execute('SELECT email,phone_number FROM users')]
    records.extend((r['registered_email'],r['phone_number']) for r in conn.execute("SELECT registered_email,phone_number FROM pending_exam_registrations WHERE status IN ('PENDING','LINKED')"))
    for email,phone in records:
        for kind,address in [('EMAIL',email_key(email)),('PHONE',phone_key(phone))]:
            if not address:continue
            row=conn.execute('SELECT owner_email FROM registration_identities WHERE kind=? AND address=?',(kind,address)).fetchone()
            if row and row['owner_email']!=email_key(email):
                conn.execute("UPDATE registration_identities SET owner_email='__legacy_conflict__' WHERE kind=? AND address=?",(kind,address))
            elif not row:conn.execute('INSERT INTO registration_identities(kind,address,owner_email,created_at) VALUES(?,?,?,?)',(kind,address,email_key(email),time.time()))

def init_identities():
    from platform_api import db
    with closing(db()) as conn:
        conn.executescript(SCHEMA)
        if not conn.execute('SELECT 1 FROM registration_identities LIMIT 1').fetchone():seed(conn)
        conn.commit()
