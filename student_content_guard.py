"""Shared rolling read quota for authenticated student exam/result content."""
from contextlib import closing
import math,re,time
from fastapi import HTTPException
SCHEMA='''CREATE TABLE IF NOT EXISTS student_content_reads (
 id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL REFERENCES users(id),read_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_student_content_reads ON student_content_reads(user_id,read_at);'''
MINUTE_LIMIT=120
HOUR_LIMIT=2000
PATTERN=re.compile(r'^/api/(?:sessions/\d+(?:/question-flags)?|my/results(?:/\d+)?|results/\d+/report|exams/\d+/leaderboard|question-concerns|student/questions/\d+/explain)$')
def protect(request,user):
    if user['role']!='STUDENT' or request.method!='GET' or not PATTERN.fullmatch(request.url.path) or getattr(request.state,'content_read_reserved',False):return
    from platform_api import db
    with closing(db()) as conn:
        conn.execute('BEGIN IMMEDIATE');conn.execute('UPDATE users SET id=id WHERE id=?',(user['id'],))
        now=time.time();conn.execute('DELETE FROM student_content_reads WHERE user_id=? AND read_at<=?',(user['id'],now-3600))
        rows=[r['read_at'] for r in conn.execute('SELECT read_at FROM student_content_reads WHERE user_id=? ORDER BY read_at',(user['id'],)).fetchall()]
        recent=[t for t in rows if t>now-60]
        retry=max(math.ceil(recent[0]+60-now) if len(recent)>=MINUTE_LIMIT else 0,math.ceil(rows[0]+3600-now) if len(rows)>=HOUR_LIMIT else 0)
        if retry:raise HTTPException(429,'Too many exam/report requests. Wait before reloading. Your answer saving and submission remain available.',headers={'Retry-After':str(max(1,retry))})
        conn.execute('INSERT INTO student_content_reads(user_id,read_at) VALUES(?,?)',(user['id'],now));conn.commit()
    request.state.content_read_reserved=True
