"""Transactional notification outbox and safe template rendering."""
from __future__ import annotations
import json,secrets,string,time

def enqueue(conn,*,event_id,user_id,channel,destination,payload,template_id=None,priority=5,scheduled_at=None):
    oid="msg_"+secrets.token_urlsafe(18);now=time.time()
    conn.execute("INSERT INTO notification_outbox(id,event_id,user_id,channel,template_id,destination_encrypted,payload_json,status,priority,scheduled_at,next_attempt_at,created_at) VALUES(?,?,?,?,?,?,?,'PENDING',?,?,?,?) ON CONFLICT(event_id,channel,template_id,destination_encrypted) DO NOTHING",
                 (oid,event_id,user_id,channel,template_id,destination,json.dumps(payload,separators=(',',':')),priority,scheduled_at or now,scheduled_at or now,now))
    return oid

def render(template,value_map,allowed):
    unknown=set()
    for _,name,_,_ in string.Formatter().parse(template):
        if name and name not in allowed:unknown.add(name)
    if unknown:raise ValueError("Template contains unapproved variables: "+", ".join(sorted(unknown)))
    return template.format_map({key:str(value_map.get(key,"")) for key in allowed})

def dispatch_due(conn,sender,limit=50,now=None):
    now=now or time.time();rows=conn.execute("SELECT * FROM notification_outbox WHERE status IN ('PENDING','RETRY') AND next_attempt_at<=? ORDER BY priority,created_at LIMIT ?",(now,limit)).fetchall();sent=0
    for row in rows:
        try:
            message_id=sender(row["channel"],row["destination_encrypted"],json.loads(row["payload_json"]))
            conn.execute("UPDATE notification_outbox SET status='SENT',provider_message_id=?,attempts=attempts+1,sent_at=? WHERE id=?",(message_id,now,row["id"]));sent+=1
        except Exception as exc:
            attempts=int(row["attempts"])+1;status="FAILED" if attempts>=8 else "RETRY";delay=min(21600,60*(2**min(attempts,8)))
            conn.execute("UPDATE notification_outbox SET status=?,attempts=?,next_attempt_at=?,last_error=? WHERE id=?",(status,attempts,now+delay,str(exc)[:500],row["id"]))
    conn.commit();return sent
