"""Bounded, released-result analytics. No learner identity is accepted from clients."""
import json
import time
from collections import defaultdict

RELEASED = "(e.result_release_mode='IMMEDIATE' OR (e.result_release_mode='AFTER_EXAM_CLOSE' AND e.status='CLOSED'))"


def benchmark(conn, user_id, exam_id, latest):
    result = {'scope':'EXAM','cohort_size':None,'sample_minimum_threshold':30,'calculation_timestamp':time.time(),'percentile':None,'message':'Benchmark will appear when enough comparable attempts are available.'}
    if not exam_id or not latest or not latest.get('exam_version_id'):
        return result
    # One most recent released attempt per learner, on the identical published version.
    cohort = conn.execute(f"""WITH comparable AS (
      SELECT s.percentage, ROW_NUMBER() OVER (PARTITION BY s.user_id ORDER BY s.submitted_at DESC,s.id DESC) position
      FROM exam_sessions s JOIN exams e ON e.id=s.exam_id
      WHERE s.exam_id=? AND s.exam_version_id=? AND s.status IN ('SUBMITTED','AUTO_SUBMITTED') AND {RELEASED})
      SELECT COUNT(*) n, SUM(CASE WHEN percentage<? THEN 1 ELSE 0 END) below,
      SUM(CASE WHEN percentage=? THEN 1 ELSE 0 END) tied FROM comparable WHERE position=1""",
      (exam_id,latest['exam_version_id'],latest['percentage'],latest['percentage'])).fetchone()
    result['cohort_size'] = cohort['n']
    if cohort['n'] >= result['sample_minimum_threshold']:
        result['percentile'] = round(100*(cohort['below']+0.5*cohort['tied'])/cohort['n'],1)
        result['message'] = f"Exam-version percentile: {result['percentile']} across {cohort['n']} learners. Latest released attempt per learner; ties use midpoint rank. This is not a national or state rank."
    return result


