// 测验：出题（范围=叶子节点默认全选）→ building 轮询 → 作答（草稿持久化）
// → 幂等提交（首点生成 key 并冻结答案快照，失败重试复用同键同答案）
// → 结果页（只信提交响应与冻结快照，刷新仍在）
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { useEffect, useMemo, useState } from 'react'
import {
  generateQuiz,
  getKnowledge,
  getQuiz,
  submitQuiz,
  type KnowledgeTreeNode,
  type QuizDetail,
  type QuizQuestion,
  type QuizSubmission,
} from '../api/endpoints'
import { collectLeaves } from '../lib/tree'
import { randomUuid } from '../lib/uuid'
import { ApiError } from '../api/client'
import { gradingMethodLabel, quizStatus } from '../api/status'
import {
  loadJobId,
  saveJobId,
  useJob,
} from '../hooks/useJob'
import {
  quizDraftKey,
  quizJobKey,
  recentQuizKey,
  saveJson,
  usePersistedDraft,
  type QuizDraft,
} from '../hooks/usePersistedDraft'
import { EmptyState } from '../components/EmptyState'
import { ErrorNotice } from '../components/ErrorNotice'

const QUESTION_TYPES = [
  { value: 'single_choice', label: '单选' },
  { value: 'multiple_choice', label: '多选' },
  { value: 'short_answer', label: '简答' },
] as const


// ---- 出题表单 ----

