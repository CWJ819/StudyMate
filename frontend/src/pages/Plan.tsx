// 复习计划：生成（同步 201，无 job）、版本列表、任务按天分组（合计分钟数 ≤ 每日上限）、
// 任务状态迁移 pending → in_progress → completed/skipped；终态与非 active 计划只读
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  createPlan,
  getKnowledge,
  getPlan,
  listPlans,
  updateTask,
  type StudyPlanDetail,
  type StudyPlanSummary,
  type StudyTask,
  type KnowledgeTreeNode,
} from '../api/endpoints'
import { ApiError } from '../api/client'
import {
  isTaskTerminal,
  planStatus,
  taskStatus,
  taskTransitionLabel,
  taskTransitions,
  taskTypeLabel,
} from '../api/status'
import { addDaysISO, daysUntil, formatDateCN, todayISO } from '../lib/date'
import { collectLeaves } from '../lib/tree'
import { EmptyState } from '../components/EmptyState'
import { ErrorNotice } from '../components/ErrorNotice'

// ---- 生成表单 ----

// 后端每叶按正文长度估 8–12 分钟；这里用 12 分钟做预算，并留 15% 缓冲。
// 目标分越高，默认覆盖范围越接近预算上限（60 分约 60%，85 分以上用满预算）。
function suggestedLeafCount(
  leafCount: number,
  examDate: string,
  dailyMinutes: number,
  targetScore: number,
): number {
  if (leafCount <= 0) return 0
  const days = examDate ? Math.max(1, daysUntil(examDate) + 1) : 14
  const budget = days * dailyMinutes * 0.85
  const scoreFactor = targetScore >= 85 ? 1 : targetScore >= 60 ? 0.8 : 0.6
  const count = Math.floor((budget * scoreFactor) / 12)
  return Math.max(1, Math.min(leafCount, count))
}

function suggestedLeafIds(
  leaves: KnowledgeTreeNode[],
  examDate: string,
  dailyMinutes: number,
  targetScore: number,
): string[] {
  const count = suggestedLeafCount(leaves.length, examDate, dailyMinutes, targetScore)
  // 非全选时后端最多接受 100 个 id；超出时先取前 100 个，可手动调整。
  const limit = count >= leaves.length ? leaves.length : Math.min(count, 100)
  return leaves.slice(0, limit).map((leaf) => leaf.knowledge_node_id)
}

function knowledgePathMap(tree: KnowledgeTreeNode[]): Map<string, string> {
  const paths = new Map<string, string>()
  const walk = (nodes: KnowledgeTreeNode[], prefix: string) => {
    for (const node of nodes) {
      const path = prefix ? `${prefix} > ${node.title}` : node.title
      paths.set(node.knowledge_node_id, path)
      if (node.children?.length) walk(node.children, path)
    }
  }
  walk(tree, '')
  return paths
}

