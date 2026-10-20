"""只读检查开发库里各课程 active 框架的层级结构（诊断侧边栏展示用）。"""
import sqlite3
import sys
from collections import Counter

conn = sqlite3.connect("file:data/studymate.db?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("select id, name from courses")
courses = cur.fetchall()

for c in courses:
    cur.execute(
        """
        select nv.knowledge_node_id as id, nv.parent_id, nv.title, nv.is_leaf,
               nv.level, nv.sort_order, nv.section_label
        from knowledge_node_versions nv
        join knowledge_framework_versions v on v.id = nv.framework_version_id
        where v.course_id = ? and v.status = 'active'
        order by nv.sort_order
        """,
        (c["id"],),
    )
    rows = cur.fetchall()
    if not rows:
        print(f"== {c['name']} ({c['id'][:8]}): 无 active 框架")
        continue

    amap = {r["id"]: r for r in rows}

    def depth(row):
        d, i = 0, row["id"]
        while True:
            parent = amap.get(i)
            if parent is None or not parent["parent_id"] or d >= 10:
                return d
            i = parent["parent_id"]
            d += 1

    dist = Counter(depth(r) for r in rows)
    leaves = sum(1 for r in rows if r["is_leaf"])
    print(
        f"== {c['name']} ({c['id'][:8]}): {len(rows)} 节点, "
        f"depth 分布 {dict(sorted(dist.items()))}, 叶子 {leaves}"
    )
    for r in rows:
        if depth(r) == 1:
            kids = sum(1 for x in rows if x["parent_id"] == r["id"])
            print(f"   L1: {(r['title'] or '')[:58]} | 子节点 {kids}")
    print()

if len(sys.argv) > 1 and sys.argv[1] == "-v":
    # 打印主课程前 30 行原始排序，看标题长度
    cid = courses[0]["id"]
    cur.execute(
        """
        select nv.title, nv.is_leaf, nv.section_label
        from knowledge_node_versions nv
        join knowledge_framework_versions v on v.id = nv.framework_version_id
        where v.course_id = ? and v.status = 'active' order by nv.sort_order limit 30
        """,
        (cid,),
    )
    for r in cur.fetchall():
        print(f"   [{r['is_leaf']}] {r['section_label']} | {(r['title'] or '')[:70]}")
