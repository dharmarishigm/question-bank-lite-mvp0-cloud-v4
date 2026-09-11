"""Bounded staging-only 1000-student exam test; credentials stay in process memory."""
import asyncio, collections, hashlib, json, os, secrets, time
from contextlib import closing
import httpx, ssl
TLS=ssl.create_default_context()
import scripts.check_staging_runtime  # verifies actual DB identity and restrictions
from platform_api import db
from exam_conduct import publish_version

BASE='https://qb-security-staging-272638587559.asia-south1.run.app'
assert os.environ['CLOUD_RUN_JOB']=='qb-security-staging-load1000'
RUN='load1000-'+str(int(time.time()))
users=[]; timings=collections.defaultdict(list); statuses=collections.Counter(); failures=[]
stop=asyncio.Event(); active=0; peak=0; completed=0
with closing(db()) as conn:
    now=time.time()
    owner=conn.execute("SELECT id FROM users WHERE email='security-admin@example.test' AND role='ADMIN'").fetchone()['id']
    exam=conn.execute("INSERT INTO exams(name,description,duration_minutes,total_marks,status,allow_self_registration,created_by,created_at,updated_at) VALUES(?,?,10,20,'OPEN',0,?,?,?)",(RUN,'Synthetic capacity test only',owner,now,now)).lastrowid
    for i in range(20):
        qid=conn.execute("INSERT INTO questions(statement,options,answer,subject,created_at,updated_at) VALUES(?,?,?,?,?,?)",(f'{RUN}: What is {i}+1?',json.dumps([str(i+1),'Other']),'A','Synthetic',now,now)).lastrowid
        conn.execute('INSERT INTO exam_questions(exam_id,question_id,display_order,marks,created_at) VALUES(?,?,?,1,?)',(exam,qid,i+1,now))
    publish_version(conn,exam,owner)
    for i in range(1000):
        email=f'{RUN}-{i}@example.test'
        uid=conn.execute("INSERT INTO users(google_sub,email,email_verified,display_name,role,status,created_at,updated_at,last_login_at) VALUES(?,?,1,?,'STUDENT','ACTIVE',?,?,?)",(email,email,RUN,now,now,now)).lastrowid
        conn.execute('INSERT INTO exam_enrollments(exam_id,user_id,registered_at,created_at,updated_at) VALUES(?,?,?,?,?)',(exam,uid,now,now,now))
        token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(24);digest=hashlib.sha256(token.encode()).hexdigest()
        conn.execute('INSERT INTO app_sessions(token_hash,user_id,csrf_token,expires_at,created_at) VALUES(?,?,?,?,?)',(digest,uid,csrf,now+1200,now))
        users.append({'id':uid,'token':token,'csrf':csrf,'hash':digest})
    conn.commit()
print(json.dumps({'event':'seeded','run':RUN,'exam_id':exam,'students':1000,'duration_minutes':10}),flush=True)

async def call(client,kind,method,path,body=None):
    started=time.perf_counter()
    try:
        r=await client.request(method,BASE+path,json=body)
        timings[kind].append((time.perf_counter()-started)*1000);statuses[str(r.status_code)]+=1
        if r.status_code!=200:raise RuntimeError(f'{kind}: HTTP {r.status_code}; '+r.text[:150])
        return r.json()
    except Exception as e:
        failures.append(str(e)[:100])
        if len(failures)>=5:stop.set()
        raise

async def student(i,user):
    global active,peak,completed
    try:await asyncio.wait_for(stop.wait(),timeout=i*.12)
    except asyncio.TimeoutError:pass
    if stop.is_set():return
    headers={'Cookie':'qb_session='+user['token']+'; qb_csrf='+user['csrf'],'X-CSRF-Token':user['csrf'],'Origin':BASE}
    async with httpx.AsyncClient(headers=headers,timeout=15,follow_redirects=False,verify=TLS,limits=httpx.Limits(max_connections=2,max_keepalive_connections=1)) as c:
        counted=False
        try:
            result=await call(c,'start','POST',f'/api/exams/{exam}/sessions',{})
            sid=result['session_id'];active+=1;counted=True;peak=max(peak,active);started=time.monotonic()
            data=await call(c,'read','GET',f'/api/sessions/{sid}')
            assert len(data['questions'])==20
            for index,q in enumerate(data['questions']):
                if stop.is_set():return
                await call(c,'save','PUT',f"/api/sessions/{sid}/answers/{q['id']}",{'selected_answer':'A'})
                delay=started+(index+1)*29-time.monotonic()
                if delay>0:
                    try:await asyncio.wait_for(stop.wait(),timeout=delay)
                    except asyncio.TimeoutError:pass
                if stop.is_set():return
                await call(c,'read','GET',f'/api/sessions/{sid}')
            # Submit near the end of the ten-minute exam, before server expiry.
            delay=started+590-time.monotonic()
            if delay>0:await asyncio.sleep(delay)
            if stop.is_set():return
            await call(c,'submit','POST',f'/api/sessions/{sid}/submit',{})
            completed+=1
        except Exception as e:
            print(json.dumps({'event':'student_failed','index':i,'reason':str(e)[:100]}),flush=True)
            stop.set()
        finally:
            if counted:active-=1

async def monitor(tasks):
    while not all(t.done() for t in tasks):
        await asyncio.sleep(30)
        print(json.dumps({'event':'progress','active':active,'peak':peak,'completed':completed,'requests':sum(statuses.values()),'errors':len(failures)}),flush=True)

async def main():
    tasks=[asyncio.create_task(student(i,u)) for i,u in enumerate(users)]
    await asyncio.gather(*tasks,monitor(tasks))

try:
    asyncio.run(main())
finally:
    with closing(db()) as conn:
        scored=conn.execute("SELECT COUNT(*) n FROM exam_sessions WHERE exam_id=? AND status='SUBMITTED' AND score=20 AND correct_count=20",(exam,)).fetchone()['n']
        persisted_answers=conn.execute('SELECT COUNT(*) n FROM exam_answers a JOIN exam_sessions s ON s.id=a.session_id WHERE s.exam_id=? AND a.is_answered=1',(exam,)).fetchone()['n']
        for u in users:
            conn.execute('DELETE FROM security_session_state WHERE token_hash=?',(u['hash'],))
            conn.execute('DELETE FROM app_sessions WHERE token_hash=?',(u['hash'],))
            conn.execute("UPDATE users SET status='DISABLED' WHERE id=?",(u['id'],))
        conn.execute("UPDATE exams SET status='CLOSED',updated_at=? WHERE id=?",(time.time(),exam));conn.commit()
    def percentile(values,p):return round(sorted(values)[min(len(values)-1,int(len(values)*p))],1) if values else None
    report={'event':'summary','run':RUN,'exam_id':exam,'peak_active':peak,'completed':completed,'correctly_scored':scored,'persisted_answers':persisted_answers,'status_counts':dict(statuses),'errors':failures,'latency_ms':{k:{'count':len(v),'p95':percentile(v,.95),'p99':percentile(v,.99),'max':round(max(v),1)} for k,v in timings.items()},'synthetic_sessions_revoked':True,'passed':completed==1000 and scored==1000 and persisted_answers==20000 and not failures}
    print(json.dumps(report),flush=True)
    if not report['passed']:raise SystemExit(1)
