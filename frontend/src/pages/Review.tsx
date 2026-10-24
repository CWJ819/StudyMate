// 复习：掌握度估计列表（升序 + 未测验灰）+ 错题本（知识缺口）+ 复习目标 → 一键出题
// 掌握度行默认显示条数（长列表渐进展开，与资料搜索同款模式）
const MASTERY_LIMIT = 20
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router'
import { useState } from 'react'
import {
  generateQuiz,
  getKnowledge,
  getWrongbook,
  listMastery,
  postReviewTargets,
} from '../api/endpoints'
import { collectLeaves } from '../lib/tree'
import { ApiError } from '../api/client'
import { gapTypeLabel } from '../api/status'
import { saveJobId } from '../hooks/useJob'
import { recentQuizKey } from '../hooks/usePersistedDraft'
import { EmptyState } from '../components/EmptyState'
import { ErrorNotice } from '../components/ErrorNotice'
import { SkeletonRows } from '../components/Skeleton'


/** evidence_summary 是后端的计数字典（total_evidence/low_score_evidence/...），泛化成键值行 */
function GapEvidence({ summary }: { summary: Record<string, unknown> }) {
  const labels: Record<string, string> = {
    total_evidence: '作答',
    low_score_evidence: '低分',
    positive_evidence: '答对',
    last_normalized_score: '最近得分',
  }
  const entries = Object.entries(summary ?? {}).filter(([k]) => k !== 'last_attempt_id')
  if (entries.length === 0) return null
  return (
    <p className="mt-0.5 text-aux text-ink2">
      {entries
        .map(([k, v]) => `${labels[k] ?? k} ${typeof v === 'number' ? v : String(v)}`)
        .join(' · ')}
    </p>
  )
}
/** 掌握度估计行（dir1 术语：估计 0.42 · 依据 3 次作答；未测验 ≠ 薄弱） */
function MasteryRow({
  title,
  estimate,
  evidence,
}: {
  title: string | null
  estimate: number | null
  evidence: number
}) {
  const tested = estimate != null
  return (
    <div className="grid animate-fade-in grid-cols-[minmax(120px,220px)_1fr_150px] items-center gap-3 border-t border-border px-5 py-2 first:border-t-0">
      <span
        className={`truncate text-aux ${tested ? 'text-ink' : 'text-ink3'}`}
        title={title ?? undefined}
      >
        {title ?? '（未命名）'}
      </span>
      <span className="relative inline-block h-3 overflow-hidden rounded-sm bg-untested-bg">
        {tested && (
          <>
            <span
              className="block h-full bg-accent"
              style={{ width: `${Math.round(estimate * 100)}%` }}
            />
            <span className="absolute inset-y-0 left-1/2 w-px bg-border2" />
          </>
        )}
      </span>
      <span className={`text-right font-mono text-meta tabular-nums ${tested ? 'text-ink2' : 'text-ink3'}`}>
        {tested ? `${estimate.toFixed(2)} · 依据 ${evidence} 次作答` : '未测验'}
      </span>
    </div>
  )
}