function GenerateForm({
  courseId,
  leaves,
  onCreated,
  onCancel,
}: {
  courseId: string
  leaves: KnowledgeTreeNode[]
  onCreated: (planId: string) => void
  onCancel?: () => void
}) {
  const [examDate, setExamDate] = useState(() => addDaysISO(todayISO(), 14))
  const [dailyMinutes, setDailyMinutes] = useState(60)
  const [targetScore, setTargetScore] = useState(85)
  const [selected, setSelected] = useState<Set<string>>(
    () =>
      new Set(
        suggestedLeafIds(leaves, addDaysISO(todayISO(), 14), 60, 85),
      ),
  )
  const [formError, setFormError] = useState<string | null>(null)
  const didInitSelection = useRef(false)

  // 知识框架异步到达时补一次默认选择（之后尊重用户手动改动，不再覆盖）。
  useEffect(() => {
    if (!didInitSelection.current && leaves.length > 0 && selected.size === 0) {
      didInitSelection.current = true
      setSelected(new Set(suggestedLeafIds(leaves, examDate, dailyMinutes, targetScore)))
    }
  }, [leaves, selected.size, examDate, dailyMinutes, targetScore])

  const suggestedIds = useMemo(
    () => suggestedLeafIds(leaves, examDate, dailyMinutes, targetScore),
    [leaves, examDate, dailyMinutes, targetScore],
  )
  const suggestedCount = suggestedIds.length
  const estimatedMin = selected.size * 8
  const estimatedMax = selected.size * 12

  const generate = useMutation({
    mutationFn: () =>
      createPlan(courseId, {
        exam_date: examDate,
        daily_minutes: dailyMinutes,
        target_score: targetScore,
        // 全选时省略字段（后端缺省=全部叶子）：契约上限 100 个 id
        knowledge_node_ids:
          selected.size === leaves.length ? undefined : Array.from(selected),
      }),
    onSuccess: (plan) => onCreated(plan.id),
    onError: (err) => setFormError(err instanceof ApiError ? err.displayMessage : String(err)),
  })

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setFormError(null)
    if (!examDate) {
      setFormError('请选择考试日期')
      return
    }
    if (examDate < todayISO()) {
      setFormError('考试日期不能早于今天')
      return
    }
    if (!Number.isInteger(dailyMinutes) || dailyMinutes < 15 || dailyMinutes > 720) {
      setFormError('每日分钟数需在 15–720 之间')
      return
    }
    if (!Number.isInteger(targetScore) || targetScore < 0 || targetScore > 100) {
      setFormError('目标分数需在 0–100 之间')
      return
    }
    if (selected.size === 0) {
      setFormError('请至少选择一个知识点')
      return
    }
    if (selected.size < leaves.length && selected.size > 100) {
      setFormError(`复习范围最多选 100 个知识点（当前 ${selected.size} 个），请缩小范围`)
      return
    }
    generate.mutate()
  }

  // 容量不足时后端会给出需要/可用分钟数（details），值得直接呈现
  const capacityDetails =
    generate.error instanceof ApiError &&
    generate.error.code === 'PLAN_CAPACITY_EXCEEDED' &&
    generate.error.details &&
    typeof generate.error.details === 'object'
      ? (generate.error.details as {
          required_minutes?: number
          available_minutes?: number
        })
      : null
  const capacityHint =
    capacityDetails &&
    typeof capacityDetails.required_minutes === 'number' &&
    typeof capacityDetails.available_minutes === 'number'
      ? `到考前共需 ${capacityDetails.required_minutes} 分钟，可用 ${capacityDetails.available_minutes} 分钟`
      : null

  return (
    <form onSubmit={submit} className="min-w-0 rounded-lg border border-border bg-surface">
      <div className="flex items-baseline gap-3 px-5 pb-2 pt-4">
        <h2 className="text-[15px] font-semibold">生成新计划</h2>
        <span className="text-[12.5px] text-ink3">生成后旧版本自动停用</span>
      </div>
      <div className="space-y-3 border-t border-border px-5 py-4">
        <label className="block">
          <span className="mb-1 block text-[13px] text-ink2">考试日期</span>
          <input
            type="date"
            value={examDate}
            min={todayISO()}
            onChange={(e) => setExamDate(e.target.value)}
            className="h-[34px] w-full rounded-md border border-border2 bg-bg px-2.5 text-[13px] text-ink"
          />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="block min-w-0">
            <span className="mb-1 block text-[13px] text-ink2">每日分钟数（15–720）</span>
            <input
              type="number"
              value={dailyMinutes}
              min={15}
              max={720}
              onChange={(e) => setDailyMinutes(Number(e.target.value))}
              className="h-[34px] w-full rounded-md border border-border2 bg-bg px-2.5 text-[13px] text-ink"
            />
          </label>
          <label className="block min-w-0">
            <span className="mb-1 block text-[13px] text-ink2">目标分数（0–100）</span>
            <input
              type="number"
              value={targetScore}
              min={0}
              max={100}
              onChange={(e) => setTargetScore(Number(e.target.value))}
              className="h-[34px] w-full rounded-md border border-border2 bg-bg px-2.5 text-[13px] text-ink"
            />
          </label>
        </div>
        {/* fieldset 默认 min-inline-size: min-content，不压成 0 会被最长标题撑破卡片 */}
        <fieldset className="min-w-0">
          <legend className="mb-1.5 text-[13px] text-ink2">
            复习范围（叶子节点，共 {leaves.length} 个）
          </legend>
          <div className="mb-2 flex flex-wrap items-center gap-2 text-[12px] text-ink3">
            <span>
              已选 {selected.size} 个 · 按 8–12 分钟/叶估算约 {estimatedMin}–{estimatedMax} 分钟
            </span>
            <button
              type="button"
              onClick={() => setSelected(new Set(suggestedIds))}
              className="rounded border border-border2 bg-surface px-2 py-0.5 text-[12px] text-accent hover:border-accent"
            >
              按时间预算选 {suggestedCount} 个
            </button>
            <button
              type="button"
              onClick={() => setSelected(new Set(leaves.map((l) => l.knowledge_node_id)))}
              className="rounded border border-border2 bg-surface px-2 py-0.5 text-[12px] text-ink2 hover:text-ink"
            >
              全选
            </button>
          </div>
          <div className="max-h-40 space-y-1 overflow-y-auto rounded-md border border-border bg-bg p-2.5">
            {leaves.map((leaf) => (
              <label
                key={leaf.knowledge_node_id}
                className="flex min-w-0 items-center gap-2 text-[13px]"
              >
                <input
                  type="checkbox"
                  checked={selected.has(leaf.knowledge_node_id)}
                  onChange={() => {
                    const next = new Set(selected)
                    if (next.has(leaf.knowledge_node_id)) next.delete(leaf.knowledge_node_id)
                    else next.add(leaf.knowledge_node_id)
                    setSelected(next)
                  }}
                  className="flex-none"
                />
                <span className="min-w-0 flex-1 truncate" title={leaf.title}>
                  {leaf.title}
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        {(formError || generate.isError) && (
          <div role="alert" className="rounded-md border border-error/40 bg-error-bg px-3 py-2 text-[13px]">
            {formError ?? (generate.error instanceof ApiError ? generate.error.displayMessage : String(generate.error))}
            {capacityHint && <p className="mt-1 text-ink2">{capacityHint}</p>}
          </div>
        )}
        <div className="flex items-center gap-2">
          <button
            type="submit"
            disabled={generate.isPending}
            className="rounded-md bg-accent px-3.5 py-1.5 text-[13px] font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {generate.isPending ? '生成中…' : '生成计划'}
          </button>
          {onCancel && (
            <button
              type="button"
              onClick={onCancel}
              className="rounded-md border border-border2 bg-surface px-3 py-1.5 text-[13px] text-ink2 hover:text-ink"
            >
              收起
            </button>
          )}
        </div>
      </div>
    </form>
  )
}

// ---- 版本列表 ----

function VersionList({
  plans,
  selectedId,
  onSelect,
}: {
  plans: StudyPlanSummary[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  return (
    <section className="overflow-hidden rounded-lg border border-border bg-surface">
      <div className="px-5 pb-2 pt-4 text-[15px] font-semibold">历史版本</div>
      {plans.map((p) => {
        const meta = planStatus(p.status)
        return (
          <button
            key={p.id}
            type="button"
            onClick={() => onSelect(p.id)}
            aria-current={p.id === selectedId}
            className={`block w-full border-t border-border px-5 py-2.5 text-left hover:bg-bg ${
              p.id === selectedId ? 'bg-accent-bg/60' : ''
            }`}
          >
            <div className="flex items-center gap-2 text-[13.5px]">
              <span className="font-semibold">
                v{p.version_number}
                {p.status === 'active' && <span className="ml-1.5 text-[11.5px] font-normal text-success">进行中</span>}
              </span>
              <span className="ml-auto font-mono text-xs text-ink2">{p.exam_date}</span>
            </div>
            <div className="mt-0.5 text-[12px] text-ink3">
              每日 {p.daily_minutes} 分钟 · {p.task_count} 项任务 · {meta.label}
            </div>
          </button>
        )
      })}
    </section>
  )
}

// ---- 任务行 ----

function TaskRow({
  task,
  labels,
  readonly,
  onTransition,
  busy,
}: {
  task: StudyTask
  labels: Map<string, string>
  readonly: boolean
  onTransition: (taskId: string, to: string) => void
  busy: boolean
}) {
  const meta = taskStatus(task.status)
  const terminal = isTaskTerminal(task.status)
  const done = task.status === 'completed'
  const targetNames = task.targets
    .map((target) => {
      const fromTree = labels.get(target.knowledge_node_id)
      if (fromTree) return fromTree
      if (target.title && !target.title.startsWith('v1:')) return target.title
      return target.knowledge_node_id
    })
    .join('、')
  return (
    <div
      data-task-id={task.id}
      className={`flex items-center gap-3 border-t border-border px-5 py-2.5 ${
        task.status === 'in_progress' ? 'bg-accent-bg/40' : ''
      }`}
    >
      <input
        type="checkbox"
        checked={done}
        disabled={readonly || terminal || busy}
        onChange={() => onTransition(task.id, 'completed')}
        aria-label={`完成 ${task.title}`}
        title={terminal ? '终态任务不可修改' : undefined}
        className="size-4 flex-none accent-[#1A7F37]"
      />
      <div className="min-w-0 flex-1">
        <div
          className={`truncate text-[14px] font-semibold ${done ? 'font-normal text-ink3' : ''}`}
          title={task.title}
        >
          {task.title}
        </div>
        <div className="mt-0.5 truncate text-[12px] text-ink3" title={targetNames}>
          {taskTypeLabel(task.task_type)}
          {targetNames ? ` · ${targetNames}` : ''}
        </div>
      </div>
      <span className="w-14 flex-none text-right font-mono text-[12.5px] text-ink2">
        {task.estimated_minutes} 分钟
      </span>
      <span className="flex-none rounded bg-bg px-2 py-0.5 text-[11.5px] text-ink2">
        {meta.label}
      </span>
      {!readonly &&
        taskTransitions(task.status).map((to) => (
          <button
            key={to}
            type="button"
            disabled={busy}
            onClick={() => onTransition(task.id, to)}
            className="flex-none rounded border border-border2 px-2 py-0.5 text-[12px] text-accent hover:border-accent disabled:opacity-50"
          >
            {taskTransitionLabel(to)}
          </button>
        ))}
    </div>
  )
}

// ---- 计划详情：头部 + 按天分组（合计分钟数与每日上限）----

function daysLabel(days: number): string {
  if (days > 0) return `距考试还有 ${days} 天`
  if (days === 0) return '今天考试'
  return '考试已过'
}

function PlanDetailCard({
  plan,
  labels,
  onTransition,
  busyTaskId,
}: {
  plan: StudyPlanDetail
  labels: Map<string, string>
  onTransition: (taskId: string, to: string) => void
  busyTaskId: string | null
}) {
  const readonly = plan.status !== 'active'
  const days = daysUntil(plan.exam_date)
  const doneCount = plan.tasks.filter((t) => t.status === 'completed').length

  const groups = useMemo(() => {
    const byDate = new Map<string, StudyTask[]>()
    for (const t of plan.tasks) {
      const list = byDate.get(t.scheduled_date) ?? []
      list.push(t)
      byDate.set(t.scheduled_date, list)
    }
    return Array.from(byDate.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, tasks]) => ({
        date,
        tasks,
        totalMinutes: tasks.reduce((sum, t) => sum + t.estimated_minutes, 0),
      }))
  }, [plan.tasks])

  return (
    <section className="overflow-hidden rounded-lg border border-border bg-surface">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-border px-5 pb-3 pt-4">
        <h2 className="text-[15px] font-semibold">v{plan.version_number} 计划</h2>
        <span
          className={`rounded px-2 py-0.5 text-[11.5px] ${
            readonly ? 'bg-bg text-ink3' : 'bg-success-bg text-success'
          }`}
        >
          {planStatus(plan.status).label}
        </span>
        <span className="text-[12.5px] text-ink2">
          考试日 <b className="font-mono">{plan.exam_date}</b> · {daysLabel(days)}
        </span>
        <span className="text-[12.5px] text-ink2">
          每日 {plan.daily_minutes} 分钟 · 目标 {plan.target_score} 分 · 已完成 {doneCount}/
          {plan.tasks.length} 项
        </span>
      </div>

      {readonly && (
        <p className="border-b border-border bg-bg px-5 py-2 text-[12.5px] text-ink3">
          此版本已停用（生成新版本后自动归档），仅供查看。
        </p>
      )}

      {groups.map(({ date, tasks, totalMinutes }) => {
        // 判色用未夹取的比值（超载日显红），设宽用夹取值
        const ratio = totalMinutes / plan.daily_minutes
        const pct = Math.min(100, ratio * 100)
        return (
          <div key={date} data-date-group={date}>
            <div className="flex items-baseline gap-3 border-t border-border px-5 pb-1.5 pt-3 first:border-t-0">
              <h3 className="text-[13.5px] font-semibold">
                {formatDateCN(date)}
                {date === todayISO() && (
                  <span className="ml-1.5 rounded bg-accent-bg px-1.5 py-0.5 text-[11px] font-normal text-accent">
                    今天
                  </span>
                )}
              </h3>
              <span className="font-mono text-[12px] text-ink2">
                合计 {totalMinutes} / {plan.daily_minutes} 分钟
              </span>
              <span className="h-1.5 max-w-40 flex-1 overflow-hidden rounded bg-untested-bg">
                <span
                  className={`block h-full ${ratio > 1 ? 'bg-error' : 'bg-accent'}`}
                  style={{ width: `${pct}%` }}
                />
              </span>
            </div>
            {tasks.map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                labels={labels}
                readonly={readonly}
                onTransition={onTransition}
                busy={busyTaskId === task.id}
              />
            ))}
          </div>
        )
      })}
    </section>
  )
}

