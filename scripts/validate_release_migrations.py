"""Run inside the release image against a disposable Cloud Build PostgreSQL DB."""
import os
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

url = os.environ['DATABASE_URL']
assert '@qb-migration-db:5432/qb_migration_test' in url, 'Disposable database required'
config = Config('alembic.ini')
engine = create_engine(url)
command.upgrade(config, '0018_grand_tests')
# Simulate a deployed 0018 installation whose library lacks the new columns.
with engine.begin() as conn:
    for table in ('program_document_audit', 'grand_test_page_status_audit', 'grand_test_page_status'):
        conn.execute(text(f'DROP TABLE IF EXISTS {table}'))
    for column in ('subject','chapter','available_for_digitisation','availability_changed_at','availability_changed_by','updated_at','updated_by'):
        conn.execute(text(f'ALTER TABLE program_documents DROP COLUMN IF EXISTS {column}'))
# Verify additive security expansion preserves the legacy rollback marker.
command.upgrade(config, '0020_dqb_document_controls')
from security_boundary import SCHEMA as QUOTAS
from security_mfa import SCHEMA as MFA
from database import translate_ddl
with engine.begin() as conn:
    for ddl in (QUOTAS+';'+MFA).split(';'):
        if ddl.strip():conn.execute(text(translate_ddl(ddl)))
    assert conn.execute(text('SELECT version_num FROM alembic_version')).scalar()=='0020_dqb_document_controls'
print('Security schema expansion preserves legacy Alembic marker')
command.upgrade(config, 'head')
command.upgrade(config, 'head')
with engine.connect() as conn:
    assert conn.execute(text('SELECT version_num FROM alembic_version')).scalar() == '0025_explanation_jobs'
    assert 'explanation_jobs' in inspect(conn).get_table_names()
    for table in ('program_document_audit','grand_test_page_status','grand_test_page_status_audit'):
        columns = {c['name']: c for c in inspect(conn).get_columns(table)}
        assert 'nextval' in columns['id']['default'], (table, columns['id'])
    assert 'available_for_digitisation' in {c['name'] for c in inspect(conn).get_columns('program_documents')}
print('PostgreSQL upgrade from legacy 0018 and repeated upgrade passed')
from security_boundary import reserve
from fastapi import HTTPException
reserve('cloud-build-disposable','validation',1,now=120)
try:
    reserve('cloud-build-disposable','validation',1,now=120)
except HTTPException as exc:
    assert exc.status_code==429
else:
    raise AssertionError('PostgreSQL security quota did not reject excess request')
reserve('cloud-build-disposable','validation',1,now=180)
print('PostgreSQL security quota increment, rejection and reset passed')

os.environ["DB_POOL_ENABLED"]="1"
from database import connect
for _ in range(8):
    c=connect("")
    assert c.execute("SELECT 1 AS n").fetchone()["n"]==1
    c.close()
print("Bounded PostgreSQL pool checkout/reuse passed")

# Exercise the actual queue/cache SQL against PostgreSQL, not only SQLite tests.
import app
from explanation_jobs import enqueue,claim_one,process,BilingualExplanation
from unittest.mock import patch
question=app.create_question(app.Question(statement='Disposable queue validation',answer='2',solution='One plus one is two.',source_type='AI_GENERATED'))
with app.connect() as conn:
    enqueue(conn,question['id']);conn.commit()
item=claim_one()
assert item and claim_one() is None
with patch('explanation_jobs.generate_bilingual',return_value=BilingualExplanation(explanation_en='One plus one is two.',explanation_te='ఒకటి మరియు ఒకటి కలిపితే రెండు.')):
    assert process(item)=='SUCCEEDED'
assert app.get_cached_question_explanation(question['id'],'en')['liked']
assert app.get_cached_question_explanation(question['id'],'te')['liked']
print('PostgreSQL queue claim, bilingual cache transaction and completion passed')

# Exercise the actual deletion route with PostgreSQL foreign keys and pooling.
# Authentication is patched only here, after the disposable-database guard above.
import json
import time
from starlette.requests import Request
from platform_api import delete_exam
from exam_conduct import publish_version

