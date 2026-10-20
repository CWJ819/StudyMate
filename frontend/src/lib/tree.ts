// 知识树共享工具（Quiz/Review/Plan/Dashboard 都要收集叶子节点）
import type { KnowledgeTreeNode } from '../api/endpoints'

export function collectLeaves(nodes: KnowledgeTreeNode[], acc: KnowledgeTreeNode[] = []) {
  for (const n of nodes) {
    if (n.is_leaf) acc.push(n)
    else collectLeaves(n.children ?? [], acc)
  }
  return acc
}
