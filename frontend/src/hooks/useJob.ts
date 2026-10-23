// 异步作业轮询（plan §4.2）：1s 起逐步放宽到 3s；终态停止；超时上限后提示“仍在处理”不再自动轮询。
// 进度只有 0/100，用不定进度表达；retry_wait 显示“重试中”，不算失败。
// 缓存失效只在「非终态→终态」的真实跃迁时触发一次，且放在 effect 里：
// 从 localStorage 恢复的历史 job 往往早已 succeeded，挂载首渲染就失效会误伤正在飞行的请求。
import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getJob, type Job } from '../api/endpoints'
import { isJobTerminal } from '../api/status'

export type JobPhase =
  | 'loading'
  | 'polling'
  | 'retry_wait'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'timeout'

export interface UseJobOptions {
  /** 自动轮询上限，默认 5 分钟 */
  timeoutMs?: number
  /** 终态后失效的 query key（如框架/测验列表） */
  onSettledInvalidate?: readonly unknown[][]
}

export interface UseJobResult {
  job: Job | undefined
  phase: JobPhase
  /** 超过 timeoutMs 仍在 running/queued：提示“仍在处理”，不再自动轮询 */
  timedOut: boolean
}

export function useJob(
  jobId: string | null | undefined,
  { timeoutMs = 5 * 60_000, onSettledInvalidate = [] }: UseJobOptions = {},
): UseJobResult {
  const queryClient = useQueryClient()
  const startedAtRef = useRef(Date.now())
  const settledRef = useRef(false)
  // 本次 jobId 生命周期内是否见过非终态：只在真实跃迁时失效
  const sawNonTerminalRef = useRef(false)
  const invalidateKeysRef = useRef<readonly unknown[][]>(onSettledInvalidate)
  const [deadlinePassed, setDeadlinePassed] = useState(false)

  useEffect(() => {
    invalidateKeysRef.current = onSettledInvalidate
  })

  useEffect(() => {
    startedAtRef.current = Date.now()
    settledRef.current = false
    sawNonTerminalRef.current = false
    setDeadlinePassed(false)
    if (jobId == null || jobId === '') return
    const timer = setTimeout(() => setDeadlinePassed(true), timeoutMs)
    return () => clearTimeout(timer)
  }, [jobId, timeoutMs])

  const query = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => getJob(jobId!),
    enabled: jobId != null && jobId !== '',
    retry: false,
    refetchInterval: (query) => {
      const job = query.state.data as Job | undefined
      if (job == null) return 1000
      if (isJobTerminal(job.status)) return false
      const elapsed = Date.now() - startedAtRef.current
      if (elapsed > timeoutMs) return false
      return elapsed > 30_000 ? 3000 : 1000
    },
  })

  const job = query.data
  const terminal = job != null && isJobTerminal(job.status)
  const timedOut = deadlinePassed && !terminal

  useEffect(() => {
    if (job != null && !isJobTerminal(job.status)) sawNonTerminalRef.current = true
  }, [job])

  useEffect(() => {
    if (!terminal || settledRef.current || !sawNonTerminalRef.current) return
    settledRef.current = true
    for (const key of invalidateKeysRef.current) {
      queryClient.invalidateQueries({ queryKey: key })
    }
  }, [terminal, queryClient])

  let phase: JobPhase = 'loading'
  if (job != null) {
    if (terminal) phase = job.status as JobPhase
    else if (timedOut) phase = 'timeout'
    else if (job.status === 'retry_wait') phase = 'retry_wait'
    else phase = 'polling'
  }

  return { job, phase, timedOut }
}

/** 资源 → job_id 的 localStorage 映射（刷新后继续取失败原因；资源自身状态为准） */
export function saveJobId(resourceKey: string, jobId: string) {
  try {
    localStorage.setItem(`studymate:job:${resourceKey}`, jobId)
  } catch {
    // 隐私模式等场景下静默失败
  }
}

export function loadJobId(resourceKey: string): string | null {
  try {
    return localStorage.getItem(`studymate:job:${resourceKey}`)
  } catch {
    return null
  }
}