now=time.time()
source_id='disposable-exam-delete-source'
with app.connect() as conn:
    uid=conn.execute("INSERT INTO users(google_sub,email,display_name,role,status,created_at,updated_at,last_login_at) VALUES(?,?,?,'ADMIN','ACTIVE',?,?,?)",
                     ('disposable-exam-delete-admin','exam-delete@example.test','Disposable validation',now,now,now)).lastrowid
    pid=conn.execute("INSERT INTO programs(code,name,payload_json,status,created_by,updated_by,created_at,updated_at) VALUES(?,?,'{}','ACTIVE',?,?,?,?)",
                     ('DISPOSABLE_EXAM_DELETE','Disposable deletion program',uid,uid,now,now)).lastrowid
    conn.execute('INSERT INTO source_documents(id,filename,sha256,mime_type,page_count,local_path,created_at) VALUES(?,?,?,?,?,?,?)',
                 (source_id,'disposable-source.pdf','disposable-exam-delete-sha','application/pdf',1,'/disposable/source.pdf',now))
    document_id=conn.execute('INSERT INTO program_documents(program_id,source_document_id,original_filename,created_by,created_at) VALUES(?,?,?,?,?)',
                             (pid,source_id,'disposable-source.pdf',uid,now)).lastrowid
    conn.commit()

source_json=json.dumps({'source_document_id':source_id,'document_id':document_id})
questions_json=json.dumps([{'question_id':question['id'],'statement':question['statement'],'saved_question_id':question['id']}])
input_json=json.dumps({'settings':{'name':'Disposable guided paper','curriculum':'Preserve frozen syllabus','sections':[]}})
paper_result={'questions':[{'question':question,'origin':'AI'}],'draft_hash':'disposable-stale-draft-hash'}


def linked_exam(suffix):
    with app.connect() as conn:
        eid=conn.execute("INSERT INTO exams(name,status,created_by,created_at,updated_at) VALUES(?,'PUBLISHED',?,?,?)",
                         ('Disposable deletion '+suffix,uid,now,now)).lastrowid
        conn.execute('INSERT INTO exam_questions(exam_id,question_id,display_order,created_at) VALUES(?,?,1,?)',(eid,question['id'],now))
        version_id=publish_version(conn,eid,uid)
        workspace_id=conn.execute("INSERT INTO grand_tests(program_id,name,status,source_json,questions_json,exam_id,created_by,updated_by,created_at,updated_at) VALUES(?,?,'PUBLISHED',?,?,?,?,?,?,?)",
                                  (pid,'Disposable source workspace '+suffix,source_json,questions_json,eid,uid,uid,now,now)).lastrowid
        conn.execute("INSERT INTO grand_test_page_status(workspace_id,source_document_id,page_number,status,created_at,updated_at,created_by,updated_by) VALUES(?,?,1,'Completed',?,?,?,?)",
                     (workspace_id,source_id,now,now,uid,uid))
        job_id=conn.execute("INSERT INTO program_exam_jobs(program_id,request_key,status,input_json,result_json,exam_id,created_by,created_at,updated_at) VALUES(?,?,'PUBLISHED',?,?,?,?,?,?)",
                            (pid,'disposable-delete-'+suffix,input_json,json.dumps(paper_result),eid,uid,now,now)).lastrowid
        conn.commit()
    return eid,workspace_id,job_id,version_id


def source_state():
    with app.connect() as conn:
        return {
            'source':dict(conn.execute('SELECT * FROM source_documents WHERE id=?',(source_id,)).fetchone()),
            'library':dict(conn.execute('SELECT * FROM program_documents WHERE id=?',(document_id,)).fetchone()),
            'question':dict(conn.execute('SELECT * FROM questions WHERE id=?',(question['id'],)).fetchone()),
            'cache':[dict(row) for row in conn.execute('SELECT * FROM question_explanation_translations WHERE question_id=? ORDER BY language',(question['id'],)).fetchall()],
        }


def linked_state(ids):
    eid,workspace_id,job_id,version_id=ids
    with app.connect() as conn:
        return {
            'exam':dict(conn.execute('SELECT * FROM exams WHERE id=?',(eid,)).fetchone()),
            'workspace':dict(conn.execute('SELECT * FROM grand_tests WHERE id=?',(workspace_id,)).fetchone()),
            'job':dict(conn.execute('SELECT * FROM program_exam_jobs WHERE id=?',(job_id,)).fetchone()),
            'version':dict(conn.execute('SELECT * FROM exam_versions WHERE id=?',(version_id,)).fetchone()),
            'page':dict(conn.execute('SELECT * FROM grand_test_page_status WHERE workspace_id=?',(workspace_id,)).fetchone()),
            'questions':[dict(row) for row in conn.execute('SELECT * FROM exam_questions WHERE exam_id=?',(eid,)).fetchall()],
        }


