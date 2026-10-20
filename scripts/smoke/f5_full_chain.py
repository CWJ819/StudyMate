# F5 §7 手工清单的自动化主干：全新课程从零走完
# 上传 → 建框架 → 出题 → 提交 → 掌握度 → 复习目标 → 计划
import json
import time
import urllib.request
import uuid
from datetime import date, timedelta
from pathlib import Path

BASE = 'http://127.0.0.1:8000/api'
FIXTURE = Path(__file__).resolve().parents[2] / 'tests' / 'fixtures' / 'f1-sample.pdf'


def call(method, path, body=None, raw=None, headers=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={'Content-Type': 'application/json', **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            r = resp.read()
            return resp.status, json.loads(r) if r else None
    except urllib.error.HTTPError as e:
        r = e.read()
        return e.code, json.loads(r) if r else None


def wait_job(job_id, timeout=90):
    for _ in range(timeout):
        s, job = call('GET', f'/jobs/{job_id}')
        if s == 200 and job['status'] in ('succeeded', 'failed', 'cancelled'):
            return job
        time.sleep(1)
    raise TimeoutError(f'job {job_id}')


# 1. 课程
s, course = call('POST', '/courses', {'name': f'F5全链路 {date.today().isoformat()}', 'description': '§7 冒烟'})
print('course:', s, course['id'])
assert s == 201

# 2. 上传（multipart，手搓 boundary）
boundary = uuid.uuid4().hex
pdf = FIXTURE.read_bytes()
parts = (
    f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="f1-sample.pdf"\r\n'
    f'Content-Type: application/pdf\r\n\r\n'
).encode() + pdf + f'\r\n--{boundary}--\r\n'.encode()
s, up = call('POST', f"/courses/{course['id']}/materials", raw=parts,
             headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
print('upload:', s, up['document_id'], up['status'])
assert s == 201
doc_job = wait_job(up['job_id'])
print('  parse job:', doc_job['status'])
assert doc_job['status'] == 'succeeded'

# 3. 知识框架
s, kb = call('POST', f"/courses/{course['id']}/knowledge/build", {})
print('knowledge build:', s)
assert s == 202
kjob = wait_job(kb['job_id'])
print('  build job:', kjob['status'])
assert kjob['status'] == 'succeeded'
s, fw = call('GET', f"/courses/{course['id']}/knowledge")
print('  framework:', fw['status'], 'v%s' % fw['version_number'], 'nodes=%d' % len(fw['nodes']))
assert fw['status'] == 'active'

# 4. 出题（3 题混合）
s, qz = call('POST', f"/courses/{course['id']}/quiz/generate", {
    'question_count': 3,
    'question_types': ['single_choice', 'multiple_choice', 'short_answer'],
})
print('quiz generate:', s, qz['quiz_id'])
assert s == 202
wait_job(qz['job_id'])
s, quiz = call('GET', f"/quizzes/{qz['quiz_id']}")
print('  quiz:', quiz['status'], 'questions=%d' % len(quiz['questions']))
assert quiz['status'] == 'open'

# 5. 幂等提交（固定 key；答案确定性填法）
key = uuid.uuid4().hex
def submit_body():
    return {'idempotency_key': key, 'answers': [
        {'question_id': q['question_id'],
         'selected_option_ids': (
             [q['options'][0]['id']] if q['question_type'] == 'single_choice'
             else [o['id'] for o in q['options']] if q['question_type'] == 'multiple_choice'
             else []
         ),
         'text': '慢启动阶段拥塞窗口指数增长' if q['question_type'] == 'short_answer' else ''}
        for q in quiz['questions']
    ]}
s, sub1 = call('POST', f"/quizzes/{quiz['quiz_id']}/submit", submit_body())
print('submit:', s, json.dumps(sub1, ensure_ascii=False)[:200] if s != 200 else 'score %s/%s' % (sub1['total_score'], sub1['max_score']))
assert s == 200
s, sub2 = call('POST', f"/quizzes/{quiz['quiz_id']}/submit", submit_body())
same = sub1['submission_id'] == sub2['submission_id']
print('idempotent replay identical:', same)
assert same

# 6. 掌握度 + 错题本 + 复习目标
s, mastery = call('GET', f"/courses/{course['id']}/mastery")
print('mastery:', s, [(m['title'][:12], m['mastery_estimate'], m['evidence_count']) for m in mastery])
assert s == 200 and len(mastery) > 0
s, wrong = call('GET', f"/courses/{course['id']}/wrongbook")
print('wrongbook:', s, len(wrong), '条')
assert s == 200
s, targets = call('POST', f"/courses/{course['id']}/review-targets", {'limit': 3})
print('review-targets:', s, [t['knowledge_node_id'][:8] for t in targets['targets']])
assert s == 200 and len(targets['targets']) > 0

# 7. 计划（today+7，每日 45 分钟）
s, plan = call('POST', f"/courses/{course['id']}/plan", {
    'exam_date': (date.today() + timedelta(days=7)).isoformat(),
    'daily_minutes': 45, 'target_score': 80,
})
per_day = {}
for t in plan['tasks']:
    per_day[t['scheduled_date']] = per_day.get(t['scheduled_date'], 0) + t['estimated_minutes']
print('plan:', s, 'v%s' % plan['version_number'], 'tasks=%d' % len(plan['tasks']), per_day)
assert s == 201 and all(v <= 45 for v in per_day.values())

# 8. 清理演示课程（保持库里整洁；留日志即可）
s, _ = call('DELETE', f"/courses/{course['id']}")
print('cleanup course:', s)
print('\nALL F5 CHAIN SMOKE PASSED')