def performance(conn, user_id, exam_id=None, limit=10, days=365, subject='', difficulty='', qtype=''):
    clauses = ['s.user_id=?', "s.status IN ('SUBMITTED','AUTO_SUBMITTED')", RELEASED, 's.submitted_at>=?']
    params = [user_id, time.time() - days * 86400]
    if exam_id:
        clauses.append('s.exam_id=?'); params.append(exam_id)
    if subject:
        clauses.append('e.subject=?'); params.append(subject)
    rows = [dict(r) for r in conn.execute(f"SELECT s.*,e.name exam_name,e.subject,e.exam_type FROM exam_sessions s JOIN exams e ON e.id=s.exam_id WHERE {' AND '.join(clauses)} ORDER BY s.submitted_at DESC,s.id DESC LIMIT ?", (*params, limit)).fetchall()]
    answers = {}
    if rows:
        ids = [r['id'] for r in rows]
        answers = {(r['session_id'], r['question_id']): dict(r) for r in conn.execute(f"SELECT * FROM exam_answers WHERE session_id IN ({','.join('?' for _ in ids)})", ids).fetchall()}
    # Older exam snapshots omitted taxonomy. Resolve only this bounded batch in one query.
    qids = {q.get('id', q.get('question_id')) for row in rows for q in json.loads(row.get('question_set_json') or '[]')}
    metadata = {}
    if qids:
        metadata = {r['id']: dict(r) for r in conn.execute(f"SELECT id,subject,chapter,topic,difficulty,qtype FROM questions WHERE id IN ({','.join('?' for _ in qids)})", list(qids)).fetchall()}
    groups = {k: defaultdict(lambda: {'count': 0, 'correct': 0, 'unanswered': 0}) for k in ('topic', 'chapter', 'difficulty', 'qtype')}
    totals = dict(correct=0, incorrect=0, unanswered=0, lost_incorrect=0., lost_unanswered=0.)
    seconds = 0; question_count = 0
    for row in rows:
        snapshot = json.loads(row.get('question_set_json') or '[]')
        seconds += max(0, min(row['submitted_at'], row['expires_at']) - row['started_at'])
        question_count += len(snapshot)
        for stored in snapshot:
            q = {**metadata.get(stored.get('id', stored.get('question_id')), {}), **stored}
            if difficulty and q.get('difficulty') != difficulty: continue
            if qtype and q.get('qtype') != qtype: continue
            a = answers.get((row['id'], q.get('id', q.get('question_id'))), {})
            answered = bool(a.get('is_answered') or a.get('selected_answer'))
            correct = bool(a.get('is_correct'))
            outcome = 'correct' if correct else 'incorrect' if answered else 'unanswered'
            totals[outcome] += 1
            if not correct:
                totals['lost_' + outcome] += max(0, float(q.get('marks', 1)) - float(a.get('marks_awarded') or 0))
            for dimension in groups:
                # Keep identically named topics in different subjects/chapters separate.
                label = str(q.get(dimension) or 'Unspecified')
                key = (str(q.get('subject') or row['subject']), str(q.get('chapter') or ''), label) if dimension == 'topic' else ('', '', label)
                g = groups[dimension][key]; g['count'] += 1; g['correct'] += int(correct); g['unanswered'] += int(not answered)
    dimensions = {}
    for dim, values in groups.items():
        dimensions[dim] = [{'label': k[2], 'subject': k[0], 'chapter': k[1], **v, 'accuracy': round(100 * v['correct'] / (v['count']-v['unanswered']), 1) if v['count']>v['unanswered'] else None} for k,v in values.items()]
        dimensions[dim].sort(key=lambda x: (-x['count'], x['label']))
    eligible = [x for x in dimensions['topic'] if x['count']-x['unanswered'] >= 5 and x['label'] != 'Unspecified']
    gaps = [{**x, 'gap_score': round(1-x['accuracy']/100, 2), 'confidence': 'HIGH' if x['count']-x['unanswered']>=20 else 'MODERATE', 'reason_codes': ['LOW_ACCURACY']} for x in eligible if x['accuracy']<60]
    gaps.sort(key=lambda x: -x['gap_score'])
    strengths = [x for x in eligible if x['accuracy']>=80]
    available = [dict(r) for r in conn.execute("SELECT e.id,e.name,e.subject,e.level FROM exams e WHERE e.status='OPEN' AND (e.allow_self_registration=1 OR EXISTS (SELECT 1 FROM exam_enrollments er WHERE er.exam_id=e.id AND er.user_id=?)) AND (e.exam_end_at IS NULL OR e.exam_end_at>?) ORDER BY e.id DESC LIMIT 30", (user_id, time.time())).fetchall()]
    recommendations = []
    for gap in gaps[:5]:
        matches = [e for e in available if e['subject'] == gap['subject']][:3]
        recommendations.append({'title': 'Revise '+gap['label'], 'reason': f"{gap['accuracy']}% accuracy across {gap['count']-gap['unanswered']} answered questions.", 'action': 'Review foundations, then practice medium difficulty questions.', 'exams': matches})
    if not recommendations:
        recommendations = [{'title': 'Build your assessment baseline' if not eligible else 'Continue consistent practice', 'reason': 'At least five answered questions per topic are needed to identify a gap.' if not eligible else 'No established topic is below 60% accuracy.', 'action': 'Complete an available assessment and review your mistakes.', 'exams': available[:3]}]
    percentages = [float(r['percentage'] or 0) for r in reversed(rows)]
    attempted = totals['correct'] + totals['incorrect']; total = attempted + totals['unanswered']
    trend = [{k:r.get(k) for k in ('id','exam_id','exam_name','submitted_at','percentage','score','max_score','attempt_number')} for r in reversed(rows)]
    return {'data_period': f'Latest {limit} released attempts within {days} days', 'attempt_count':len(rows), 'average_score':round(sum(percentages)/len(percentages),1) if percentages else None, 'accuracy':round(100*totals['correct']/attempted,1) if attempted else None, 'completion_rate':round(100*attempted/total,1) if total else None, 'improvement':round(percentages[-1]-sum(percentages[:-1])/len(percentages[:-1]),1) if len(percentages)>1 else None, 'average_seconds_per_question':round(seconds/question_count,1) if question_count else None, 'time_note':'Elapsed assessment time divided by all questions; topic timing is not recorded.', **totals, 'dimensions':dimensions, 'strengths':strengths[:5], 'learning_gaps':gaps[:5], 'recommendations':recommendations, 'recent_attempts':trend, 'benchmark':benchmark(conn,user_id,exam_id,rows[0] if rows else None), 'readiness':{'score':None,'message':'More assessment evidence and syllabus coverage are needed to calculate readiness.'}}