function GenerateForm({
  courseId,
  leaves,
  onGenerated,
  onCancel,
}: {
  courseId: string
  leaves: KnowledgeTreeNode[]
  onGenerated: (quizId: string, jobId: string) => void
  onCancel: () => void
}) {
  const [selected, setSelected] = useState<Set<string>>(() => new Set(leaves.map((l) => l.knowledge_node_id)))
  const [count, setCount] = useState(10)
  const [types, setTypes] = useState<string[]>(['single_choice', 'multiple_choice', 'short_answer'])
  const [difficulty, setDifficulty] = useState('low')
  const [formError, setFormError] = useState<string | null>(null)

  const generate = useMutation({
    mutationFn: () =>
      generateQuiz(courseId, {
        // 全选时省略字段（后端缺省=全部叶子）：契约上限 50 个 id，叶子多于 50 时全选清单发不出去
        knowledge_node_ids:
          selected.size === leaves.length ? undefined : Array.from(selected),
        question_count: count,
        question_types: types,
        difficulty,
      }),
    onSuccess: (result) => onGenerated(result.quiz_id, result.job_id),
    onError: (err) =>
      setFormError(err instanceof ApiError ? err.displayMessage : String(err)),
  })

  const toggleLeaf = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const toggleType = (value: string) =>
    setTypes((prev) =>
      prev.includes(value) ? prev.filter((t) => t !== value) : [...prev, value],
    )

  return (
    <form
      className="mb-4 rounded-lg border border-border bg-surface px-5 py-4"
      onSubmit={(e) => {
        e.preventDefault()
        if (selected.size === 0) {
          setFormError('请至少选择一个知识点')
          return
        }
        if (selected.size < leaves.length && selected.size > 50) {
          setFormError(`出题范围最多选 50 个知识点（当前 ${selected.size} 个），请缩小范围`)
          return
        }
        if (types.length === 0) {
          setFormError('请至少选择一种题型')
          return
        }
        setFormError(null)
        generate.mutate()
      }}
      aria-label="出题设置"
    >
      <h2 className="text-title font-semibold">出题设置</h2>
      <div className="mt-3 grid gap-3">
        <fieldset className="min-w-0">
          <legend className="mb-1 text-aux text-ink2">范围（叶子知识点，默认全选）</legend>
          <div className="grid max-w-2xl grid-cols-2 gap-1">
            {leaves.map((leaf) => (
              <label
                key={leaf.knowledge_node_id}
                className="flex min-w-0 items-center gap-1.5 text-aux"
              >
                <input
                  type="checkbox"
                  checked={selected.has(leaf.knowledge_node_id)}
                  onChange={() => toggleLeaf(leaf.knowledge_node_id)}
                  className="flex-none"
                />
                <span className="min-w-0 flex-1 truncate" title={leaf.title}>{leaf.title}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <div className="flex max-w-xl flex-wrap items-end gap-4">
          <label className="text-aux text-ink2">
            题量（1–20）
            <input
              type="number"
              min={1}
              max={20}
              value={count}
              onChange={(e) => setCount(Math.min(20, Math.max(1, Number(e.target.value) || 1)))}
              className="ml-2 w-16 rounded-md border border-border2 bg-bg px-2 py-1 text-body text-ink"
            />
          </label>
          <fieldset className="text-aux text-ink2">
            <legend className="mb-1">题型</legend>
            {QUESTION_TYPES.map((t) => (
              <label key={t.value} className="mr-3 inline-flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={types.includes(t.value)}
                  onChange={() => toggleType(t.value)}
                />
                {t.label}
              </label>
            ))}
          </fieldset>
          <label className="text-aux text-ink2">
            难度
            <select
              value={difficulty}
              onChange={(e) => setDifficulty(e.target.value)}
              className="ml-2 rounded-md border border-border2 bg-bg px-2 py-1 text-body text-ink"
            >
              <option value="low">低</option>
              <option value="medium">中</option>
              <option value="high">高</option>
            </select>
          </label>
        </div>
        {formError && <p className="text-aux text-error">{formError}</p>}
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={generate.isPending}
            className="btn btn-primary"
          >
            {generate.isPending ? '提交中…' : '生成测验'}
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="btn btn-secondary"
          >
            取消
          </button>
        </div>
      </div>
    </form>
  )
}

// ---- 作答视图 ----

interface AnswerMap {
  [questionId: string]: { selected_option_ids?: string[]; text?: string }
}

function answerText(answer: { selected_option_ids?: string[]; text?: string } | undefined): string {
  if (answer == null) return ''
  return answer.text ?? ''
}

function AnswerView({
  quiz,
  draft,
  onDraftChange,
  onSubmit,
  submitting,
  locked,
  submitError,
}: {
  quiz: QuizDetail
  draft: QuizDraft
  onDraftChange: (answers: AnswerMap) => void
  onSubmit: () => void
  submitting: boolean
  /** 已发起过提交：答案随幂等键冻结，作答控件只读（重试必须同键同答案） */
  locked: boolean
  submitError: unknown
}) {
  const answers = draft.answers
  const inputsDisabled = submitting || locked
  const answeredCount = quiz.questions.filter((q) => {
    const a = answers[q.question_id]
    if (q.question_type === 'short_answer') return (a?.text ?? '') !== ''
    return (a?.selected_option_ids ?? []).length > 0
  }).length

  const setChoice = (q: QuizQuestion, optionId: string, multi: boolean) => {
    const prev = answers[q.question_id]?.selected_option_ids ?? []
    const next = multi
      ? prev.includes(optionId)
        ? prev.filter((id) => id !== optionId)
        : [...prev, optionId]
      : prev.includes(optionId)
        ? prev
        : [optionId]
    onDraftChange({ ...answers, [q.question_id]: { selected_option_ids: next } })
  }

  return (
    <section className="overflow-hidden rounded-lg border border-border bg-surface">
      <div className="flex flex-wrap items-center gap-3 border-b border-border px-5 py-3">
        <span className="text-aux text-ink2">
          已答 <b className="text-ink">{answeredCount}</b> / {quiz.questions.length} 题
          <span className="ml-2 text-ink3">（未答也允许提交，按未作答计分）</span>
        </span>
        <button
          type="button"
          onClick={onSubmit}
          disabled={submitting}
          className="ml-auto btn btn-primary"
        >
          {submitting ? '提交中…' : '提交答卷'}
        </button>
      </div>

      {submitError != null && (
        <div className="border-b border-border px-5 py-3">
          <ErrorNotice error={submitError} onRetry={onSubmit} />
          {submitError instanceof ApiError && submitError.retryable && (
            <p className="mt-1 text-aux text-ink3">答案已在本地保留，重试会复用同一提交键，不会重复计分。</p>
          )}
        </div>
      )}

      {quiz.questions
        .slice()
        .sort((a, b) => a.ordinal - b.ordinal)
        .map((q) => {
          const current = answers[q.question_id]
          return (
            <div key={q.question_id} className="border-t border-border px-5 py-4 first:border-t-0">
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-aux text-ink3">Q{q.ordinal}</span>
                <span className="rounded bg-untested-bg px-1.5 py-0.5 text-meta text-ink3">
                  {q.question_type === 'single_choice'
                    ? '单选'
                    : q.question_type === 'multiple_choice'
                      ? '多选'
                      : '简答'}
                </span>
              </div>
              <p className="mt-1 whitespace-pre-wrap text-body leading-[1.7] text-ink">{q.stem}</p>
              {q.question_type === 'short_answer' ? (
                <textarea
                  value={answerText(current)}
                  onChange={(e) =>
                    onDraftChange({ ...answers, [q.question_id]: { text: e.target.value } })
                  }
                  rows={3}
                  disabled={inputsDisabled}
                  aria-label={`Q${q.ordinal} 作答`}
                  className="mt-2 w-full max-w-3xl rounded-md border border-border2 bg-quote-bg px-3 py-2 text-body leading-[1.7] text-ink outline-none focus:border-accent disabled:cursor-not-allowed disabled:opacity-60"
                  placeholder="用自己的话回答，批改由模型完成"
                />
              ) : (
                <div className="mt-2 grid max-w-3xl gap-1.5">
                  {q.options.map((opt) => {
                    const picked = (current?.selected_option_ids ?? []).includes(opt.id)
                    return (
                      <button
                        key={opt.id}
                        type="button"
                        onClick={() => setChoice(q, opt.id, q.question_type === 'multiple_choice')}
                        aria-pressed={picked}
                        disabled={inputsDisabled}
                        className={`transition-colors duration-150 flex items-start gap-2 rounded-md border px-3 py-2 text-left text-body disabled:cursor-not-allowed disabled:opacity-60 ${ picked ? 'border-accent bg-accent-bg/70 text-ink' : 'border-border2 bg-surface text-ink2 hover:border-ink3' }`}
                      >
                        <span
                          aria-hidden="true"
                          className={`mt-0.5 flex size-4 flex-none items-center justify-center border text-micro ${ q.question_type === 'multiple_choice' ? 'rounded-[3px]' : 'rounded-full' } ${picked ? 'border-accent bg-accent text-white' : 'border-border2 text-transparent'}`}
                        >
                          ✓
                        </span>
                        <span className="whitespace-pre-wrap">{opt.text}</span>
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
    </section>
  )
}

// ---- 结果视图（只信提交响应 + 提交时冻结的答案快照）----

function resultTone(r: QuizSubmission['question_results'][number]) {
  if (r.correct === true) return 'success'
  if (r.correct === false && r.score === 0) return 'error'
  if (r.correct === false) return 'warning'
  return 'untested'
}

function ResultView({
  quiz,
  submission,
  answers,
}: {
  quiz: QuizDetail
  submission: QuizSubmission
  answers: AnswerMap
}) {
  const byId = new Map(quiz.questions.map((q) => [q.question_id, q]))
  const results = submission.question_results
  const count = (pred: (r: QuizSubmission['question_results'][number]) => boolean) =>
    results.filter(pred).length
  const right = count((r) => r.correct === true)
  const wrong = count((r) => r.correct === false && r.score === 0)
  const partial = count((r) => r.correct === false && r.score > 0)
  const pending = count((r) => r.correct == null)

  const [expanded, setExpanded] = useState<Set<string>>(() => {
    const s = new Set<string>()
    for (const r of results) if (r.correct !== true) s.add(r.question_id)
    return s
  })

  const statusChip = (r: QuizSubmission['question_results'][number]) => {
    const tone = resultTone(r)
    if (tone === 'success') return <span className="text-success">答对</span>
    if (tone === 'error') return <span className="text-error">答错</span>
    if (tone === 'warning') return <span className="text-warning">部分得分</span>
    return <span className="text-ink3">待批改</span>
  }
  const toneBorder = {
    success: 'border-l-success',
    error: 'border-l-error',
    warning: 'border-l-warning',
    untested: 'border-l-untested',
  } as const

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-5 rounded-lg border border-border bg-surface px-5 py-3">
        <span className="text-title">
          总分 <b className="font-mono tabular-nums">{submission.total_score}</b>
          <span className="text-ink3">
            {' '}
            / <span className="font-mono tabular-nums">{submission.max_score}</span>
          </span>
        </span>
        <span className="text-aux text-success">
          <span className="mr-1.5 inline-block size-2 rounded-full bg-success" />
          答对 <span className="font-mono tabular-nums">{right}</span>
        </span>
        <span className="text-aux text-error">
          <span className="mr-1.5 inline-block size-2 rounded-full bg-error" />
          答错 <span className="font-mono tabular-nums">{wrong}</span>
        </span>
        <span className="text-aux text-warning">
          <span className="mr-1.5 inline-block size-2 rounded-full bg-warning" />
          部分得分 <span className="font-mono tabular-nums">{partial}</span>
        </span>
        <span className="text-aux text-ink3">
          <span className="mr-1.5 inline-block size-2 rounded-full bg-untested" />
          待批改 <span className="font-mono tabular-nums">{pending}</span>
        </span>
      </div>

      <section className="overflow-hidden rounded-lg border border-border bg-surface">
        {results.map((r, i) => {
          const q = byId.get(r.question_id)
          const open = expanded.has(r.question_id)
          const answer = answers[r.question_id]
          return (
            <div
              key={r.question_id}
              className={`animate-fade-in border-t border-border border-l-[3px] first:border-t-0 ${toneBorder[resultTone(r)]}`}
            >
              <button
                type="button"
                aria-expanded={open}
                onClick={() =>
                  setExpanded((prev) => {
                    const next = new Set(prev)
                    if (next.has(r.question_id)) next.delete(r.question_id)
                    else next.add(r.question_id)
                    return next
                  })
                }
                className="flex w-full items-center gap-2.5 px-5 py-2.5 text-left row-hover"
              >
                <span className="font-mono text-aux text-ink3">Q{q?.ordinal ?? i + 1}</span>
                <span className="text-aux font-medium">{statusChip(r)}</span>
                <span className="text-aux text-ink3">
                  得分 <b className="font-mono tabular-nums text-ink2">{r.score}/{r.max_score}</b>
                </span>
                <span className="ml-auto flex-none text-meta text-ink3">{open ? '收起 ▴' : '展开 ▾'}</span>
              </button>
              <div
                className={`grid transition-[grid-template-rows] duration-150 ease-out ${
                  open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
                }`}
              >
                <div className="overflow-hidden">
                  {q && (
                    <div className="px-5 pb-4">
                      <p className="whitespace-pre-wrap text-body leading-[1.7] text-ink">{q.stem}</p>
                      <div className="mt-3 rounded-md border border-border bg-bg px-3.5 py-2.5">
                        <div className="text-meta text-ink3">你的答案</div>
                        {q.question_type === 'short_answer' ? (
                          <p className="mt-0.5 whitespace-pre-wrap text-body text-ink">
                            {(answer?.text ?? '').trim() || '（未作答）'}
                          </p>
                        ) : (
                          <ul className="mt-0.5 grid gap-0.5">
                            {(answer?.selected_option_ids ?? []).length === 0 && (
                              <li className="text-body text-ink3">（未作答）</li>
                            )}
                            {(answer?.selected_option_ids ?? []).map((id) => (
                              <li key={id} className="whitespace-pre-wrap text-body text-ink">
                                · {q.options.find((o) => o.id === id)?.text ?? id}
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                      <p className="mt-2 text-aux text-ink3">
                        判分方式：{gradingMethodLabel(r.grading_method)}；正确答案不随接口下发，请对照课件核对。
                      </p>
                      {r.feedback_text && (
                        <div className="mt-2 rounded-md bg-quote-bg px-3.5 py-2.5">
                          <div className="text-meta text-ink3">批改反馈</div>
                          <p className="mt-0.5 whitespace-pre-wrap text-body leading-[1.7] text-ink">
                            {r.feedback_text}
                          </p>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </section>
      <p className="mt-2 text-meta text-ink3">
        结果保存在本地，刷新后仍在；每份测验只能提交一次，想再练请重新出题。
      </p>
    </div>
  )
}

// ---- 单场测验会话（key=quizId 挂载，草稿随 quizId 隔离）----

function QuizSession({
  quizId,
  courseId,
  onNewQuiz,
}: {
  quizId: string
  courseId: string
  onNewQuiz: () => void
}) {
  const queryClient = useQueryClient()
  const quiz = useQuery({
    queryKey: ['quiz', quizId],
    queryFn: () => getQuiz(quizId),
    refetchInterval: (query) => (query.state.data?.status === 'building' ? 1500 : false),
  })
  const [draft, setDraft] = usePersistedDraft<QuizDraft>(quizDraftKey(quizId), {
    idempotencyKey: null,
    answers: {},
  })
  const [submitError, setSubmitError] = useState<unknown>(null)

  // 出题 job 只用来取失败原因（plan §4.2：以资源自身状态为准）
  const [jobId, setJobId] = useState<string | null>(() => loadJobId(`quiz:${quizId}`))
  useEffect(() => {
    const saved = loadJobId(`quiz:${quizId}`)
    if (saved != null) setJobId(saved)
  }, [quizId])
  const job = useJob(jobId, {
    onSettledInvalidate: [
      ['quiz', quizId],
      ['mastery', courseId],
      ['wrongbook', courseId],
    ],
  })

  const submit = useMutation({
    mutationFn: (payload: { idempotencyKey: string; answers: AnswerMap }) => {
      const questions = quiz.data?.questions ?? []
      return submitQuiz(quizId, {
        idempotency_key: payload.idempotencyKey,
        answers: questions.map((q) =>
          q.question_type === 'short_answer'
            ? {
                question_id: q.question_id,
                text: payload.answers[q.question_id]?.text ?? '',
              }
            : {
                question_id: q.question_id,
                selected_option_ids: payload.answers[q.question_id]?.selected_option_ids ?? [],
              },
        ),
      })
    },
    onSuccess: (submission) => {
      setSubmitError(null)
      setDraft((prev) => ({ ...prev, submission }))
      queryClient.invalidateQueries({ queryKey: ['mastery', courseId] })
      queryClient.invalidateQueries({ queryKey: ['wrongbook', courseId] })
    },
    onError: (err) => setSubmitError(err),
  })

  const onSubmitClick = () => {
    const key = draft.idempotencyKey ?? randomUuid()
    // 首次提交即冻结答案快照：重试必须复用同键同答案（后端对同键不同答案返回 409），
    // 结果页也只展示这份快照——批改窗口内改动草稿不影响已提交内容的呈现
    const answers = draft.submittedAnswers ?? draft.answers
    setDraft((prev) => ({ ...prev, idempotencyKey: key, submittedAnswers: answers }))
    submit.mutate({ idempotencyKey: key, answers })
  }

  if (quiz.isError) {
    return (
      <div>
        <ErrorNotice error={quiz.error} />
        <button type="button" onClick={onNewQuiz} className="mt-3 text-aux text-accent">
          重新出题
        </button>
      </div>
    )
  }
  if (quiz.isLoading || !quiz.data) return <p className="text-aux text-ink3">加载中…</p>

  const status = quizStatus(quiz.data.status)

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2.5 text-aux text-ink2">
        <span className="flex items-center gap-1.5">
          <span className={`inline-block size-2 rounded-full ${status.dot}`} />
          {status.label}
        </span>
        <span>{quiz.data.questions.length || '—'} 题</span>
        {quiz.data.created_at && (
          <span className="text-ink3">{quiz.data.created_at.slice(0, 16).replace('T', ' ')} 生成</span>
        )}
        <button type="button" onClick={onNewQuiz} className="ml-auto text-accent">
          新出题
        </button>
      </div>

      {quiz.data.status === 'building' && (
        <div className="flex items-center gap-2.5 rounded-lg border border-accent/40 bg-accent-bg/60 px-4 py-3 text-aux text-ink">
          <span className="inline-block size-2 animate-pulse rounded-full bg-accent" />
          正在根据所选知识点出题，完成后自动刷新…
          {job.job && (
            <span className="text-ink3">（第 {job.job.attempts} 次尝试）</span>
          )}
        </div>
      )}

      {quiz.data.status === 'failed' && (
        <div className="mb-3">
          <ErrorNotice
            error={new ApiError(500, job.job?.error_code ?? 'QUIZ_GENERATION_FAILED', '出题失败')}
          />
          <button type="button" onClick={onNewQuiz} className="mt-2 text-aux text-accent">
            重新出题
          </button>
        </div>
      )}

      {quiz.data.status === 'open' && draft.submission == null && (
        <AnswerView
          quiz={quiz.data}
          draft={draft}
          onDraftChange={(answers) => setDraft((prev) => ({ ...prev, answers }))}
          onSubmit={onSubmitClick}
          submitting={submit.isPending}
          locked={draft.submittedAnswers != null}
          submitError={submitError}
        />
      )}

      {draft.submission != null && (
        <ResultView
          quiz={quiz.data}
          submission={draft.submission}
          answers={draft.submittedAnswers ?? draft.answers}
        />
      )}

      {quiz.data.status === 'submitted' && draft.submission == null && (
        <div className="rounded-lg border border-border bg-surface px-5 py-4 text-body text-ink2">
          这份测验已提交，但本地没有保存结果（可能换了浏览器或清了缓存）。
          <button type="button" onClick={onNewQuiz} className="ml-2 text-accent">
            重新出题
          </button>
        </div>
      )}
    </div>
  )
}

// ---- 页面 ----

export function QuizPage() {
  const { courseId } = useParams()
  const framework = useQuery({
    queryKey: ['knowledge', courseId],
    queryFn: () => getKnowledge(courseId!),
    enabled: courseId !== undefined,
    retry: false,
  })
  const leaves = useMemo(
    () => collectLeaves(framework.data?.tree ?? []),
    [framework.data],
  )

  const [recentQuizId, setRecentQuizId] = useState<string | null>(() =>
    courseId != null ? (localStorage.getItem(recentQuizKey(courseId)) ?? null) : null,
  )
  useEffect(() => {
    if (courseId != null) {
      const saved = localStorage.getItem(recentQuizKey(courseId))
      if (saved != null) setRecentQuizId(saved)
    }
  }, [courseId])
  const [showForm, setShowForm] = useState(false)

  const notBuilt =
    framework.isError &&
    framework.error instanceof ApiError &&
    framework.error.code === 'RESOURCE_NOT_FOUND'

  if (notBuilt) {
    return (
      <EmptyState title="先构建知识框架，才能出题">
        出题范围与掌握度统计都基于知识框架的叶子知识点。
        <div className="mt-3">
          <Link to={`/courses/${courseId}/knowledge`} className="text-accent">
            去知识框架 →
          </Link>
        </div>
      </EmptyState>
    )
  }

  return (
    <div>
      <div className="mb-3 flex items-end justify-between">
        <div>
          <h1 className="text-page font-semibold">测验</h1>
          <p className="mt-0.5 text-aux text-ink2">出题 → 作答 → 自动批改 → 掌握度与错题本更新</p>
        </div>
        <button
          type="button"
          onClick={() => setShowForm((v) => !v)}
          className="btn btn-primary"
        >
          {showForm ? '收起表单' : '+ 新出题'}
        </button>
      </div>

      {framework.isError && !notBuilt && <ErrorNotice error={framework.error} />}

      {showForm && leaves.length > 0 && (
        <GenerateForm
          courseId={courseId!}
          leaves={leaves}
          onCancel={() => setShowForm(false)}
          onGenerated={(quizId, jobId) => {
            if (courseId != null) {
              localStorage.setItem(recentQuizKey(courseId), quizId)
              saveJobId(`quiz:${quizId}`, jobId)
            }
            saveJson(quizJobKey(quizId), jobId)
            setRecentQuizId(quizId)
            setShowForm(false)
          }}
        />
      )}

      {leaves.length === 0 && !framework.isLoading && !framework.isError && (
        <p className="text-aux text-ink3">知识框架没有叶子节点，无法出题。</p>
      )}

      {recentQuizId != null && courseId != null ? (
        <QuizSession
          key={recentQuizId}
          quizId={recentQuizId}
          courseId={courseId}
          onNewQuiz={() => setShowForm(true)}
        />
      ) : (
        !showForm && (
          <EmptyState title="还没有测验">
            点右上「新出题」，默认覆盖全部叶子知识点。
          </EmptyState>
        )
      )}
    </div>
  )
}
