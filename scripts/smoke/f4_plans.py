# F4 验收冒烟（真实后端 + mock LLM）：
# 1) 生成计划 → 每日分钟数合计 ≤ daily_minutes
# 2) 生成新版本后旧版本 inactive
# 3) 任务迁移 pending→completed→(skipped 409)
import json
import urllib.request
from collections import defaultdict
from datetime import date, timedelta

BASE = 'http://127.0.0.1:8000/api'
COURSE = '204637ae-a9a0-4708-832c-97a33351d133'


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, json.loads(raw) if raw else None


# 旧版本列表（应已有 active v1，来自此前冒烟；没有也不影响）
s, old_plans = call('GET', f'/courses/{COURSE}/plans')
print('before:', s, [(p['version_number'], p['status'], p['task_count']) for p in old_plans])

exam = (date.today() + timedelta(days=10)).isoformat()
s, plan = call('POST', f'/courses/{COURSE}/plan', {
    'exam_date': exam,
    'daily_minutes': 60,
    'target_score': 85,
})
print('create:', s, 'v%s' % plan['version_number'], plan['status'], 'tasks=%d' % len(plan['tasks']))
assert s == 201

# 1) 每日合计 ≤ daily_minutes
per_day = defaultdict(int)
for t in plan['tasks']:
    per_day[t['scheduled_date']] += t['estimated_minutes']
bad = {d: m for d, m in per_day.items() if m > 60}
print('days:', dict(sorted(per_day.items())))
assert not bad, f'capacity violated: {bad}'
print('OK 每日合计均 ≤ 60')

# 2) 旧版本 inactive
s, plans = call('GET', f'/courses/{COURSE}/plans')
statuses = {p['version_number']: p['status'] for p in plans}
print('versions:', statuses)
assert statuses[plan['version_number']] == 'active'
old = [v for v, st in statuses.items() if v != plan['version_number']]
assert all(statuses[v] == 'inactive' for v in old), statuses
print('OK 旧版本已停用')

# 3) 任务迁移：pending → completed（200）→ skipped（409）
pending = next(t for t in plan['tasks'] if t['status'] == 'pending')
s, updated = call('PATCH', f'/tasks/{pending["id"]}', {'status': 'completed'})
print('patch completed:', s, updated['status'])
assert s == 200 and updated['status'] == 'completed'

s, err = call('PATCH', f'/tasks/{pending["id"]}', {'status': 'skipped'})
print('patch skipped on completed:', s, err['error']['code'])
assert s == 409 and err['error']['code'] == 'INVALID_TASK_STATUS_TRANSITION'

# 非法状态值
s, err = call('PATCH', f'/tasks/{pending["id"]}', {'status': 'nonsense'})
print('patch nonsense:', s, err['error']['code'])
assert s == 400 and err['error']['code'] == 'INVALID_TASK_STATUS'

# 容量不足（明天考试 + 每天 15 分钟装不下所有任务 → 409）
s, err = call('POST', f'/courses/{COURSE}/plan', {
    'exam_date': (date.today() + timedelta(days=1)).isoformat(),
    'daily_minutes': 15,
    'target_score': 85,
})
print('capacity:', s, err['error']['code'], err['error'].get('details'))
assert s == 409 and err['error']['code'] == 'PLAN_CAPACITY_EXCEEDED'

# 过去日期 → 400
s, err = call('POST', f'/courses/{COURSE}/plan', {
    'exam_date': (date.today() - timedelta(days=1)).isoformat(),
    'daily_minutes': 60,
    'target_score': 85,
})
print('past exam:', s, err['error']['code'])
assert s == 400 and err['error']['code'] == 'INVALID_PLAN_CONSTRAINTS'

print('\nALL F4 API SMOKE PASSED')
