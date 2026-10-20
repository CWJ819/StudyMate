# P0 修复真实验证（8001 临时后端 + 真实 DeepSeek）：
# 1) 三种题型混合出题（此前必失败：短答 rubric schema）
# 2) 提交含简答的测验（此前 502：批改字段名 + 总分精确相等）
# 3) 幂等重放一致性
import json
import time
import urllib.error
import urllib.request
import uuid

BASE = 'http://127.0.0.1:8001/api'
CID = '96d00dc9-9c7a-49df-bec6-0b22219563d5'  # 真实模型验收课程（固定 ID）


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, json.loads(raw) if raw else None


def wait_job(job_id, timeout=180):
    for _ in range(timeout):
        s, job = call('GET', f'/jobs/{job_id}')
        if s == 200 and job['status'] in ('succeeded', 'failed', 'cancelled'):
            return job
        time.sleep(1)
    raise TimeoutError(job_id)


# 1) 三题型混合出题
s, qz = call('POST', f'/courses/{CID}/quiz/generate', {
    'question_count': 3,
    'question_types': ['single_choice', 'multiple_choice', 'short_answer'],
})
print('generate:', s)
assert s == 202, qz
job = wait_job(qz['job_id'])
print('job:', job['status'], job.get('error_summary'))
assert job['status'] == 'succeeded', job.get('error_summary')

s, quiz = call('GET', f"/quizzes/{qz['quiz_id']}")
types = [q['question_type'] for q in quiz['questions']]
print('quiz:', quiz['status'], types)
assert quiz['status'] == 'open' and 'short_answer' in types

# 2) 提交（简答给一段真实作答文本，触发真实批改）
key = uuid.uuid4().hex
short = next(q for q in quiz['questions'] if q['question_type'] == 'short_answer')
answers = []
for q in quiz['questions']:
    if q['question_type'] == 'short_answer':
        answers.append({'question_id': q['question_id'], 'selected_option_ids': [],
                        'text': '超时后 ssthresh 减半并重新慢启动；收到 3 个重复 ACK 触发快重传与快恢复，cwnd 减半进入快恢复阶段。'})
    elif q['question_type'] == 'single_choice':
        answers.append({'question_id': q['question_id'], 'selected_option_ids': [q['options'][0]['id']], 'text': ''})
    else:
        answers.append({'question_id': q['question_id'], 'selected_option_ids': [o['id'] for o in q['options'][:2]], 'text': ''})

s, sub = call('POST', f"/quizzes/{quiz['quiz_id']}/submit", {'idempotency_key': key, 'answers': answers})
print('submit:', s)
assert s == 200, json.dumps(sub, ensure_ascii=False)[:500]

sa = next(r for r in sub['question_results'] if r['question_id'] == short['question_id'])
print('short-answer result: score %s/%s method=%s correct=%s' % (
    sa['score'], sa['max_score'], sa['grading_method'], sa['correct']))
print('feedback:', (sa['feedback_text'] or '')[:120])
assert sa['grading_method'] == 'rubric_llm'
assert 0 <= sa['score'] <= sa['max_score']

# 3) 幂等重放
s, sub2 = call('POST', f"/quizzes/{quiz['quiz_id']}/submit", {'idempotency_key': key, 'answers': answers})
print('replay identical:', sub2['submission_id'] == sub['submission_id'])
assert sub2['submission_id'] == sub['submission_id']

print('\nP0 REAL-MODEL VERIFICATION PASSED')
