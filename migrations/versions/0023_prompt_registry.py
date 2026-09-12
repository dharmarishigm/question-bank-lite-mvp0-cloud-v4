"""Add the immutable Administrator prompt registry."""
from alembic import op
from database import translate_ddl
from prompt_registry import SCHEMA, SEEDS, content_hash
import time

revision='0023_prompt_registry'
down_revision='0022_security_sessions'
branch_labels=None
depends_on=None

def upgrade():
    for statement in SCHEMA.split(';'):
        if statement.strip():op.execute(translate_ddl(statement))
    bind=op.get_bind();now=time.time()
    for key,(name,description,content) in SEEDS.items():
        row=bind.exec_driver_sql('SELECT id FROM prompt_definitions WHERE prompt_key=%s' if bind.dialect.name=='postgresql' else 'SELECT id FROM prompt_definitions WHERE prompt_key=?',(key,)).fetchone()
        if row:continue
        if bind.dialect.name=='postgresql':
            did=bind.exec_driver_sql("INSERT INTO prompt_definitions(prompt_key,name,description,scope_type,created_at) VALUES(%s,%s,%s,'BOTH',%s) RETURNING id",(key,name,description,now)).scalar_one()
            bind.exec_driver_sql("INSERT INTO prompt_versions(prompt_definition_id,scope_id,version_number,status,system_content,change_note,content_hash,created_at,activated_at) VALUES(%s,0,1,'ACTIVE',%s,'Bootstrap from verified production prompt',%s,%s,%s)",(did,content,content_hash(content),now,now))
        else:
            result=bind.exec_driver_sql("INSERT INTO prompt_definitions(prompt_key,name,description,scope_type,created_at) VALUES(?,?,?,'BOTH',?)",(key,name,description,now));did=result.lastrowid
            bind.exec_driver_sql("INSERT INTO prompt_versions(prompt_definition_id,scope_id,version_number,status,system_content,change_note,content_hash,created_at,activated_at) VALUES(?,0,1,'ACTIVE',?,'Bootstrap from verified production prompt',?,?,?)",(did,content,content_hash(content),now,now))

def downgrade():
    raise RuntimeError('Prompt provenance is immutable; use an application rollback.')
