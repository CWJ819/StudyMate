// 知识框架：构建与轮询（useJob）、树视图、节点详情与来源 chunk 内联展开、版本列表、掌握度叠加
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router'
import { useEffect, useId, useMemo, useState } from 'react'
import {
  addKnowledgeAliasLock,
  buildKnowledge,
  deleteKnowledgeAliasLock,
  getChunk,
  getKnowledge,
  getKnowledgeGraph,
  getKnowledgeHighlights,
  getKnowledgeNode,
  getKnowledgeTree,
  listKnowledgeAliasLocks,
  listKnowledgeMergeDecisions,
  listKnowledgeVersions,
  listMastery,
  type KnowledgeMergeDecision,
  type KnowledgeScoredTreeNode,
  type KnowledgeSource,
  type MasteryState,
} from '../api/endpoints'
import { ApiError } from '../api/client'
import { frameworkStatus, isJobTerminal, jobStatusLabel } from '../api/status'
import { loadJobId, saveJobId, useJob } from '../hooks/useJob'
import { EmptyState } from '../components/EmptyState'
import { ErrorNotice } from '../components/ErrorNotice'

/** pptx 的“页”显示为幻灯片（plan §5） */
function pageWord(filename: string): string {
  return filename.toLowerCase().endsWith('.pptx') ? '张幻灯片' : '页'
}

const COMPONENT_LABELS: Record<string, string> = {
  source_pages: '出处页数',
  relation_centrality: '关系连接',
  content_length: '内容长度',
  quiz_reinforcement: '测验强化',
  source_documents: '跨文档覆盖',
  prerequisite_depth: '前置链深度',
  prerequisite_indegree: '前置入度',
}

const IMPORTANCE_WEIGHTS: Record<string, number> = {
  source_pages: 0.25,
  relation_centrality: 0.25,
  content_length: 0.15,
  quiz_reinforcement: 0.15,
  source_documents: 0.2,
}

const RELATION_TYPE_LABELS: Record<string, string> = {
  prerequisite: '前置',
  derives: '推导',
  causes: '因果',
  contrasts_with: '对比',
  applies_to: '应用',
  counterexample_of: '反例',
}

const RELATION_TYPES = Object.keys(RELATION_TYPE_LABELS)

function contributionReasons(
  components: Record<string, number> | null | undefined,
  weights: Record<string, number>,
  limit = 2,
): { key: string; label: string; value: number; weighted: number }[] {
  if (!components) return []
  return Object.entries(components)
    .map(([key, value]) => ({
      key,
      label: COMPONENT_LABELS[key] ?? key,
      value,
      weighted: value * (weights[key] ?? 0),
    }))
    .sort((a, b) => b.weighted - a.weighted)
    .slice(0, limit)
}

