// 总览：并行请求拼装（每张卡片独立 loading/error）；考试倒计时取 active 计划；
// 左栏「今日任务 + 最近薄弱点」与右栏「掌握度估计」点击联动（plan §4.5 修正项）
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  getCourse,
  getKnowledge,
  getPlan,
  listMaterials,
  listMastery,
  listPlans,
  getWrongbook,
  updateTask,
  type KnowledgeGap,
  type KnowledgeTreeNode,
  type StudyTask,
} from '../api/endpoints'
import { ApiError } from '../api/client'
import { gapTypeLabel, isTaskTerminal, taskStatus, taskTypeLabel } from '../api/status'
import { addDaysISO, daysUntil, formatDateCN, formatDateLong, todayISO } from '../lib/date'
import { collectLeaves } from '../lib/tree'
import { ErrorNotice } from '../components/ErrorNotice'
import { SkeletonRows } from '../components/Skeleton'
import { ChevronDown, ChevronUp } from '../components/icons'

/** 错题本证据摘要（与复习页同一口径：作答 5 · 低分 3 · 答对 2 · 最近得分 0.4） */
const EVIDENCE_LABELS: Record<string, string> = {
  total_evidence: '作答',
  low_score_evidence: '低分',
  positive_evidence: '答对',
  last_normalized_score: '最近得分',
}

function evidenceLine(gap: KnowledgeGap): string {
  const entries = Object.entries(gap.evidence_summary ?? {}).filter(([k]) => k !== 'last_attempt_id')
  return entries
    .map(([k, v]) => `${EVIDENCE_LABELS[k] ?? k} ${typeof v === 'number' ? v : String(v)}`)
    .join(' · ')
}

/** 任务目标的可读路径（后端 targets 只稳定返回 stable_key，标题需由知识树补） */
function knowledgePathMap(tree: KnowledgeTreeNode[]): Map<string, string> {
  const paths = new Map<string, string>()
  const walk = (nodes: KnowledgeTreeNode[], parents: string[]) => {
    for (const node of nodes) {
      const path = [...parents, node.title]
      paths.set(node.knowledge_node_id, path.join(' > '))
      if (node.children?.length) walk(node.children, path)
    }
  }
  walk(tree, [])
  return paths
}


// ---- 考试倒计时 ----