def call_delete(eid):
    request=Request({'type':'http','method':'DELETE','path':f'/api/admin/exams/{eid}','headers':[]})
    with patch('platform_api._auth',return_value={'id':uid,'role':'ADMIN','status':'ACTIVE'}):
        return delete_exam(eid,request)


unused=linked_exam('unused')
eid,workspace_id,job_id,version_id=unused
before=linked_state(unused)
preserved_source=source_state()
assert {row['language'] for row in preserved_source['cache']}=={'en','te'}
assert call_delete(eid)=={'deleted':eid}
with app.connect() as conn:
    assert conn.execute('SELECT 1 FROM exams WHERE id=?',(eid,)).fetchone() is None
    assert conn.execute('SELECT 1 FROM exam_questions WHERE exam_id=?',(eid,)).fetchone() is None
    assert conn.execute('SELECT 1 FROM exam_versions WHERE id=?',(version_id,)).fetchone() is None
    workspace=dict(conn.execute('SELECT * FROM grand_tests WHERE id=?',(workspace_id,)).fetchone())
    assert workspace['exam_id'] is None and workspace['status']=='REVIEW_REQUIRED'
    assert workspace['source_json']==source_json and workspace['questions_json']==questions_json
    assert workspace['revision']==before['workspace']['revision']+1
    assert dict(conn.execute('SELECT * FROM grand_test_page_status WHERE workspace_id=?',(workspace_id,)).fetchone())==before['page']
    job=dict(conn.execute('SELECT * FROM program_exam_jobs WHERE id=?',(job_id,)).fetchone())
    assert job['exam_id'] is None and job['status']=='REVIEW_REQUIRED' and job['input_json']==input_json
    result=json.loads(job['result_json'])
    assert result['questions']==paper_result['questions'] and 'draft_hash' not in result
    assert conn.execute("SELECT 1 FROM exam_audit_log WHERE exam_id=? AND event_type='EXAM_DELETED'",(eid,)).fetchone()
assert source_state()==preserved_source
print('PostgreSQL linked exam deletion detaches workspaces and preserves source, questions and bilingual cache')

for history_kind in ('registration','pending','attempt','concern','external_reference'):
    ids=linked_exam(history_kind)
    eid=ids[0]
    with app.connect() as conn:
        if history_kind=='external_reference':
            conn.execute('CREATE TABLE disposable_exam_reference(id INTEGER PRIMARY KEY,exam_id INTEGER REFERENCES exams(id))')
            conn.execute('INSERT INTO disposable_exam_reference(id,exam_id) VALUES(1,?)',(eid,))
        elif history_kind=='concern':
            conn.execute("INSERT INTO question_concerns(question_id,exam_id,reporter_id,category,description,created_at,updated_at) VALUES(?,?,?,'ANSWER','Preserve concern',?,?)",
                         (question['id'],eid,uid,now,now))
        elif history_kind=='pending':
            conn.execute('INSERT INTO pending_exam_registrations(exam_id,registered_email,created_by,created_at,updated_at) VALUES(?,?,?,?,?)',
                         (eid,'pending@example.test',uid,now,now))
        else:
            registration_id=conn.execute('INSERT INTO exam_enrollments(exam_id,user_id,registered_at,created_at,updated_at) VALUES(?,?,?,?,?)',
                                         (eid,uid,now,now,now)).lastrowid
            if history_kind=='attempt':
                conn.execute("INSERT INTO exam_sessions(exam_id,user_id,registration_id,attempt_number,status,started_at,expires_at,duration_minutes,created_at,updated_at) VALUES(?,?,?,1,'SUBMITTED',?,?,30,?,?)",
                             (eid,uid,registration_id,now,now+1800,now,now))
        conn.commit()
    before=linked_state(ids)
    try:
        call_delete(eid)
    except HTTPException as exc:
        assert exc.status_code==409,(history_kind,exc.status_code)
    else:
        raise AssertionError('Exam with '+history_kind+' history was deleted')
    assert linked_state(ids)==before,history_kind
    assert source_state()==preserved_source,history_kind
print('PostgreSQL exam history 409 preserves exam, versions, workspaces and bilingual cache atomically')
