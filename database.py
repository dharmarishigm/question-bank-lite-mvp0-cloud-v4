"""Database adapter supporting local SQLite and Cloud SQL PostgreSQL."""
from __future__ import annotations

import os
import re
import sqlite3
import threading
from collections.abc import Iterator, Mapping


class Row(Mapping):
    def __init__(self, values):
        self._data = dict(values)
        self._keys = list(self._data)

    def __getitem__(self, key):
        return self._data[self._keys[key]] if isinstance(key, int) else self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def keys(self):
        return self._data.keys()


def _qmark(sql: str) -> str:
    out = []
    quoted = False
    index = 0
    while index < len(sql):
        char = sql[index]
        if char == "'" and quoted and index + 1 < len(sql) and sql[index + 1] == "'":
            out.extend((char, char))
            index += 2
            continue
        if char == "'":
            quoted = not quoted
        if char == '?' and not quoted:
            out.append('%s')
        elif char == '%':
            out.append('%%')
        else:
            out.append(char)
        index += 1
    return ''.join(out)


def translate_sql(sql: str) -> str:
    statement=sql.strip()
    statement=re.sub(r'\s+COLLATE\s+NOCASE', '', statement, flags=re.I)
    statement=re.sub(r'^BEGIN\s+IMMEDIATE$', 'BEGIN', statement, flags=re.I)
    ignored=bool(re.match(r'^INSERT\s+OR\s+IGNORE\s+INTO',statement,re.I))
    statement=re.sub(r'^INSERT\s+OR\s+IGNORE\s+INTO','INSERT INTO',statement,flags=re.I)
    if ignored and ' ON CONFLICT ' not in statement.upper():statement+=' ON CONFLICT DO NOTHING'
    return _qmark(statement)


def translate_ddl(sql: str) -> str:
    sql=re.sub(r'INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT','BIGSERIAL PRIMARY KEY',sql,flags=re.I)
    sql=re.sub(r'\bREAL\b','DOUBLE PRECISION',sql,flags=re.I)
    sql=re.sub(r'\s+COLLATE\s+NOCASE','',sql,flags=re.I)
    return sql


class PostgresCursor:
    def __init__(self,cursor,lastrowid=None):self._cursor=cursor;self.lastrowid=lastrowid
    @property
    def rowcount(self):return self._cursor.rowcount
    def fetchone(self):
        value=self._cursor.fetchone();return Row(value) if value is not None else None
    def fetchall(self):return [Row(value) for value in self._cursor.fetchall()]
    def __iter__(self):return iter(self.fetchall())


class PostgresConnection:
    def __init__(self,connection):self._connection=connection
    def execute(self,sql,params=()):
        pragma=re.match(r'\s*PRAGMA\s+table_info\(([^)]+)\)',sql,re.I)
        if pragma:
            cur=self._connection.execute("SELECT column_name AS name,data_type AS type FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",(pragma.group(1),));return PostgresCursor(cur)
        table_check = re.match(
            r"\s*SELECT\s+1\s+FROM\s+sqlite_master\s+WHERE\s+type='table'\s+AND\s+name=(\?|\'([^']+)\')",
            sql,
            re.I,
        )
        if table_check:
            table_name = params[0] if table_check.group(1) == '?' else table_check.group(2)
            cur = self._connection.execute(
                "SELECT 1 AS present FROM information_schema.tables WHERE table_schema='public' AND table_name=%s",
                (table_name,),
            )
            return PostgresCursor(cur)
        statement=translate_sql(sql)
        insert = re.match(r'^INSERT\s+(?:INTO\s+)?["`]?([A-Za-z_][A-Za-z0-9_]*)', statement, re.I)
        table = insert.group(1).lower() if insert else ''
        returning = bool(insert) and table not in {'oauth_states', 'engagement_limits', 'flag_trials'} and ' RETURNING ' not in statement.upper()
        if returning:
            statement = statement.rstrip().rstrip(';') + ' RETURNING id'
        cur=self._connection.execute(statement,params)
        last=None
        if returning:
            row=cur.fetchone();last=(row or {}).get('id')
        return PostgresCursor(cur,last)
    def executescript(self,script):
        for statement in translate_ddl(script).split(';'):
            if statement.strip():self._connection.execute(statement)
    def commit(self):self._connection.commit()
    def rollback(self):self._connection.rollback()
    def close(self):self._connection.close()
    def __enter__(self):return self
    def __exit__(self,kind,value,traceback):
        if kind:self.rollback()
        else:self.commit()
        self.close()


_engines={}
_engine_lock=threading.Lock()

def connect(sqlite_path: str):
    url=os.getenv('DATABASE_URL','').strip()
    if not url:
        connection=sqlite3.connect(sqlite_path);connection.row_factory=sqlite3.Row;connection.execute('PRAGMA foreign_keys = ON');return connection
    import psycopg
    from psycopg.rows import dict_row
    if os.getenv('DB_POOL_ENABLED')=='1':
        from sqlalchemy import create_engine
        key=(os.getpid(),url)
        with _engine_lock:
            if key not in _engines:
                sqlalchemy_url=url.replace('postgresql://','postgresql+psycopg://',1)
                _engines[key]=create_engine(sqlalchemy_url,
                    pool_size=int(os.getenv('DB_POOL_SIZE','5')),max_overflow=0,
                    pool_timeout=5,pool_recycle=300,pool_pre_ping=True,
                    connect_args={'connect_timeout':5,
                      'options':'-c statement_timeout=30000 -c lock_timeout=5000 -c idle_in_transaction_session_timeout=60000'})
            engine=_engines[key]
        connection=engine.raw_connection()
        connection.driver_connection.row_factory=dict_row
        return PostgresConnection(connection)
    if url.startswith('postgresql+psycopg://'):url='postgresql://'+url.split('://',1)[1]
    return PostgresConnection(psycopg.connect(url,row_factory=dict_row))
