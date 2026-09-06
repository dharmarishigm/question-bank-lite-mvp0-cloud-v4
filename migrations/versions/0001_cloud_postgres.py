"""Create the complete question bank and examination schema on PostgreSQL."""
from pathlib import Path
import ast
from alembic import op
from sqlalchemy import text
from database import translate_ddl

revision='0001_cloud_postgres'
down_revision=None
branch_labels=None
depends_on=None

ROOT=Path(__file__).resolve().parents[2]

def constants(filename,names):
    tree=ast.parse((ROOT/filename).read_text())
    values={}
    for node in tree.body:
        if isinstance(node,(ast.Assign,ast.AnnAssign)):
            targets=node.targets if isinstance(node,ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target,ast.Name) and target.id in names:values[target.id]=ast.literal_eval(node.value)
    return values

def upgrade():
    bind=op.get_bind()
    sources=[('app.py',{'SCHEMA'}),('platform_api.py',{'SCHEMA'}),('exam_conduct.py',{'SCHEMA'})]
    for filename,names in sources:
        for schema in constants(filename,names).values():
            for statement in translate_ddl(schema).split(';'):
                if statement.strip():bind.execute(text(statement))
    maps={}
    maps.update(constants('app.py',{'QUESTION_MIGRATIONS','EXAM_REGISTRATION_MIGRATIONS','AI_RUN_MIGRATIONS'}))
    maps.update(constants('exam_conduct.py',{'EXAM_COLUMNS','USER_COLUMNS','ENROLL_COLUMNS','PENDING_COLUMNS','SESSION_COLUMNS','ANSWER_COLUMNS'}))
    table_maps={
      'questions':maps['QUESTION_MIGRATIONS'],'exam_registrations':maps['EXAM_REGISTRATION_MIGRATIONS'],'ai_generation_runs':maps['AI_RUN_MIGRATIONS'],
      'exams':maps['EXAM_COLUMNS'],'users':maps['USER_COLUMNS'],'exam_enrollments':maps['ENROLL_COLUMNS'],'pending_exam_registrations':maps['PENDING_COLUMNS'],'exam_sessions':maps['SESSION_COLUMNS'],'exam_answers':maps['ANSWER_COLUMNS']}
    for table,columns in table_maps.items():
        existing={row[0] for row in bind.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=:table"),{'table':table})}
        for name,ddl in columns.items():
            if name not in existing:bind.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {translate_ddl(ddl)}'))

def downgrade():
    raise RuntimeError('Cloud v4 protects production data; restore a backup instead of downgrading the initial schema.')