export function ReviewPage() {
  const { courseId } = useParams()
  const navigate = useNavigate()

  const framework = useQuery({
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
  const wrongbook = useQuery({
    queryKey: ['wrongbook', courseId],
    queryFn: () => getWrongbook(courseId!),
    enabled: courseId !== undefined,
  })

  const [limit, setLimit] = useState(10)
  const [ratio, setRatio] = useState(0.3)
  const [targetError, setTargetError] = useState<unknown>(null)
  // 掌握度长列表收敛（与资料搜索同款渐进展开）
  const [showAllTested, setShowAllTested] = useState(false)
  const [showUntested, setShowUntested] = useState(false)

  // 复习目标 → 直接以这些节点出题 → 跳测验页（变式题接口缺失时的闭环替代，plan §5）
  const startReviewQuiz = useMutation({
    mutationFn: async () => {
      const targets = await postReviewTargets(courseId!, {
        limit,
        exploration_ratio: ratio,
      })
      return generateQuiz(courseId!, {
        knowledge_node_ids: targets.targets.map((t) => t.knowledge_node_id),
        question_count: Math.min(20, targets.targets.length * 2),
      })
    },
    onSuccess: (quiz) => {
      setTargetError(null)
      if (courseId != null) {
        localStorage.setItem(recentQuizKey(courseId), quiz.quiz_id)
        saveJobId(`quiz:${quiz.quiz_id}`, quiz.job_id)
      }
      navigate(`/courses/${courseId}/quiz`)
    },
    onError: (err) => setTargetError(err),
  })

  const notBuilt =
    framework.isError &&
    framework.error instanceof ApiError &&
    framework.error.code === 'RESOURCE_NOT_FOUND'

  if (notBuilt) {
    return (
      <EmptyState title="先构建知识框架">
        掌握度与错题本都基于知识框架统计。
        <div className="mt-3">
          <Link to={`/courses/${courseId}/knowledge`} className="text-accent">
            去知识框架 →
          </Link>
        </div>
      </EmptyState>
    )
  }

  const leaves = collectLeaves(framework.data?.tree ?? [])
  const masteryByNode = new Map((mastery.data ?? []).map((m) => [m.knowledge_node_id, m]))
  // 已测验按估计值升序在前，未测验（框架叶子但无记录）灰条在后
  const testedRows = (mastery.data ?? [])
    .slice()
    .sort((a, b) => a.mastery_estimate - b.mastery_estimate)
  const untestedLeaves = leaves.filter((l) => !masteryByNode.has(l.knowledge_node_id))
  // 长列表收敛：已测验默认前 20 条（与资料搜索同款渐进展开），未测验折叠成计数行
  const testedVisible = showAllTested ? testedRows : testedRows.slice(0, MASTERY_LIMIT)
  const hiddenTested = testedRows.length - testedVisible.length

  const gaps = wrongbook.data ?? []

  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_420px] items-start gap-6">
      <div className="min-w-0">
        <h1 className="mb-3 text-page font-semibold">复习</h1>

        <section className="overflow-hidden rounded-lg border border-border bg-surface">
          <div className="flex items-baseline gap-3 px-5 pb-2 pt-4">
            <h2 className="text-title font-semibold">掌握度估计</h2>
            <span className="text-aux text-ink3">已测验升序 · 未测验 ≠ 薄弱</span>
          </div>
          {mastery.isLoading && <SkeletonRows rows={4} className="px-5 pb-4" />}
          {mastery.isError && (
            <div className="px-5 pb-4">
              <ErrorNotice error={mastery.error} />
            </div>
          )}
          {testedVisible.map((m) => (
            <MasteryRow
              key={m.knowledge_node_id}
              title={m.title}
              estimate={m.mastery_estimate}
              evidence={m.evidence_count}
            />
          ))}
          {hiddenTested > 0 && (
            <button
              type="button"
              onClick={() => setShowAllTested((v) => !v)}
              className="w-full border-t border-border px-5 py-2 text-left text-aux text-accent row-hover"
            >
              {showAllTested ? (
                '收起 ▴'
              ) : (
                <>
                  展开其余 <span className="font-mono tabular-nums">{hiddenTested}</span> 条已测验 ▾
                </>
              )}
            </button>
          )}
          {untestedLeaves.length > 0 && (
            <button
              type="button"
              onClick={() => setShowUntested((v) => !v)}
              aria-expanded={showUntested}
              className="w-full border-t border-border px-5 py-2 text-left text-aux text-ink3 row-hover"
            >
              {showUntested ? (
                '收起未测验 ▴'
              ) : (
                <>
                  未测验 <span className="font-mono tabular-nums">{untestedLeaves.length}</span>{' '}
                  个（不代表薄弱）· 展开 ▾
                </>
              )}
            </button>
          )}
          {showUntested &&
            untestedLeaves.map((l) => (
              <MasteryRow key={l.knowledge_node_id} title={l.title} estimate={null} evidence={0} />
            ))}
          <p className="border-t border-dashed border-border px-5 py-2 text-meta leading-relaxed text-ink3">
            估计值 = 作答记录的统计推断，不是精确测量。
          </p>
        </section>

        <section className="mt-6 overflow-hidden rounded-lg border border-border bg-surface">
          <div className="flex items-baseline gap-3 px-5 pb-2 pt-4">
            <h2 className="text-title font-semibold">错题本（知识缺口）</h2>
            <span className="text-aux text-ink3">由测验记录得出，非自评</span>
          </div>
          {wrongbook.isLoading && <SkeletonRows rows={3} className="px-5 pb-4" />}
          {wrongbook.isError && (
            <div className="px-5 pb-4">
              <ErrorNotice error={wrongbook.error} />
            </div>
          )}
          {!wrongbook.isLoading && gaps.length === 0 && (
            <p className="border-t border-border px-5 py-5 text-aux text-ink3">
              还没有知识缺口记录——完成一次测验后，这里会列出薄弱知识点及其原因。
            </p>
          )}
          {gaps.map((gap) => (
            <div key={gap.gap_id} className="animate-fade-in border-t border-border px-5 py-3">
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="text-body font-semibold">{gap.title}</span>
                <span className="rounded bg-untested-bg px-1.5 py-0.5 text-meta text-ink3">
                  {gapTypeLabel(gap.gap_type)}
                </span>
                {gap.evidence_count > 0 && (
                  <span className="font-mono text-meta text-ink3">
                    依据 {gap.evidence_count} 次
                  </span>
                )}
              </div>
              {gap.evidence_summary != null && Object.keys(gap.evidence_summary).length > 0 && (
                <GapEvidence summary={gap.evidence_summary} />
              )}
            </div>
          ))}
        </section>
      </div>

      <aside className="min-w-0">
        <section className="rounded-lg border border-border bg-surface px-5 py-4">
          <h2 className="text-title font-semibold">练一轮薄弱点</h2>
          <p className="mt-1 text-aux leading-relaxed text-ink3">
            按策略挑选知识点（重点补薄弱、留一部分探索未测），直接生成一份针对性测验。
          </p>
          <div className="mt-3 grid gap-3">
            <label className="text-aux text-ink2">
              目标知识点数（1–50）
              <input
                type="number"
                min={1}
                max={50}
                value={limit}
                onChange={(e) => setLimit(Math.min(50, Math.max(1, Number(e.target.value) || 1)))}
                className="ml-2 w-16 rounded-md border border-border2 bg-bg px-2 py-1 text-body text-ink"
              />
            </label>
            <label className="text-aux text-ink2">
              探索比例 <span className="font-mono tabular-nums">{ratio.toFixed(2)}</span>
              （0=全薄弱，1=全未测）
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={ratio}
                onChange={(e) => setRatio(Number(e.target.value))}
                className="mt-1 w-full"
              />
            </label>
            {targetError != null && <ErrorNotice error={targetError} />}
            <button
              type="button"
              onClick={() => startReviewQuiz.mutate()}
              disabled={startReviewQuiz.isPending}
              className="btn btn-primary"
            >
              {startReviewQuiz.isPending ? '生成中…' : '生成复习测验'}
            </button>
          </div>
        </section>
      </aside>
    </div>
  )
}