function CountdownCard({ courseId }: { courseId: string }) {
  const plans = useQuery({
    queryKey: ['plans', courseId],
    queryFn: () => listPlans(courseId),
  })
  const active = plans.data?.find((p) => p.status === 'active')
  // 与 TodayTasksCard 共用 ['plan', id] 缓存：不新增网络请求
  const detail = useQuery({
    queryKey: ['plan', active?.id],
    queryFn: () => getPlan(active!.id),
    enabled: active != null,
  })

  if (plans.isLoading) {
    return (
      <div className="rounded-lg border border-border bg-surface px-5 py-4 text-aux text-ink3">
        计划加载中…
      </div>
    )
  }
  if (plans.isError) return <ErrorNotice error={plans.error} />

  if (!active) {
    return (
      <div className="flex min-w-[280px] items-center gap-3.5 rounded-lg border border-border border-l-4 border-l-accent bg-surface px-5 py-3">
        <span className="text-display font-extrabold leading-none text-ink3">—</span>
        <p className="text-aux leading-snug text-ink2">
          还没有复习计划。
          <Link to={`/courses/${courseId}/plan`} className="text-accent">
            设置考试日并生成计划 →
          </Link>
        </p>
      </div>
    )
  }

  const days = daysUntil(active.exam_date)
  const today = todayISO()
  const minutesByDate = new Map<string, number>()
  for (const task of detail.data?.tasks ?? []) {
    minutesByDate.set(
      task.scheduled_date,
      (minutesByDate.get(task.scheduled_date) ?? 0) + task.estimated_minutes,
    )
  }
  const band = Array.from({ length: 7 }, (_, offset) => {
    const iso = addDaysISO(today, offset)
    const minutes = minutesByDate.get(iso) ?? 0
    const pct =
      active.daily_minutes > 0
        ? Math.min(100, Math.round((minutes / active.daily_minutes) * 100))
        : 0
    return {
      iso,
      minutes,
      pct,
      over: active.daily_minutes > 0 && minutes > active.daily_minutes,
      isToday: iso === today,
      weekday: formatDateCN(iso).split('（')[1]?.replace('）', '') ?? '',
    }
  })

  return (
    <div
      className="min-w-[320px] rounded-lg border border-border border-l-4 border-l-accent bg-surface px-5 py-3"
      aria-label={`距考试还有 ${days} 天`}
    >
      <div className="flex items-center gap-3.5">
        <div className="text-display font-extrabold leading-none tracking-tight">
          {days}
          <small className="ml-0.5 text-title font-semibold">天</small>
        </div>
        <p className="text-aux leading-snug text-ink2">
          距考试{days === 0 ? '就是今天' : days > 0 ? `还有 ${days} 天` : '已过'}
          <br />
          {formatDateLong(active.exam_date)} · 每日{' '}
          <span className="font-mono tabular-nums">{active.daily_minutes}</span> 分钟 · 目标{' '}
          <span className="font-mono tabular-nums">{active.target_score}</span> 分
        </p>
      </div>
      {detail.data && (
        <div className="mt-3 border-t border-border pt-2" data-testid="plan-band">
          <p className="mb-1.5 text-meta text-ink3">
            未来 7 天每日投入（分钟）· 上限{' '}
            <span className="font-mono tabular-nums">{active.daily_minutes}</span>/天
          </p>
          <div className="grid grid-cols-7 gap-1">
            {band.map((d) => (
              <div
                key={d.iso}
                className={`flex flex-col items-center gap-1 rounded-sm ${
                  d.isToday ? 'ring-1 ring-accent' : ''
                }`}
                data-testid="plan-band-day"
              >
                <div className="relative h-6 w-full overflow-hidden rounded-sm bg-untested-bg">
                  <div
                    data-testid="plan-band-fill"
                    className={`absolute bottom-0 w-full ${d.over ? 'bg-error' : 'bg-accent'}`}
                    style={{ height: `${d.pct}%` }}
                  />
                </div>
                <span className={`text-micro ${d.isToday ? 'text-accent' : 'text-ink3'}`}>
                  {d.isToday ? '今天' : d.weekday}
                </span>
                <span className="font-mono text-micro tabular-nums text-ink3">{d.minutes}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ---- 今日任务 ----

function TodayTasksCard({
  courseId,
  labels,
}: {
  courseId: string
  labels: Map<string, string>
}) {
  const queryClient = useQueryClient()
  const [transitionError, setTransitionError] = useState<unknown>(null)
  const plans = useQuery({
    queryKey: ['plans', courseId],
    queryFn: () => listPlans(courseId),
  })
  const active = plans.data?.find((p) => p.status === 'active')
  const detail = useQuery({
    queryKey: ['plan', active?.id],
    queryFn: () => getPlan(active!.id),
    enabled: active != null,
  })

  const transition = useMutation({
    mutationFn: ({ taskId }: { taskId: string }) => updateTask(taskId, { status: 'completed' }),
    onSuccess: () => {
      setTransitionError(null)
      void queryClient.invalidateQueries({ queryKey: ['plan', active?.id] })
    },
    onError: (err) => setTransitionError(err),
  })

  const today = todayISO()
  const tasks: StudyTask[] = (detail.data?.tasks ?? []).filter((t) => t.scheduled_date === today)
  const totalMinutes = tasks.reduce((sum, t) => sum + t.estimated_minutes, 0)
  const doneCount = tasks.filter((t) => t.status === 'completed').length

  return (
    <section className="overflow-hidden rounded-lg border border-border bg-surface">
      <div className="flex items-baseline gap-3 px-5 pb-2 pt-4">
        <h2 className="text-title font-semibold">今日任务</h2>
        <span className="text-aux text-ink2">
          {formatDateCN(today)} · 合计 <span className="font-mono tabular-nums">{totalMinutes}</span>{' '}
          分钟 · 已完成 <span className="font-mono tabular-nums">{doneCount}</span> 项
        </span>
        <Link
          to={`/courses/${courseId}/plan`}
          className="ml-auto flex-none text-aux text-accent"
        >
          查看复习计划 →
        </Link>
      </div>

      {transitionError != null && (
        <div className="border-t border-border px-5 py-2" aria-live="polite">
          <ErrorNotice error={transitionError} />
        </div>
      )}

      {detail.isError && (
        <div className="border-t border-border px-5 py-2">
          <ErrorNotice error={detail.error} />
        </div>
      )}

      {detail.isLoading && <SkeletonRows rows={2} className="border-t border-border px-5 py-3.5" />}

      {!detail.isLoading && tasks.length === 0 && (
        <p className="border-t border-border px-5 py-4 text-aux text-ink3">
          {active == null
            ? '还没有复习计划，今天没有安排任务。'
            : '今天没有安排任务。'}
          <Link to={`/courses/${courseId}/plan`} className="ml-1 text-accent">
            查看计划 →
          </Link>
        </p>
      )}

      {tasks.map((task) => {
        const meta = taskStatus(task.status)
        const terminal = isTaskTerminal(task.status)
        const done = task.status === 'completed'
        const go =
          task.status === 'in_progress' ? '继续' : task.status === 'pending' ? '开始' : null
        const targetNode = task.targets[0]
        const target = targetNode
          ? labels.get(targetNode.knowledge_node_id) ??
            targetNode.title ??
            targetNode.knowledge_node_id
          : undefined
        return (
          <div
            key={task.id}
            data-task-id={task.id}
            className={`flex animate-fade-in items-center gap-3 border-t border-border px-5 py-2.5 ${ task.status === 'in_progress' ? 'bg-accent-bg/40 shadow-[inset_3px_0_0_var(--color-accent)]' : 'row-hover' }`}
          >
            <input
              type="checkbox"
              checked={done}
              disabled={terminal || transition.isPending}
              onChange={() => transition.mutate({ taskId: task.id })}
              aria-label={`完成 ${task.title}`}
              title={terminal ? '终态任务不可修改' : undefined}
              className="size-4 flex-none accent-[#1A7F37]"
            />
            <div className="min-w-0 flex-1">
              <div
                className={`truncate text-body font-semibold ${done ? 'font-normal text-ink3' : ''}`}
                title={task.title}
              >
                {task.title}
              </div>
              <div className="mt-0.5 truncate text-meta text-ink3" title={target}>
                {taskTypeLabel(task.task_type)}
                {target ? ` · ${target}` : ''}
              </div>
            </div>
            <span className="w-14 flex-none text-right font-mono text-aux text-ink2">
              {task.estimated_minutes} 分钟
            </span>
            <span
              className={`flex-none rounded px-2 py-0.5 text-meta ${ task.status === 'in_progress' ? 'bg-accent-bg text-accent' : done ? 'bg-success-bg text-success' : 'bg-untested-bg text-ink3' }`}
            >
              {meta.label}
            </span>
            {go && (
              <Link
                to={`/courses/${courseId}/${task.task_type === 'practice' ? 'quiz' : 'review'}`}
                className="ml-1 flex-none text-aux text-accent"
              >
                {go}
              </Link>
            )}
          </div>
        )
      })}
    </section>
  )
}

// ---- 最近薄弱点（点击 → 联动右栏掌握度行）----

function WeakPointsCard({
  courseId,
  masteryByNode,
  onFocus,
}: {
  courseId: string
  masteryByNode: Map<string, { title: string | null; mastery_estimate: number; evidence_count: number }>
  onFocus: (nodeId: string | null) => void
}) {
  const wrongbook = useQuery({
    queryKey: ['wrongbook', courseId],
    queryFn: () => getWrongbook(courseId),
  })
  const gaps: KnowledgeGap[] = wrongbook.data?.slice(0, 3) ?? []

  return (
    <section className="overflow-hidden rounded-lg border border-border bg-surface">
      <div className="flex items-baseline gap-3 px-5 pb-2 pt-4">
        <h2 className="text-title font-semibold">最近薄弱点</h2>
        <span className="text-aux text-ink3">由测验记录得出，非自评</span>
        <Link to={`/courses/${courseId}/review`} className="ml-auto text-aux text-accent">
          查看复习 / 错题本 →
        </Link>
      </div>
      {wrongbook.isLoading && (
        <SkeletonRows rows={3} className="border-t border-border px-5 py-3.5" />
      )}
      {wrongbook.isError && (
        <div className="border-t border-border px-5 py-2">
          <ErrorNotice error={wrongbook.error} />
        </div>
      )}
      {wrongbook.data && gaps.length === 0 && (
        <p className="border-t border-border px-5 py-4 text-aux text-ink3">
          暂无薄弱点记录 —— 提交测验后，这里会列出最近答错的知识点。
        </p>
      )}
      {gaps.map((gap) => {
        const m = masteryByNode.get(gap.knowledge_node_id)
        return (
          <button
            key={`${gap.knowledge_node_id}-${gap.gap_type}`}
            type="button"
            onClick={() => onFocus(gap.knowledge_node_id)}
            className="block w-full animate-fade-in border-t border-border px-5 py-2.5 text-left row-hover"
          >
            <div className="flex min-w-0 items-baseline gap-2.5">
              <span
                className="min-w-0 break-words text-body font-semibold"
                title={gap.title ?? gap.knowledge_node_id}
              >
                {gap.title ?? gap.knowledge_node_id}
              </span>
              <span className="flex-none text-aux text-ink2">
                {m ? (
                  <>
                    估计 <b className="font-mono tabular-nums text-ink">{m.mastery_estimate.toFixed(2)}</b>{' '}
                    · 依据 <span className="font-mono tabular-nums">{m.evidence_count}</span> 次作答
                  </>
                ) : (
                  '暂无掌握度记录'
                )}
              </span>
            </div>
            <p className="mt-0.5 line-clamp-2 text-aux leading-snug text-ink2">
              {gapTypeLabel(gap.gap_type)}
              {evidenceLine(gap) ? ` · ${evidenceLine(gap)}` : ''}
            </p>
          </button>
        )
      })}
    </section>
  )
}

// ---- 掌握度估计（右栏；可被左栏薄弱点联动高亮）----

/** 已测验行默认显示条数（长列表渐进展开，与资料搜索同款模式） */
const TESTED_LIMIT = 10

function MasteryCard({
  courseId,
  frameworkNotBuilt,
  focusNodeId,
  onFocus,
}: {
  courseId: string
  frameworkNotBuilt: boolean
  focusNodeId: string | null
  onFocus: (nodeId: string | null) => void
}) {
  const mastery = useQuery({
    queryKey: ['mastery', courseId],
    queryFn: () => listMastery(courseId),
  })
  const knowledge = useQuery({
    queryKey: ['knowledge', courseId],
    queryFn: () => getKnowledge(courseId),
    retry: false,
  })
  const rowRefs = useRef(new Map<string, HTMLButtonElement>())
  // 长列表收敛（与资料搜索同款渐进展开）：已测验默认前 10 条，未测验默认折叠成计数行
  const [showAllTested, setShowAllTested] = useState(false)
  const [showUntested, setShowUntested] = useState(false)

  const leaves = collectLeaves(knowledge.data?.tree ?? [])
  const masteryByNode = new Map((mastery.data ?? []).map((m) => [m.knowledge_node_id, m]))
  const testedRows = (mastery.data ?? [])
    .slice()
    .sort((a, b) => a.mastery_estimate - b.mastery_estimate)
  const untestedLeaves = leaves.filter((l) => !masteryByNode.has(l.knowledge_node_id))
  const testedVisible = showAllTested ? testedRows : testedRows.slice(0, TESTED_LIMIT)
  const hiddenTested = testedRows.length - testedVisible.length

  // 联动目标行若在折叠区，先展开——展开触发的重渲染之后，滚动 effect 才能定位到行。
  // 数据就绪信号必须进依赖：薄弱点（wrongbook）常先于 mastery/knowledge 到达，
  // 若数据到达后不重算，首屏窗口期的点击会静默失效（focusNodeId 不变则 effect 不重跑）。
  useEffect(() => {
    if (!focusNodeId) return
    if (untestedLeaves.some((l) => l.knowledge_node_id === focusNodeId)) setShowUntested(true)
    if (testedRows.findIndex((m) => m.knowledge_node_id === focusNodeId) >= TESTED_LIMIT) {
      setShowAllTested(true)
    }
    // 列表数组是渲染派生值（身份不稳定），用 dataUpdatedAt 作为数据就绪信号
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusNodeId, mastery.dataUpdatedAt, knowledge.dataUpdatedAt])

  useEffect(() => {
    if (focusNodeId) {
      // jsdom 未实现 scrollIntoView，用可选调用兜底
      rowRefs.current.get(focusNodeId)?.scrollIntoView?.({ block: 'nearest' })
    }
  }, [focusNodeId, showAllTested, showUntested, mastery.dataUpdatedAt, knowledge.dataUpdatedAt])

  return (
    <section className="min-w-0 overflow-hidden rounded-lg border border-border bg-surface">
      <div className="flex items-baseline gap-3 px-5 pb-1.5 pt-4">
        <h2 className="text-title font-semibold">掌握度估计</h2>
        <span className="text-aux text-ink3">已测验按估计值升序</span>
      </div>

      {mastery.isLoading && (
        <SkeletonRows rows={4} className="border-t border-border px-5 py-3.5" />
      )}
      {mastery.isError && (
        <div className="border-t border-border px-5 py-2">
          <ErrorNotice error={mastery.error} />
        </div>
      )}

      {(mastery.data != null || knowledge.data != null) && (
        <div className="animate-fade-in px-5 pb-3 pt-1.5">
          {testedVisible.map((m) => {
            const focused = focusNodeId === m.knowledge_node_id
            return (
              <button
                key={m.knowledge_node_id}
                type="button"
                ref={(el) => {
                  if (el) rowRefs.current.set(m.knowledge_node_id, el)
                  else rowRefs.current.delete(m.knowledge_node_id)
                }}
                onClick={() => onFocus(focused ? null : m.knowledge_node_id)}
                aria-pressed={focused}
                className={`grid w-full animate-fade-in grid-cols-[116px_1fr_136px] items-center gap-2.5 rounded px-1 py-1.5 text-left ${ focused ? 'bg-accent-bg' : 'row-hover' }`}
              >
                <span className="truncate text-right text-aux">{m.title ?? m.knowledge_node_id}</span>
                <span className="relative h-3 overflow-hidden rounded-sm bg-untested-bg">
                  <span
                    className="absolute inset-y-0 left-0 rounded-sm bg-accent"
                    style={{ width: `${Math.round(m.mastery_estimate * 100)}%` }}
                  />
                  <span className="absolute inset-y-0 left-1/2 w-px bg-border2" />
                </span>
                <span className="whitespace-nowrap text-right font-mono text-meta text-ink2 tabular-nums">
                  估计 {m.mastery_estimate.toFixed(2)} · {m.evidence_count} 次
                </span>
              </button>
            )
          })}
          {hiddenTested > 0 && (
            <button
              type="button"
              onClick={() => setShowAllTested((v) => !v)}
              className="w-full rounded px-1 py-1.5 text-left text-aux text-accent row-hover"
            >
              {showAllTested ? (
                <>
                  收起 <ChevronUp className="ml-1 inline size-4 align-[-3px]" />
                </>
              ) : (
                <>
                  展开其余 <span className="font-mono tabular-nums">{hiddenTested}</span> 条已测验
                  <ChevronDown className="ml-1 inline size-4 align-[-3px]" />
                </>
              )}
            </button>
          )}
          {untestedLeaves.length > 0 && (
            <button
              type="button"
              onClick={() => setShowUntested((v) => !v)}
              aria-expanded={showUntested}
              className="w-full rounded px-1 py-1.5 text-left text-aux text-ink3 row-hover"
            >
              {showUntested ? (
                <>
                  收起未测验 <ChevronUp className="ml-1 inline size-4 align-[-3px]" />
                </>
              ) : (
                <>
                  未测验 <span className="font-mono tabular-nums">{untestedLeaves.length}</span>{' '}
                  个（不代表薄弱）· 展开
                  <ChevronDown className="ml-1 inline size-4 align-[-3px]" />
                </>
              )}
            </button>
          )}
          {showUntested &&
            untestedLeaves.map((leaf) => {
            const focused = focusNodeId === leaf.knowledge_node_id
            return (
              <button
                key={leaf.knowledge_node_id}
                type="button"
                ref={(el) => {
                  if (el) rowRefs.current.set(leaf.knowledge_node_id, el)
                  else rowRefs.current.delete(leaf.knowledge_node_id)
                }}
                onClick={() => onFocus(focused ? null : leaf.knowledge_node_id)}
                aria-pressed={focused}
                className={`grid w-full animate-fade-in grid-cols-[116px_1fr_136px] items-center gap-2.5 rounded px-1 py-1.5 text-left text-ink3 ${ focused ? 'bg-accent-bg' : 'row-hover' }`}
              >
                <span className="truncate text-right text-aux">{leaf.title}</span>
                <span className="h-3 rounded-sm bg-untested-bg" />
                <span className="whitespace-nowrap text-meta">未测验</span>
              </button>
            )
          })}
        </div>
      )}

      <p className="border-t border-dashed border-border px-5 py-3 text-meta leading-relaxed text-ink3">
        估计是系统根据<b className="font-semibold text-ink2">作答记录</b>做出的推断，不是精确测量，会随新作答变化。
        <br />
        <b className="font-semibold text-ink2">未测验</b>表示尚无作答记录，不代表薄弱。
        {frameworkNotBuilt ? (
          <> 知识框架未构建，无法对比未测验知识点，<Link to={`/courses/${courseId}/knowledge`} className="text-accent">去构建 →</Link></>
        ) : (
          <>
            {' '}
            <Link to={`/courses/${courseId}/knowledge`} className="text-accent">
              在知识框架中查看全部知识点 →
            </Link>
          </>
        )}
      </p>
    </section>
  )
}

// ---- 页面 ----

export function DashboardPage() {
  const { courseId } = useParams()
  const [focusNodeId, setFocusNodeId] = useState<string | null>(null)

  const course = useQuery({
    queryKey: ['course', courseId],
    queryFn: () => getCourse(courseId!),
    enabled: courseId !== undefined,
  })
  const materials = useQuery({
    queryKey: ['materials', courseId],
    queryFn: () => listMaterials(courseId!),
    enabled: courseId !== undefined,
  })
  const knowledge = useQuery({
    queryKey: ['knowledge', courseId],
    queryFn: () => getKnowledge(courseId!),
    enabled: courseId !== undefined,
    retry: false,
  })
  const mastery = useQuery({
    queryKey: ['mastery', courseId],
    queryFn: () => listMastery(courseId!),
    enabled: courseId !== undefined,
  })
  const plans = useQuery({
    queryKey: ['plans', courseId],
    queryFn: () => listPlans(courseId!),
    enabled: courseId !== undefined,
  })

  const frameworkNotBuilt =
    knowledge.isError &&
    knowledge.error instanceof ApiError &&
    knowledge.error.code === 'RESOURCE_NOT_FOUND'
  const activePlan = plans.data?.find((p) => p.status === 'active')
  const leafCount = useMemo(
    () => collectLeaves(knowledge.data?.tree ?? []).length,
    [knowledge.data],
  )
  const pathLabels = useMemo(
    () => knowledgePathMap(knowledge.data?.tree ?? []),
    [knowledge.data],
  )

  // 头部一行摘要：各段独立降级（数据没到就跳过该段）
  const segments: string[] = []
  if (materials.data) segments.push(`${materials.data.length} 份资料`)
  if (knowledge.data) {
    segments.push(
      `知识框架 v${knowledge.data.version_number}（${leafCount} 个知识点）`,
    )
  } else if (frameworkNotBuilt) {
    segments.push('知识框架未构建')
  }
  segments.push(
    activePlan ? `复习计划：每日 ${activePlan.daily_minutes} 分钟，进行中` : '还没有复习计划',
  )

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-page font-semibold">{course.data?.name ?? '…'}</h1>
          <p className="mt-1 text-aux text-ink2">{segments.join(' · ')}</p>
        </div>
        <CountdownCard courseId={courseId!} />
      </div>

      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_424px] items-start gap-6">
        <div className="flex min-w-0 flex-col gap-4">
          <TodayTasksCard courseId={courseId!} labels={pathLabels} />
          <WeakPointsCard
            courseId={courseId!}
            masteryByNode={new Map(
              (mastery.data ?? []).map((m) => [
                m.knowledge_node_id,
                { title: m.title, mastery_estimate: m.mastery_estimate, evidence_count: m.evidence_count },
              ]),
            )}
            onFocus={setFocusNodeId}
          />
        </div>
        <MasteryCard
          courseId={courseId!}
          frameworkNotBuilt={frameworkNotBuilt}
          focusNodeId={focusNodeId}
          onFocus={setFocusNodeId}
        />
      </div>
    </div>
  )
}
