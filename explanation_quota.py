"""Database-backed rolling quota, shared across workers and login sessions."""
from contextlib import closing
import math
import time
from fastapi import HTTPException

SCHEMA = """
CREATE TABLE IF NOT EXISTS student_explanation_calls (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL REFERENCES users(id),
 called_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_student_explanation_calls ON student_explanation_calls(user_id,called_at);
"""
LIMIT = 10
WINDOW_SECONDS = 3600


def reserve_explanation_call(user_id):
    from platform_api import db
    with closing(db()) as conn:
        conn.execute('BEGIN IMMEDIATE')
        # PostgreSQL locks this user's row; SQLite serializes writers. Reserve
        # before calling the provider so parallel requests cannot overspend.
        conn.execute('UPDATE users SET id=id WHERE id=?',(user_id,))
        now=time.time()
        conn.execute('DELETE FROM student_explanation_calls WHERE user_id=? AND called_at<=?',(user_id,now-WINDOW_SECONDS))
        rows=conn.execute('SELECT called_at FROM student_explanation_calls WHERE user_id=? ORDER BY called_at',(user_id,)).fetchall()
        if len(rows)>=LIMIT:
            retry=max(1,math.ceil(rows[0]['called_at']+WINDOW_SECONDS-now))
            raise HTTPException(429,f'You have reached the limit of 10 AI explanations per hour. Try again in {math.ceil(retry/60)} minute(s).',headers={'Retry-After':str(retry)})
        conn.execute('INSERT INTO student_explanation_calls(user_id,called_at) VALUES(?,?)',(user_id,now))
        conn.commit()