// ---- 页面 ----

export function PlanPage() {
  const { courseId } = useParams()
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [transitionError, setTransitionError] = useState<unknown>(null)

  const framework = useQuery({
    queryKey: ['knowledge', courseId],
    queryFn: () => getKnowledge(courseId!),
    enabled: courseId !== undefined,
    retry: false,
  })
  const plans = useQuery({
    queryKey: ['plans', courseId],
    queryFn: () => listPlans(courseId!),
    enabled: courseId !== undefined,
  })

  // 默认选中 active 版本；没有 active（理论上仅在数据异常时）取最新
  useEffect(() => {
    if (plans.data && selectedId === null) {
      const active = plans.data.find((p) => p.status === 'active')
      const latest = plans.data[0]
      if (active ?? latest) setSelectedId((active ?? latest)!.id)
      else setFormOpen(true)
    }
  }, [plans.data, selectedId])

  const detail = useQuery({
    queryKey: ['plan', selectedId],
    queryFn: () => getPlan(selectedId!),
    enabled: selectedId !== null,
    retry: false,
  })

  const transition = useMutation({
    mutationFn: ({ taskId, to }: { taskId: string; to: string }) => updateTask(taskId, { status: to }),
    onSuccess: () => {
      setTransitionError(null)
      void queryClient.invalidateQueries({ queryKey: ['plan', selectedId] })
    },
    onError: (err) => setTransitionError(err),
  })

  const notBuilt =
    framework.isError &&
    framework.error instanceof ApiError &&
    framework.error.code === 'RESOURCE_NOT_FOUND'

  if (notBuilt) {
    return (
      <EmptyState title="先构建知识框架">
        复习计划按知识框架的叶子节点生成。
        <div className="mt-3">
          <Link to={`/courses/${courseId}/knowledge`} className="text-accent">
            去知识框架 →
          </Link>
        </div>
      </EmptyState>
    )
  }

  const leaves = collectLeaves(framework.data?.tree ?? [])
  const labels = useMemo(() => knowledgePathMap(framework.data?.tree ?? []), [framework.data])
  const planList = plans.data ?? []

  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_380px] items-start gap-6">
      <div className="min-w-0">
        <div className="mb-3 flex items-center gap-3">
          <h1 className="text-[22px] font-bold">复习计划</h1>
          {!formOpen && (
            <button
              type="button"
              onClick={() => setFormOpen(true)}
              className="rounded-md border border-border2 bg-surface px-3 py-1 text-[13px] text-accent hover:border-accent"
            >
              生成新计划
            </button>
          )}
        </div>

        {transitionError != null && (
          <div className="mb-3" aria-live="polite">
            <ErrorNotice error={transitionError} />
          </div>
        )}

        {detail.isError && (
          <div className="mb-3">
            <ErrorNotice error={detail.error} />
          </div>
        )}

        {detail.data && (
          <PlanDetailCard
            plan={detail.data}
            labels={labels}
            onTransition={(taskId, to) => transition.mutate({ taskId, to })}
            busyTaskId={transition.isPending ? transition.variables?.taskId ?? null : null}
          />
        )}

        {detail.isLoading && <p className="text-[13px] text-ink3">计划加载中…</p>}

        {plans.data && planList.length === 0 && !formOpen && (
          <EmptyState title="还没有复习计划">
            设定考试日期和每日可投入的分钟数，系统会按知识框架排出每日任务。
          </EmptyState>
        )}
      </div>

      <aside className="flex min-w-0 flex-col gap-4">
        {formOpen && (
          <GenerateForm
            courseId={courseId!}
            leaves={leaves}
            onCreated={(planId) => {
              setSelectedId(planId)
              setFormOpen(false)
              void queryClient.invalidateQueries({ queryKey: ['plans', courseId] })
            }}
            onCancel={planList.length > 0 ? () => setFormOpen(false) : undefined}
          />
        )}
        {plans.isLoading && <p className="text-[13px] text-ink3">版本加载中…</p>}
        {plans.isError && <ErrorNotice error={plans.error} />}
        {planList.length > 0 && (
          <VersionList plans={planList} selectedId={selectedId} onSelect={setSelectedId} />
        )}
      </aside>
    </div>
  )
}