/** 出处行：点击内联展开/收起该 chunk 的完整原文（不再弹侧边抽屉） */
function SourceItem({ source }: { source: KnowledgeSource }) {
  const [open, setOpen] = useState(false)
  const panelId = useId()
  const chunkId = source.chunk_id
  const chunk = useQuery({
    queryKey: ['chunk', chunkId],
    queryFn: () => getChunk(chunkId!),
    enabled: open && chunkId != null,
  })
  if (chunkId == null) {
    return (
      <span className="text-ink3">
        {source.filename} · 第 {source.page_number} {pageWord(source.filename)}（来源已不可用）
      </span>
    )
  }
  return (
    <div>
      <button
        type="button"
        className="flex w-fit items-center gap-1.5 text-left text-[13px] text-accent hover:underline"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
      >
        <span aria-hidden="true" className="flex-none">
          {open ? '▾' : '▸'}
        </span>
        <span>
          {source.filename} · 第 {source.page_number} {pageWord(source.filename)}
        </span>
        <span className="flex-none text-[11.5px] text-ink3">{open ? '收起原文' : '展开原文'}</span>
      </button>
      {open && (
        <div
          id={panelId}
          className="ml-5 mt-1.5 rounded-md border border-border bg-quote-bg px-3.5 py-2.5"
        >
          {chunk.isLoading && <p className="text-[13px] text-ink3">加载中…</p>}
          {chunk.isError && <ErrorNotice error={chunk.error} />}
          {chunk.data && (
            <p className="whitespace-pre-wrap text-[13.5px] leading-[1.7] text-ink">
              {chunk.data.text}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

/** 组内默认显示的行数（报告 §5.3.3：避免 96 条一次性撑开） */
const BATCH_LIMIT = 20

/** 后代叶子中已有掌握度记录的数量（组头「已测 M」徽标） */
function countTested(node: KnowledgeScoredTreeNode, mastery: Map<string, MasteryState>): number {
  let n = 0
  const walk = (cur: KnowledgeScoredTreeNode) => {
    for (const c of cur.children ?? []) {
      if (c.is_leaf && mastery.has(c.knowledge_node_id)) n += 1
      walk(c)
    }
  }
  walk(node)
  return n
}

/** section_label 已经出现在 title 开头时不再重复渲染（如 label=第3章、title=第3章 运输层） */
function labelDuplicatesTitle(label: string | null | undefined, title: string): boolean {
  const normalized = (label ?? '').trim()
  if (!normalized) return false
  return title.trim().startsWith(normalized)
}

/** 后代叶子总数（容器摘要卡的「M 个知识点」） */
function countLeaves(node: KnowledgeScoredTreeNode): number {
  const children = node.children ?? []
  if (children.length === 0) return node.is_leaf ? 1 : 0
  return children.reduce((sum, child) => sum + countLeaves(child), 0)
}

function findTreeNode(nodes: KnowledgeScoredTreeNode[], id: string): KnowledgeScoredTreeNode | null {
  for (const node of nodes) {
    if (node.knowledge_node_id === id) return node
    const found = findTreeNode(node.children ?? [], id)
    if (found) return found
  }
  return null
}

/** 返回从根到目标节点的容器 id 路径（点击重难点/关系节点时展开） */
function findPath(
  nodes: KnowledgeScoredTreeNode[],
  id: string,
  ancestors: string[] = [],
): string[] | null {
  for (const node of nodes) {
    const path = [...ancestors, node.knowledge_node_id]
    if (node.knowledge_node_id === id) return path
    const found = findPath(node.children ?? [], id, path)
    if (found) return found
  }
  return null
}

/** 掌握度叠加（估计值·依据次数，未测验灰）；树行与平铺兜底行共用 */
function MasteryBadge({ m }: { m?: MasteryState }) {  if (!m) return <span className="flex-none text-[11px] text-ink3">未测验</span>
  return (
    <span className="flex flex-none items-center gap-1 font-mono text-[11.5px] text-ink2">
      <span className="inline-block h-1.5 w-10 overflow-hidden rounded-sm bg-untested-bg">
        <span
          className="block h-full bg-accent"
          style={{ width: `${Math.round(m.mastery_estimate * 100)}%` }}
        />
      </span>
      {m.mastery_estimate.toFixed(2)}·{m.evidence_count}
    </span>
  )
}

/** 平铺兜底分组（报告 §5.3.3）：根 + 全叶子的旧框架按 sources[0].document_id 现场分组，只影响展示 */
interface FlatGroup {
  key: string
  filename: string
  leaves: KnowledgeScoredTreeNode[]
}

function buildFlatGroups(tree: KnowledgeScoredTreeNode[]): FlatGroup[] | null {
  // 旧框架形态：顶层直接是叶子（API 不含合成根），没有任何层级 → 按来源文档现场分组
  if (tree.length === 0 || !tree.every((n) => n.is_leaf)) return null
  const groups: FlatGroup[] = []
  const byKey = new Map<string, FlatGroup>()
  for (const leaf of tree) {
    const source = leaf.sources[0]
    const key = source?.document_id ?? '__no_source__'
    let group = byKey.get(key)
    if (!group) {
      group = { key, filename: source?.filename ?? '未标注来源', leaves: [] }
      byKey.set(key, group)
      groups.push(group)
    }
    group.leaves.push(leaf)
  }
  return groups
}

/** 平铺兜底的叶子行：小字号 + 参考线缩进 + 单行 truncate + 行内 P{page} */
function FlatLeafRow({
  node,
  selectedId,
  mastery,
  onSelect,
}: {
  node: KnowledgeScoredTreeNode
  selectedId: string | null
  mastery: Map<string, MasteryState>
  onSelect: (id: string) => void
}) {
  const m = mastery.get(node.knowledge_node_id)
  const source = node.sources[0]
  return (
    <div
      className={`flex cursor-pointer items-center gap-1.5 border-l-2 py-[3px] pr-3 text-[12.5px] ${
        selectedId === node.knowledge_node_id
          ? 'border-accent bg-accent-bg/60 font-medium'
          : 'border-transparent hover:bg-bg'
      }`}
      style={{ paddingLeft: '26px' }}
      onClick={() => onSelect(node.knowledge_node_id)}
      role="treeitem"
      aria-selected={selectedId === node.knowledge_node_id}
    >
      <span className="min-w-0 flex-1 truncate" title={node.title}>
        {node.section_label && !labelDuplicatesTitle(node.section_label, node.title) && (
          <span className="mr-1 font-mono text-[11px] text-ink3">{node.section_label}</span>
        )}
        <span className="align-baseline">{node.title}</span>
      </span>
      {source && (
        <span className="flex-none font-mono text-[10.5px] text-ink3">P{source.page_number}</span>
      )}
      <MasteryBadge m={m} />
    </div>
  )
}

/** 平铺兜底的文档组：组头（文件名 · N 个 · 已测 M，默认收起）+ 组内前 20 条 + 展开其余 */
function FlatGroupBlock({
  group,
  open,
  showAll,
  selectedId,
  mastery,
  onToggle,
  onShowAll,
  onSelect,
}: {
  group: FlatGroup
  open: boolean
  showAll: boolean
  selectedId: string | null
  mastery: Map<string, MasteryState>
  onToggle: () => void
  onShowAll: () => void
  onSelect: (id: string) => void
}) {
  const tested = group.leaves.filter((l) => mastery.has(l.knowledge_node_id)).length
  const visible = showAll ? group.leaves : group.leaves.slice(0, BATCH_LIMIT)
  const rest = group.leaves.length - BATCH_LIMIT
  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 border-l-2 border-transparent px-3 py-1.5 text-left text-[13px] font-semibold text-ink hover:bg-bg"
      >
        <span aria-hidden="true" className="w-3.5 flex-none text-xs text-ink3">
          {open ? '▾' : '▸'}
        </span>
        <span className="min-w-0 flex-1 truncate" title={group.filename}>
          <span aria-hidden="true" className="mr-1">
            📄
          </span>
          {group.filename}
        </span>
        <span className="flex-none font-mono text-[11px] text-ink3">
          {group.leaves.length} 个{tested > 0 ? ` · 已测 ${tested}` : ''}
        </span>
      </button>
      {open && (
        <div role="group">
          {visible.map((leaf) => (
            <FlatLeafRow
              key={leaf.knowledge_node_id}
              node={leaf}
              selectedId={selectedId}
              mastery={mastery}
              onSelect={onSelect}
            />
          ))}
          {rest > 0 && !showAll && (
            <button
              type="button"
              onClick={onShowAll}
              className="block w-full border-l-2 border-transparent py-1 pr-3 text-left text-[11.5px] text-accent hover:bg-bg"
              style={{ paddingLeft: '42px' }}
            >
              展开其余 {rest} 条 ▾
            </button>
          )}
        </div>
      )}
    </div>
  )
}

/** 读取时评分：树行迷你条（分数为工程估计值，不写成精确测量） */
function ScoreBar({ value, label = '重要度' }: { value: number; label?: string }) {
  return (
    <span
      className="flex flex-none items-center gap-1 font-mono text-[10.5px] text-ink3"
      title={`${label}（估计值） ${value.toFixed(2)}`}
    >
      <span className="inline-block h-1 w-7 overflow-hidden rounded-sm bg-untested-bg">
        <span
          className="block h-full bg-accent/70"
          style={{ width: `${Math.round(value * 100)}%` }}
        />
      </span>
      {value.toFixed(2)}
    </span>
  )
}

/** 树行：缩进 + 展开/折叠 + 选中高亮 + 掌握度叠加；组头带 N/已测 徽标、组内前 20 条分批、叶子行内 P{page} */
function TreeRow({
  node,
  depth,
  expanded,
  fullIds,
  selectedId,
  mastery,
  onToggle,
  onToggleFull,
  onSelect,
}: {
  node: KnowledgeScoredTreeNode
  depth: number
  expanded: Set<string>
  fullIds: Set<string>
  selectedId: string | null
  mastery: Map<string, MasteryState>
  onToggle: (id: string) => void
  onToggleFull: (id: string) => void
  onSelect: (id: string) => void
}) {
  const children = node.children ?? []
  const hasChildren = children.length > 0
  const isOpen = expanded.has(node.knowledge_node_id)
  const showAll = fullIds.has(node.knowledge_node_id)
  const m = mastery.get(node.knowledge_node_id)
  const tested = countTested(node, mastery)
  const visibleChildren = showAll ? children : children.slice(0, BATCH_LIMIT)
  const rest = children.length - BATCH_LIMIT
  return (
    <div>
      <div
        className={`flex cursor-pointer items-center gap-1.5 border-l-2 py-1 pr-3 text-[13.5px] ${
          selectedId === node.knowledge_node_id
            ? 'border-accent bg-accent-bg/60 font-medium'
            : 'border-transparent hover:bg-bg'
        }`}
        style={{ paddingLeft: `${depth * 18 + 8}px` }}
        onClick={() => onSelect(node.knowledge_node_id)}
        role="treeitem"
        aria-selected={selectedId === node.knowledge_node_id}
        aria-expanded={hasChildren ? isOpen : undefined}
      >
        {hasChildren ? (
          <button
            type="button"
            className="w-4 flex-none text-xs text-ink3 hover:text-ink"
            onClick={(e) => {
              e.stopPropagation()
              onToggle(node.knowledge_node_id)
            }}
            aria-label={isOpen ? '折叠' : '展开'}
          >
            {isOpen ? '▾' : '▸'}
          </button>
        ) : (
          <span className="w-4 flex-none text-center text-[10px] text-ink3">·</span>
        )}
        <span className="min-w-0 flex-1 truncate" title={node.title}>
          {node.section_label && !labelDuplicatesTitle(node.section_label, node.title) && (
            <span className="mr-1 font-mono text-[12px] text-ink3">{node.section_label}</span>
          )}
          <span className="align-baseline">{node.title}</span>
        </span>
        {node.is_leaf ? (
          <ScoreBar value={node.importance} />
        ) : (
          <span
            className="flex-none rounded-full bg-accent-bg px-1.5 py-0.5 font-mono text-[10.5px] text-accent"
            title={`后代最高重要度（估计值） ${node.importance.toFixed(2)}`}
          >
            重要度 {node.importance.toFixed(2)}
          </span>
        )}
        {node.is_leaf && node.sources[0] && (
          <span className="flex-none font-mono text-[10.5px] text-ink3">
            P{node.sources[0].page_number}
          </span>
        )}
        {node.is_leaf && <MasteryBadge m={m} />}
        {hasChildren && (
          <span className="flex-none font-mono text-[11px] text-ink3">
            {children.length} 个{tested > 0 ? ` · 已测 ${tested}` : ''}
          </span>
        )}
      </div>
      {hasChildren && isOpen && (
        <div role="group">
          {visibleChildren.map((child) => (
            <TreeRow
              key={child.knowledge_node_id}
              node={child}
              depth={depth + 1}
              expanded={expanded}
              fullIds={fullIds}
              selectedId={selectedId}
              mastery={mastery}
              onToggle={onToggle}
              onToggleFull={onToggleFull}
              onSelect={onSelect}
            />
          ))}
          {rest > 0 && !showAll && (
            <button
              type="button"
              onClick={() => onToggleFull(node.knowledge_node_id)}
              className="block border-l-2 border-transparent py-1 pr-3 text-left text-[11.5px] text-accent hover:bg-bg"
              style={{ paddingLeft: `${depth * 18 + 26}px` }}
            >
              展开其余 {rest} 条 ▾
            </button>
          )}
        </div>
      )}
    </div>
  )
}

/** 容器节点摘要：标题 + 小节/知识点/已测计数 + 可直接点开的小节行（无新 API） */
function ContainerSummary({
  node,
  mastery,
  onSelect,
}: {
  node: KnowledgeScoredTreeNode
  mastery: Map<string, MasteryState>
  onSelect: (id: string) => void
}) {
  const children = node.children ?? []
  const sections = children.filter((child) => (child.children ?? []).length > 0)
  const directLeaves = children.length - sections.length
  const tested = countTested(node, mastery)
  return (
    <div className="mb-4 rounded-lg border border-border bg-bg px-4 py-3">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="min-w-0 truncate text-[17px] font-bold" title={node.title}>
          {node.title}
        </h2>
        <span className="flex-none font-mono text-[11.5px] text-ink3">
          {sections.length} 个小节 · {countLeaves(node)} 个知识点
          {tested > 0 ? ` · 已测 ${tested}` : ''}
        </span>
      </div>
      {sections.length > 0 && (
        <div className="mt-2 grid gap-0.5">
          {sections.map((child) => (
            <button
              key={child.knowledge_node_id}
              type="button"
              onClick={() => onSelect(child.knowledge_node_id)}
              className="flex items-center gap-2 rounded px-2 py-1 text-left text-[12.5px] text-ink2 hover:bg-surface"
            >
              <span className="min-w-0 flex-1 truncate" title={child.title}>
                {child.title}
              </span>
              <span className="flex-none font-mono text-[11px] text-ink3">
                {countLeaves(child)} 个 · 已测 {countTested(child, mastery)}
              </span>
            </button>
          ))}
        </div>
      )}
      {directLeaves > 0 && (
        <p className="mt-1.5 text-[11.5px] text-ink3">
          另有 {directLeaves} 个知识点直接挂在章下，展开左侧树即可查看。
        </p>
      )}
    </div>
  )
}

function NodeDetail({
  nodeId,
  score,
  hideHeading = false,
}: {
  nodeId: string
  score?: KnowledgeScoredTreeNode
  hideHeading?: boolean
}) {
  const detail = useQuery({
    queryKey: ['knode', nodeId],
    queryFn: () => getKnowledgeNode(nodeId),
  })
  if (detail.isError) return <ErrorNotice error={detail.error} />
  if (detail.isLoading || !detail.data) return <p className="text-[13px] text-ink3">加载中…</p>
  const d = detail.data
  const reasons = contributionReasons(score?.components, IMPORTANCE_WEIGHTS)
  return (
    <div>
      {!hideHeading && (
        <>
          {d.section_label && !labelDuplicatesTitle(d.section_label, d.title) && (
            <div className="text-[12px] font-mono text-ink3">{d.section_label}</div>
          )}
          <h2 className="mt-0.5 text-[18px] font-bold">{d.title}</h2>
        </>
      )}
      {d.content && (
        <p className="mt-2 whitespace-pre-wrap rounded-md bg-quote-bg px-4 py-3 text-[13.5px] leading-[1.7] text-ink">
          {d.content}
        </p>
      )}
      {d.aliases && d.aliases.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[11.5px] text-ink3">
          <span>别名</span>
          {d.aliases.map((alias) => (
            <span
              key={alias}
              className="rounded-full border border-border bg-bg px-2 py-0.5 text-ink2"
            >
              {alias}
            </span>
          ))}
        </div>
      )}
      {score && (
        <div className="mt-4 rounded-md border border-border bg-bg px-3.5 py-3">
          <h3 className="text-[13px] font-semibold text-ink2">学习优先级（估计值）</h3>
          <div className="mt-2 grid grid-cols-2 gap-3">
            <div>
              <div className="text-[11.5px] text-ink3">重要度</div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-[20px] font-bold text-accent">
                  {score.importance.toFixed(2)}
                </span>
                <span className="h-1.5 w-16 overflow-hidden rounded-sm bg-untested-bg">
                  <span
                    className="block h-full bg-accent"
                    style={{ width: `${Math.round(score.importance * 100)}%` }}
                  />
                </span>
              </div>
            </div>
            <div>
              <div className="text-[11.5px] text-ink3">难度</div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-[20px] font-bold text-ink">
                  {score.difficulty.toFixed(2)}
                </span>
                <span className="h-1.5 w-16 overflow-hidden rounded-sm bg-untested-bg">
                  <span
                    className="block h-full bg-ink3/60"
                    style={{ width: `${Math.round(score.difficulty * 100)}%` }}
                  />
                </span>
              </div>
            </div>
          </div>
          {reasons.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {reasons.map((reason) => (
                <span
                  key={reason.key}
                  className="rounded-full border border-border bg-surface px-2 py-0.5 text-[11px] text-ink3"
                  title={`${reason.label} · 原值 ${reason.value.toFixed(2)} · 归一化 — · 贡献 ${reason.weighted.toFixed(3)}`}
                >
                  {reason.label} 贡献 {reason.weighted.toFixed(3)}
                </span>
              ))}
            </div>
          )}
          <p className="mt-2 text-[11px] text-ink3">
            分数为工程估计值，依据抽取出处与关系证据，不代表教材语义重要性。
          </p>
        </div>
      )}
      {d.sources.length > 0 && (
        <div className="mt-4">
          <h3 className="text-[13px] font-semibold text-ink2">出处（{d.sources.length}）</h3>
          <div className="mt-1 grid gap-1">
            {d.sources.map((s, i) => (
              <SourceItem key={`${s.chunk_id}-${i}`} source={s} />
            ))}
          </div>
        </div>
      )}
      {d.relations.length > 0 && (
        <div className="mt-4">
          <h3 className="text-[13px] font-semibold text-ink2">关联</h3>
          <div className="mt-1 grid gap-1 text-[13px] text-ink2">
            {d.relations.map((r, i) => (
              <div key={i}>
                <span className="mr-1.5 rounded bg-untested-bg px-1.5 py-0.5 text-[11.5px] text-ink3">
                  {r.relation_type}
                </span>
                {r.target_title}
                <span className="ml-1 text-[11.5px] text-ink3">置信 {r.confidence.toFixed(2)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function HighlightsPanel({
  courseId,
  onPick,
}: {
  courseId: string
  onPick: (id: string) => void
}) {
  const [order, setOrder] = useState<'importance' | 'difficulty' | 'gap'>('importance')
  const [limit, setLimit] = useState(20)
  const highlights = useQuery({
    queryKey: ['knowledge-highlights', courseId, order, limit],
    queryFn: () => getKnowledgeHighlights(courseId, { order, limit }),
  })
  return (
    <section className="rounded-lg border border-border bg-surface">
      <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3">
        <div>
          <h2 className="text-[15px] font-semibold">重难点</h2>
          <p className="mt-0.5 text-[11.5px] text-ink3">按读取时评分排序；分数是工程估计值，不是教材语义重要性。</p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <div className="flex rounded-md border border-border p-0.5" role="group" aria-label="排序">
            {(['importance', 'difficulty', 'gap'] as const).map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={order === value}
                onClick={() => setOrder(value)}
                className={`rounded px-2 py-1 text-[11.5px] ${
                  order === value ? 'bg-accent-bg text-accent' : 'text-ink3 hover:text-ink'
                }`}
              >
                {value === 'importance' ? '重要度' : value === 'difficulty' ? '难度' : '掌握缺口'}
              </button>
            ))}
          </div>
          <select
            aria-label="显示数量"
            value={limit}
            onChange={(event) => setLimit(Number(event.target.value))}
            className="rounded-md border border-border bg-surface px-2 py-1 text-[11.5px] text-ink2"
          >
            {[10, 20, 50].map((value) => (
              <option key={value} value={value}>
                {value} 条
              </option>
            ))}
          </select>
        </div>
      </div>
      {highlights.isLoading && <p className="px-4 py-4 text-[13px] text-ink3">加载中…</p>}
      {highlights.isError && (
        <div className="px-4 py-4">
          <ErrorNotice error={highlights.error} />
        </div>
      )}
      {highlights.data && highlights.data.items.length === 0 && (
        <p className="px-4 py-4 text-[13px] text-ink3">当前版本还没有可排序的知识点。</p>
      )}
      {highlights.data && highlights.data.items.length > 0 && (
        <div className="divide-y divide-border">
          {highlights.data.items.map((item, index) => {
            const gap = item.importance * (1 - (item.mastery_estimate ?? 0))
            const reasons = item.reasons ?? []
            return (
              <div key={item.knowledge_node_id} className="flex items-start gap-3 px-4 py-2.5 text-[13px]">
                <span className="w-6 flex-none pt-0.5 text-right font-mono text-[11.5px] text-ink3">
                  {index + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <button
                    type="button"
                    onClick={() => onPick(item.knowledge_node_id)}
                    className="block max-w-full truncate text-left font-medium text-ink hover:text-accent"
                    title={item.title}
                  >
                    {item.title}
                  </button>
                  <div className="mt-0.5 truncate text-[11px] text-ink3" title={item.section_path.join(' > ')}>
                    {item.section_path.join(' > ')}
                  </div>
                </div>
                <div className="flex flex-none items-center gap-3">
                  <ScoreBar value={item.importance} label="重要度" />
                  <ScoreBar value={item.difficulty} label="难度" />
                  {item.untested || item.mastery_estimate == null ? (
                    <span className="flex-none rounded-full bg-untested-bg px-2 py-0.5 text-[11px] text-ink3">
                      未测验
                    </span>
                  ) : (
                    <span
                      className="flex-none rounded-full bg-surface px-2 py-0.5 font-mono text-[11px] text-ink2"
                      title={`掌握度 ${item.mastery_estimate.toFixed(2)} · 证据 ${item.evidence_count} 条`}
                    >
                      缺口 {gap.toFixed(2)} · 证据 {item.evidence_count}
                    </span>
                  )}
                  <span
                    className="flex-none cursor-help text-[11px] text-ink3"
                    title={reasons
                      .map(
                        (reason) =>
                          `${COMPONENT_LABELS[reason.component] ?? reason.component} · 原值 ${reason.value.toFixed(2)} · 归一化 ${reason.normalized.toFixed(2)} · 贡献 ${reason.contribution.toFixed(3)}`,
                      )
                      .join('\n')}
                  >
                    依据
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      )}
      {highlights.data && (
        <div className="border-t border-border px-4 py-3 text-[11.5px] leading-relaxed text-ink3">
          重要度权重：
          {Object.entries(highlights.data.basis.weights.importance)
            .map(([key, value]) => `${COMPONENT_LABELS[key] ?? key} ${value}`)
            .join(' · ')}
          ；难度权重：
          {Object.entries(highlights.data.basis.weights.difficulty)
            .map(([key, value]) => `${COMPONENT_LABELS[key] ?? key} ${value}`)
            .join(' · ')}
          。评分版本 {highlights.data.basis.scoring_version}；未测验 ≠ 薄弱。
        </div>
      )}
    </section>
  )
}

function GraphPanel({ courseId, onPick }: { courseId: string; onPick: (id: string) => void }) {
  const graph = useQuery({
    queryKey: ['knowledge-graph', courseId],
    queryFn: () => getKnowledgeGraph(courseId),
  })
  const [type, setType] = useState<string>('all')
  const [openEvidence, setOpenEvidence] = useState<Set<string>>(new Set())
  const nodeMap = useMemo(
    () => new Map((graph.data?.nodes ?? []).map((node) => [node.knowledge_node_id, node])),
    [graph.data],
  )
  const edges = (graph.data?.edges ?? []).filter((edge) => type === 'all' || edge.relation_type === type)
  const typeCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const edge of graph.data?.edges ?? []) {
      counts.set(edge.relation_type, (counts.get(edge.relation_type) ?? 0) + 1)
    }
    return counts
  }, [graph.data])
  return (
    <section className="rounded-lg border border-border bg-surface">
      <div className="border-b border-border px-4 py-3">
        <h2 className="text-[15px] font-semibold">关系图</h2>
        <p className="mt-0.5 text-[11.5px] text-ink3">
          只展示构建时产出的关系边；关系来自同一次抽取，只连接同一窗口内的叶子。
        </p>
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          <button
            type="button"
            aria-pressed={type === 'all'}
            onClick={() => setType('all')}
            className={`rounded-full border px-2.5 py-1 text-[11.5px] ${
              type === 'all' ? 'border-accent bg-accent-bg text-accent' : 'border-border text-ink2'
            }`}
          >
            全部 {graph.data?.edges.length ?? 0}
          </button>
          {RELATION_TYPES.map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={type === value}
              onClick={() => setType(value)}
              className={`rounded-full border px-2.5 py-1 text-[11.5px] ${
                type === value ? 'border-accent bg-accent-bg text-accent' : 'border-border text-ink2'
              }`}
            >
              {RELATION_TYPE_LABELS[value]} {typeCounts.get(value) ?? 0}
            </button>
          ))}
        </div>
      </div>
      {graph.isLoading && <p className="px-4 py-4 text-[13px] text-ink3">加载中…</p>}
      {graph.isError && (
        <div className="px-4 py-4">
          <ErrorNotice error={graph.error} />
        </div>
      )}
      {graph.data && edges.length === 0 && (
        <p className="px-4 py-4 text-[13px] text-ink3">
          {graph.data.edges.length === 0 ? '当前版本还没有关系边。' : '该类型下没有关系边。'}
        </p>
      )}
      <div className="divide-y divide-border">
        {edges.map((edge, index) => {
          const source = nodeMap.get(edge.source)
          const target = nodeMap.get(edge.target)
          const key = `${edge.source}-${edge.target}-${edge.relation_type}-${index}`
          const evidenceOpen = openEvidence.has(key)
          return (
            <div key={key} className="px-4 py-2.5 text-[12.5px]">
              <div className="flex flex-wrap items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => onPick(edge.source)}
                  className="max-w-[220px] truncate rounded-full border border-border bg-bg px-2 py-0.5 text-ink2 hover:text-accent"
                  title={source?.title ?? edge.source}
                >
                  {source?.title ?? edge.source}
                </button>
                <span className="text-ink3">→</span>
                <span className="rounded bg-untested-bg px-1.5 py-0.5 text-[10.5px] text-ink3">
                  {RELATION_TYPE_LABELS[edge.relation_type] ?? edge.relation_type}
                </span>
                <span className="text-ink3">→</span>
                <button
                  type="button"
                  onClick={() => onPick(edge.target)}
                  className="max-w-[220px] truncate rounded-full border border-border bg-bg px-2 py-0.5 text-ink2 hover:text-accent"
                  title={target?.title ?? edge.target}
                >
                  {target?.title ?? edge.target}
                </button>
                <span className="ml-auto flex items-center gap-1 font-mono text-[10.5px] text-ink3">
                  置信
                  <span className="inline-block h-1 w-10 overflow-hidden rounded-sm bg-untested-bg">
                    <span
                      className="block h-full bg-accent/60"
                      style={{ width: `${Math.round(edge.confidence * 100)}%` }}
                    />
                  </span>
                  {edge.confidence.toFixed(2)}
                </span>
              </div>
              {edge.evidence && (
                <div className="mt-1 pl-1">
                  <button
                    type="button"
                    className="text-[11px] text-accent hover:underline"
                    aria-expanded={evidenceOpen}
                    onClick={() =>
                      setOpenEvidence((prev) => {
                        const next = new Set(prev)
                        if (next.has(key)) next.delete(key)
                        else next.add(key)
                        return next
                      })
                    }
                  >
                    {evidenceOpen ? '收起依据' : '展开依据'}
                  </button>
                  {evidenceOpen && (
                    <p className="mt-1 whitespace-pre-wrap rounded bg-quote-bg px-2.5 py-1.5 text-[12px] leading-relaxed text-ink2">
                      {edge.evidence}
                    </p>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
      {graph.data && (
        <div className="border-t border-border px-4 py-2.5 text-[11.5px] text-ink3">
          {graph.data.nodes.length} 个节点 · {graph.data.edges.length} 条关系边（已按 node id 与三元组去重）
        </div>
      )}
    </section>
  )
}

function MergePanel({ courseId }: { courseId: string }) {
  const queryClient = useQueryClient()
  const decisions = useQuery({
    queryKey: ['knowledge-merge-decisions', courseId],
    queryFn: () => listKnowledgeMergeDecisions(courseId),
  })
  const locks = useQuery({
    queryKey: ['knowledge-alias-locks', courseId],
    queryFn: () => listKnowledgeAliasLocks(courseId),
  })
  const [message, setMessage] = useState<string | null>(null)
  const addLock = useMutation({
    mutationFn: (decision: KnowledgeMergeDecision) =>
      addKnowledgeAliasLock(courseId, {
        title_a: decision.canonical_title,
        title_b: decision.aliases[0]!,
      }),
    onSuccess: () => {
      setMessage('已锁定，下次重建时这两个标题不再合并。')
      queryClient.invalidateQueries({ queryKey: ['knowledge-merge-decisions', courseId] })
      queryClient.invalidateQueries({ queryKey: ['knowledge-alias-locks', courseId] })
    },
    onError: (error) => setMessage(error instanceof Error ? error.message : '锁定失败'),
  })
  const removeLock = useMutation({
    mutationFn: (lock: { title_a: string; title_b: string }) =>
      deleteKnowledgeAliasLock(courseId, lock),
    onSuccess: () => {
      setMessage('已解锁。')
      queryClient.invalidateQueries({ queryKey: ['knowledge-merge-decisions', courseId] })
      queryClient.invalidateQueries({ queryKey: ['knowledge-alias-locks', courseId] })
    },
    onError: (error) => setMessage(error instanceof Error ? error.message : '解锁失败'),
  })
  return (
    <section className="rounded-lg border border-border bg-surface">
      <div className="border-b border-border px-4 py-3">
        <h2 className="text-[15px] font-semibold">整合记录</h2>
        <p className="mt-0.5 text-[11.5px] text-ink3">
          Stage C 把跨文档、跨 section 的同概念标题合并为一个知识点；相似度与方法是确定性规则的结果，不是语义判断。
        </p>
      </div>
      {decisions.isLoading && <p className="px-4 py-4 text-[13px] text-ink3">加载中…</p>}
      {decisions.isError && (
        <div className="px-4 py-4">
          <ErrorNotice error={decisions.error} />
        </div>
      )}
      {decisions.data && decisions.data.decisions.length === 0 && (
        <p className="px-4 py-4 text-[13px] text-ink3">当前版本没有跨文档合并。</p>
      )}
      {message && <p className="mx-4 my-2 rounded bg-accent-bg px-3 py-1.5 text-[12px] text-accent">{message}</p>}
      <div className="divide-y divide-border">
        {(decisions.data?.decisions ?? []).map((decision) => (
          <div key={decision.id} className="flex flex-wrap items-center gap-2 px-4 py-2.5 text-[12.5px]">
            <span className="rounded bg-untested-bg px-1.5 py-0.5 text-[10.5px] text-ink3">
              {decision.method === 'exact' ? '精确' : '相似'}
            </span>
            <span className="font-medium text-ink">{decision.canonical_title}</span>
            {decision.aliases.length > 0 && (
              <span className="text-ink3">← {decision.aliases.join(' / ')}</span>
            )}
            {decision.similarity != null && (
              <span className="font-mono text-[11px] text-ink3">相似度 {decision.similarity.toFixed(2)}</span>
            )}
            <span className="text-[11px] text-ink3">{decision.distinct_documents} 份文档</span>
            {decision.aliases.length > 0 && (
              <button
                type="button"
                disabled={addLock.isPending}
                onClick={() => addLock.mutate(decision)}
                className="ml-auto rounded border border-border2 px-2 py-0.5 text-[11.5px] text-ink2 hover:text-ink disabled:opacity-50"
              >
                禁止再合并
              </button>
            )}
          </div>
        ))}
      </div>
      {(locks.data?.length ?? 0) > 0 && (
        <div className="border-t border-border px-4 py-3">
          <h3 className="text-[12px] font-semibold text-ink2">已锁定的标题对</h3>
          <div className="mt-1.5 grid gap-1">
            {(locks.data ?? []).map((lock) => (
              <div key={`${lock.title_a}-${lock.title_b}`} className="flex items-center gap-2 text-[12px] text-ink2">
                <span className="truncate">{lock.title_a}</span>
                <span className="text-ink3">↔</span>
                <span className="truncate">{lock.title_b}</span>
                <button
                  type="button"
                  disabled={removeLock.isPending}
                  onClick={() => removeLock.mutate(lock)}
                  className="ml-auto text-[11.5px] text-accent hover:underline disabled:opacity-50"
                >
                  解锁
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}


export function KnowledgePage() {
  const { courseId } = useParams()
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  // 层级树：超过 BATCH_LIMIT 的组点过「展开其余」的节点
  const [expandedFull, setExpandedFull] = useState<Set<string>>(new Set())
  // 平铺兜底分组：展开的组 / 解除 20 条截断的组
  const [groupOpen, setGroupOpen] = useState<Set<string>>(new Set())
  const [groupShowAll, setGroupShowAll] = useState<Set<string>>(new Set())
  const [showVersions, setShowVersions] = useState(false)
  const [buildJobId, setBuildJobId] = useState<string | null>(null)
  const [buildError, setBuildError] = useState<unknown>(null)
  const [view, setView] = useState<'tree' | 'highlights' | 'graph' | 'merge'>('tree')

  const framework = useQuery({
    queryKey: ['knowledge', courseId],
    queryFn: () => getKnowledge(courseId!),
    enabled: courseId !== undefined,
    retry: false,
  })
  const scored = useQuery({
    queryKey: ['knowledge-scored', courseId],
    queryFn: () => getKnowledgeTree(courseId!),
    enabled: courseId !== undefined,
    retry: false,
  })
  const notBuilt =
    (framework.isError && framework.error instanceof ApiError && framework.error.code === 'RESOURCE_NOT_FOUND') ||
    (scored.isError && scored.error instanceof ApiError && scored.error.code === 'RESOURCE_NOT_FOUND')
  const otherError =
    framework.isError && !(framework.error instanceof ApiError && framework.error.code === 'RESOURCE_NOT_FOUND')
      ? framework.error
      : scored.isError && !(scored.error instanceof ApiError && scored.error.code === 'RESOURCE_NOT_FOUND')
        ? scored.error
        : null

  const mastery = useQuery({
    queryKey: ['mastery', courseId],
    queryFn: () => listMastery(courseId!),
    enabled: courseId !== undefined,
  })
  const masteryMap = useMemo(
    () => new Map((mastery.data ?? []).map((m) => [m.knowledge_node_id, m])),
    [mastery.data],
  )

  // 刷新后从 localStorage 恢复 job_id（仅用于失败原因与“仍在处理”提示）
  useEffect(() => {
    if (courseId != null && buildJobId == null) {
      const saved = loadJobId(`knowledge:${courseId}`)
      if (saved != null) setBuildJobId(saved)
    }
  }, [courseId, buildJobId])

  const buildJob = useJob(buildJobId, {
    onSettledInvalidate: [
      ['knowledge', courseId],
      ['knowledge-scored', courseId],
      ['knowledge-versions', courseId],
      ['knowledge-highlights', courseId],
      ['knowledge-graph', courseId],
      ['knowledge-merge-decisions', courseId],
    ],
  })

  const building =
    framework.data?.status === 'building' ||
    (buildJob.job != null && !isJobTerminal(buildJob.job.status))

  const build = useMutation({
    mutationFn: () => buildKnowledge(courseId!, {}),
    onSuccess: (result) => {
      setBuildError(null)
      setBuildJobId(result.job_id)
      if (courseId != null) saveJobId(`knowledge:${courseId}`, result.job_id)
      queryClient.invalidateQueries({ queryKey: ['knowledge', courseId] })
      queryClient.invalidateQueries({ queryKey: ['knowledge-scored', courseId] })
    },
    onError: (err) => setBuildError(err),
  })

  const versions = useQuery({
    queryKey: ['knowledge-versions', courseId],
    queryFn: () => listKnowledgeVersions(courseId!),
    enabled: courseId !== undefined && showVersions,
  })

  const tree = scored.data?.tree ?? []
  const meta = framework.data ? frameworkStatus(framework.data.status) : null
  const leafCount = tree.reduce((total, node) => total + countLeaves(node), 0)
  // 右侧详情：容器节点额外渲染摘要卡（计数 + 可点开的小节）
  const selectedNode = useMemo(
    () => (selectedId ? findTreeNode(tree, selectedId) : null),
    [tree, selectedId],
  )
  // 旧框架（根 + 全叶子）→ 按来源文档分组的平铺兜底；新框架（有层级）→ 走 TreeRow
  const flatGroups = useMemo(() => buildFlatGroups(tree), [tree])

  // 层级树：默认选中根、只展开根（文档组默认收起，报告 §5.3.3）；平铺兜底不预选，等用户点叶子
  useEffect(() => {
    if (tree.length > 0 && selectedId == null) {
      if (flatGroups == null) {
        setSelectedId(tree[0]!.knowledge_node_id)
        setExpanded(new Set([tree[0]!.knowledge_node_id]))
      }
    }
  }, [tree, selectedId, flatGroups])

  const expandAll = () => {
    if (flatGroups != null) {
      setGroupOpen(new Set(flatGroups.map((g) => g.key)))
      setGroupShowAll(new Set(flatGroups.map((g) => g.key)))
      return
    }
    const ids = new Set<string>()
    const walk = (nodes: KnowledgeScoredTreeNode[]) => {
      for (const n of nodes) {
        if ((n.children ?? []).length > 0) {
          ids.add(n.knowledge_node_id)
          walk(n.children ?? [])
        }
      }
    }
    walk(tree)
    setExpanded(ids)
    setExpandedFull(new Set(ids))
  }

  const collapseAll = () => {
    setGroupOpen(new Set())
    setGroupShowAll(new Set())
    setExpandedFull(new Set())
    if (flatGroups == null && tree.length > 0) {
      setExpanded(new Set([tree[0]!.knowledge_node_id]))
    } else {
      setExpanded(new Set())
    }
  }

  const toggleGroup = (key: string) =>
    setGroupOpen((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  const toggleFull = (id: string) =>
    setExpandedFull((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  if (notBuilt) {
    return (
      <div>
        <div className="mb-3">
          <h1 className="text-[22px] font-bold">知识框架</h1>
          <p className="mt-0.5 text-[13px] text-ink2">上传资料后构建，作为测验出题与掌握度统计的结构底座</p>
        </div>
        {buildError != null && (
          <div className="mb-3">
            <ErrorNotice error={buildError} />
          </div>
        )}
        {building && (
          <div className="mb-3 flex items-center gap-2.5 rounded-lg border border-accent/40 bg-accent-bg/60 px-4 py-2.5 text-[13px] text-ink">
            <span className="inline-block size-2 animate-pulse rounded-full bg-accent" />
            {buildJob.phase === 'retry_wait' ? '构建任务重试中…' : '框架构建中，完成后自动刷新…'}
            {buildJob.job && (
              <span className="text-ink3">
                （{jobStatusLabel(buildJob.job.status)} · 第 {buildJob.job.attempts} 次尝试）
              </span>
            )}
          </div>
        )}
        <EmptyState
          title="还没有知识框架"
          action={
            <button
              type="button"
              onClick={() => build.mutate()}
              disabled={build.isPending || building}
              className="rounded-md bg-accent px-3.5 py-1.5 text-[13px] font-medium text-white disabled:opacity-50"
            >
              {build.isPending || building ? '构建中…' : '构建知识框架'}
            </button>
          }
        >
          基于已解析的课件大纲生成层级知识树，每个节点挂原文出处。
        </EmptyState>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-3 flex items-end justify-between">
        <div>
          <h1 className="text-[22px] font-bold">知识框架</h1>
          <p className="mt-0.5 flex items-center gap-2 text-[13px] text-ink2">
            {framework.data && (
              <>
                <span>v{framework.data.version_number}</span>
                <span className="flex items-center gap-1.5">
                  <span className={`inline-block size-2 rounded-full ${meta!.dot}`} />
                  {meta!.label}
                </span>
                <span className="text-ink3">{leafCount} 个知识点</span>
              </>
            )}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setShowVersions((v) => !v)}
            className="rounded-md border border-border2 px-3 py-1.5 text-[13px] text-ink2 hover:text-ink"
          >
            版本列表
          </button>
          <button
            type="button"
            onClick={() => build.mutate()}
            disabled={build.isPending || building}
            className="rounded-md bg-accent px-3.5 py-1.5 text-[13px] font-medium text-white disabled:opacity-50"
          >
            重新构建
          </button>
        </div>
      </div>

      {buildError != null && (
        <div className="mb-3">
          <ErrorNotice error={buildError} />
        </div>
      )}

      {building && (
        <div className="mb-3 flex items-center gap-2.5 rounded-lg border border-accent/40 bg-accent-bg/60 px-4 py-2.5 text-[13px] text-ink">
          <span className="inline-block size-2 animate-pulse rounded-full bg-accent" />
          {buildJob.phase === 'retry_wait' ? '构建任务重试中…' : '框架构建中，完成后自动刷新…'}
          {buildJob.job && (
            <span className="text-ink3">
              （{jobStatusLabel(buildJob.job.status)} · 第 {buildJob.job.attempts} 次尝试）
            </span>
          )}
        </div>
      )}

      {buildJob.phase === 'timeout' && (
        <div className="mb-3 rounded-md border border-warning-border bg-warning-bg px-4 py-2 text-[13px] text-ink">
          构建仍在处理（已超过 5 分钟），稍后回来刷新查看；也可点「重新构建」。
        </div>
      )}

      {framework.data?.status === 'failed' && (
        <div className="mb-3">
          <ErrorNotice
            error={new ApiError(500, buildJob.job?.error_code ?? 'LLM_REQUEST_FAILED', '框架构建失败')}
          />
        </div>
      )}

      {otherError != null && <ErrorNotice error={otherError} />}
      {framework.isLoading && <p className="text-[13px] text-ink3">加载中…</p>}

      <div className="mb-4 flex gap-1 border-b border-border" role="tablist" aria-label="知识视图">
        {(
          [
            ['tree', '章节树'],
            ['highlights', '重难点'],
            ['graph', '关系图'],
            ['merge', '整合记录'],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={view === value}
            onClick={() => setView(value)}
            className={`-mb-px border-b-2 px-3 py-2 text-[13px] ${
              view === value
                ? 'border-accent font-medium text-accent'
                : 'border-transparent text-ink2 hover:text-ink'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {view === 'highlights' && courseId && (
        <HighlightsPanel
          courseId={courseId}
          onPick={(id) => {
            setView('tree')
            setSelectedId(id)
            const path = findPath(tree, id)
            if (path) setExpanded((prev) => new Set([...prev, ...path]))
          }}
        />
      )}
      {view === 'graph' && courseId && (
        <GraphPanel
          courseId={courseId}
          onPick={(id) => {
            setView('tree')
            setSelectedId(id)
            const path = findPath(tree, id)
            if (path) setExpanded((prev) => new Set([...prev, ...path]))
          }}
        />
      )}
      {view === 'merge' && courseId && <MergePanel courseId={courseId} />}

      {view === 'tree' && tree.length > 0 && (
        <div className="grid grid-cols-[340px_1fr] gap-6">
          <section className="h-fit rounded-lg border border-border bg-surface" role="tree" aria-label="知识框架树">
            <div className="flex items-center gap-2 border-b border-border px-3 py-1.5">
              <span className="mr-auto text-[11.5px] text-ink3">
                {flatGroups != null ? `按资料分组 · ${flatGroups.length} 组` : '层级结构'}
              </span>
              <button
                type="button"
                onClick={expandAll}
                className="rounded border border-border2 px-2 py-0.5 text-[11.5px] text-ink2 hover:text-ink"
              >
                全部展开
              </button>
              <button
                type="button"
                onClick={collapseAll}
                className="rounded border border-border2 px-2 py-0.5 text-[11.5px] text-ink2 hover:text-ink"
              >
                全部收起
              </button>
            </div>
            {flatGroups != null ? (
              flatGroups.map((group) => (
                <FlatGroupBlock
                  key={group.key}
                  group={group}
                  open={groupOpen.has(group.key)}
                  showAll={groupShowAll.has(group.key)}
                  selectedId={selectedId}
                  mastery={masteryMap}
                  onToggle={() => toggleGroup(group.key)}
                  onShowAll={() => setGroupShowAll((prev) => new Set(prev).add(group.key))}
                  onSelect={setSelectedId}
                />
              ))
            ) : (
              tree.map((node) => (
                <TreeRow
                  key={node.knowledge_node_id}
                  node={node}
                  depth={0}
                  expanded={expanded}
                  fullIds={expandedFull}
                  selectedId={selectedId}
                  mastery={masteryMap}
                  onToggle={(id) =>
                    setExpanded((prev) => {
                      const next = new Set(prev)
                      if (next.has(id)) next.delete(id)
                      else next.add(id)
                      return next
                    })
                  }
                  onToggleFull={toggleFull}
                  onSelect={setSelectedId}
                />
              ))
            )}
            <p className="mt-2 border-t border-dashed border-border px-3 pt-2 text-[11.5px] leading-relaxed text-ink3">
              估计值 = 作答记录的统计推断；未测验 ≠ 薄弱。
            </p>
          </section>
          <section className="h-fit rounded-lg border border-border bg-surface px-5 py-4">
            {selectedId ? (
              selectedNode != null && (selectedNode.children ?? []).length > 0 ? (
                <>
                  <ContainerSummary node={selectedNode} mastery={masteryMap} onSelect={setSelectedId} />
                  <NodeDetail nodeId={selectedId} score={selectedNode} hideHeading />
                </>
              ) : (
                <NodeDetail nodeId={selectedId} score={selectedNode ?? undefined} />
              )
            ) : (
              <p className="text-[13px] text-ink3">在左侧选择一个知识点查看详情与出处。</p>
            )}
          </section>
        </div>
      )}

      {showVersions && (
        <section className="mt-6 overflow-hidden rounded-lg border border-border bg-surface">
          <div className="px-5 pb-2 pt-4">
            <h2 className="text-[15px] font-semibold">版本列表</h2>
          </div>
          {versions.isLoading && <p className="px-5 pb-4 text-[13px] text-ink3">加载中…</p>}
          {versions.isError && (
            <div className="px-5 pb-4">
              <ErrorNotice error={versions.error} />
            </div>
          )}
          {(versions.data ?? []).map((v) => {
            const vm = frameworkStatus(v.status)
            return (
              <div key={v.id} className="flex items-center gap-4 border-t border-border px-5 py-2.5 text-[13px]">
                <span className="w-16 flex-none font-mono">v{v.version_number}</span>
                <span className="flex flex-none items-center gap-1.5 text-ink2">
                  <span className={`inline-block size-2 rounded-full ${vm.dot}`} />
                  {vm.label}
                </span>
                <span className="flex-none text-ink3">创建 {v.created_at.slice(0, 16).replace('T', ' ')}</span>
                {v.activated_at && (
                  <span className="flex-none text-ink3">生效 {v.activated_at.slice(0, 16).replace('T', ' ')}</span>
                )}
              </div>
            )
          })}
        </section>
      )}
    </div>
  )
}


