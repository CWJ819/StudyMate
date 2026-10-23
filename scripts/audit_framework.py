#!/usr/bin/env python
"""只读审计一个课程 active 知识框架的版本/图一致性。

用途：Phase 4 修复前后各跑一次，用同一口径对比。脚本只发 SELECT，并在
SQLite 上打开 ``PRAGMA query_only``；不依赖应用代码，可在线上库副本或
Studio 容器里直接运行。

    python scripts/audit_framework.py --course-id <uuid>
    python scripts/audit_framework.py --course-id <uuid> --json audit.json

口径：
- total_versions：active 版本的 node_version 行数；
- unique_node_ids：不同 knowledge_node_id 数；
- duplicate_leaf_versions：同一 node 在同一版本里出现多行叶 version 的额外行数；
- unreachable：从所有 parent_id IS NULL 的根出发走不到的行；
- duplicate_edges：按 (source_node_id, target_node_id, relation_type) 聚合后
  多出来的关系行数（无序对不计，方向保留）。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "studymate.db"


def _connect(database_url: str) -> sqlite3.Connection:
    if not database_url.startswith("sqlite:///"):
        raise SystemExit(
            "audit_framework.py 只支持 sqlite:/// URL；线上库请先复制到本地再跑。"
        )
    path = database_url.removeprefix("sqlite:///")
    if path == DEFAULT_DB.as_posix() or not Path(path).is_absolute():
        path = str((Path.cwd() / path).resolve()) if not Path(path).is_absolute() else path
    if not Path(path).exists():
        raise SystemExit(f"数据库不存在：{path}")
    connection = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _active_framework(connection: sqlite3.Connection, course_id: str) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT id, version_number, status, activated_at
        FROM knowledge_framework_versions
        WHERE course_id = ? AND status = 'active'
        ORDER BY version_number DESC
        LIMIT 1
        """,
        (course_id,),
    ).fetchone()
    if row is None:
        raise SystemExit(f"课程 {course_id} 没有 active 框架")
    return row


def _walk_roots(rows: list[sqlite3.Row]) -> tuple[set[str], list[dict[str, Any]]]:
    by_id = {row["id"]: row for row in rows}
    roots = [row for row in rows if row["parent_id"] is None]
    reachable: set[str] = set()
    broken: list[dict[str, Any]] = []
    for root in roots:
        stack = [root["id"]]
        while stack:
            node_id = stack.pop()
            if node_id in reachable:
                continue
            reachable.add(node_id)
            for child in rows:
                if child["parent_id"] == node_id:
                    stack.append(child["id"])
    for row in rows:
        if row["id"] in reachable:
            continue
        chain: list[str] = []
        current = row
        seen: set[str] = set()
        while current is not None and current["id"] not in seen:
            seen.add(current["id"])
            chain.append(current["title"])
            parent_id = current["parent_id"]
            if parent_id is None:
                break
            parent = by_id.get(parent_id)
            if parent is None:
                chain.append(f"<missing parent {parent_id}>")
                break
            current = parent
        broken.append(
            {
                "node_version_id": row["id"],
                "knowledge_node_id": row["knowledge_node_id"],
                "title": row["title"],
                "chain": chain,
            }
        )
    return reachable, broken


def audit(course_id: str, database_url: str) -> dict[str, Any]:
    connection = _connect(database_url)
    try:
        framework = _active_framework(connection, course_id)
        versions = connection.execute(
            """
            SELECT id, parent_id, knowledge_node_id, title, level, is_leaf, sort_order
            FROM knowledge_node_versions
            WHERE framework_version_id = ?
            ORDER BY sort_order, id
            """,
            (framework["id"],),
        ).fetchall()
        relations = connection.execute(
            """
            SELECT source_node_version_id, target_node_version_id, relation_type, confidence
            FROM knowledge_node_relations
            WHERE framework_version_id = ?
            """,
            (framework["id"],),
        ).fetchall()
    finally:
        connection.close()

    version_by_id = {row["id"]: row for row in versions}
    per_node = Counter(row["knowledge_node_id"] for row in versions)
    duplicate_leaf_versions = sum(
        count - 1
        for node_id, count in per_node.items()
        if count > 1
        and any(row["knowledge_node_id"] == node_id and row["is_leaf"] for row in versions)
    )

    reachable, broken = _walk_roots(versions)

    logical_edges: dict[tuple[str, str, str], dict[str, Any]] = {}
    duplicate_edge_rows = 0
    for relation in relations:
        source = version_by_id.get(relation["source_node_version_id"])
        target = version_by_id.get(relation["target_node_version_id"])
        if source is None or target is None:
            continue
        key = (
            source["knowledge_node_id"],
            target["knowledge_node_id"],
            relation["relation_type"],
        )
        existing = logical_edges.get(key)
        if existing is None:
            logical_edges[key] = {
                "source": key[0],
                "target": key[1],
                "relation_type": key[2],
                "rows": 1,
                "max_confidence": relation["confidence"],
            }
        else:
            existing["rows"] += 1
            existing["max_confidence"] = max(
                existing["max_confidence"], relation["confidence"]
            )
            duplicate_edge_rows += 1

    return {
        "course_id": course_id,
        "framework_version_id": framework["id"],
        "version_number": framework["version_number"],
        "total_versions": len(versions),
        "unique_node_ids": len(per_node),
        "containers": sum(1 for row in versions if not row["is_leaf"]),
        "leaves": sum(1 for row in versions if row["is_leaf"]),
        "duplicate_leaf_versions": duplicate_leaf_versions,
        "versions_by_node_distribution": dict(sorted(Counter(per_node.values()).items())),
        "reachable_versions": len(reachable),
        "unreachable_versions": len(versions) - len(reachable),
        "unreachable_examples": broken[:20],
        "relation_rows": len(relations),
        "logical_edges": len(logical_edges),
        "duplicate_edge_rows": duplicate_edge_rows,
        "edges_with_multiple_rows": [
            edge for edge in logical_edges.values() if edge["rows"] > 1
        ][:20],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course-id", required=True)
    parser.add_argument(
        "--database-url",
        default=f"sqlite:///{DEFAULT_DB.as_posix()}",
        help="sqlite:/// 路径；默认 StudyMate/data/studymate.db",
    )
    parser.add_argument("--json", type=Path, help="把结果同时写入 JSON 文件")
    args = parser.parse_args()

    result = audit(args.course_id, args.database_url)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.json is not None:
        args.json.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
