// plan §7：useJob 用 fake timers 覆盖 queued→running→succeeded、retry_wait、failed、超时
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { PropsWithChildren } from 'react'
import { server } from '../test/server'
import { jobSucceeded } from '../test/fixtures'
import { useJob } from './useJob'

function makeJob(overrides: Record<string, unknown>) {
  return { ...jobSucceeded, ...overrides }
}

function createWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

function createSpyWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const spy = vi.spyOn(client, 'invalidateQueries')
  function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return { Wrapper, spy }
}

function useSequentialJobHandler(responses: Array<Record<string, unknown>>) {
  let call = 0
  server.use(
    http.get('*/api/jobs/:id', () => {
      const body = responses[Math.min(call, responses.length - 1)]!
      call += 1
      return HttpResponse.json(body)
    }),
  )
  return () => call
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

test('queued → running → succeeded：终态后停止轮询', async () => {
  const getCalls = useSequentialJobHandler([
    makeJob({ status: 'queued' }),
    makeJob({ status: 'running' }),
    makeJob({ status: 'succeeded' }),
  ])
  const { result } = renderHook(() => useJob('job-1'), { wrapper: createWrapper() })

  await act(async () => {
    await vi.advanceTimersByTimeAsync(1)
  })
  expect(result.current.phase).toBe('polling')

  // 多推进一点：interval 触发后响应需要再走一拍微任务才落地
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1200)
  })
  expect(result.current.job?.status).toBe('running')

  await act(async () => {
    await vi.advanceTimersByTimeAsync(1200)
  })
  expect(result.current.phase).toBe('succeeded')

  const callsAtTerminal = getCalls()
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000)
  })
  expect(getCalls()).toBe(callsAtTerminal)
})

test('retry_wait 显示重试中，随后成功', async () => {
  useSequentialJobHandler([
    makeJob({ status: 'retry_wait', attempts: 2 }),
    makeJob({ status: 'succeeded' }),
  ])
  const { result } = renderHook(() => useJob('job-2'), { wrapper: createWrapper() })

  await act(async () => {
    await vi.advanceTimersByTimeAsync(1)
  })
  expect(result.current.phase).toBe('retry_wait')

  await act(async () => {
    await vi.advanceTimersByTimeAsync(1200)
  })
  expect(result.current.phase).toBe('succeeded')
})

test('failed：保留 error_code', async () => {
  useSequentialJobHandler([
    makeJob({ status: 'failed', error_code: 'LLM_TIMEOUT', error_summary: 'timeout' }),
  ])
  const { result } = renderHook(() => useJob('job-3'), { wrapper: createWrapper() })

  await act(async () => {
    await vi.advanceTimersByTimeAsync(1)
  })
  expect(result.current.phase).toBe('failed')
  expect(result.current.job?.error_code).toBe('LLM_TIMEOUT')
})

test('挂载时 job 已是终态（localStorage 恢复的历史 job）：不触发缓存失效', async () => {
  useSequentialJobHandler([makeJob({ status: 'succeeded' })])
  const { Wrapper, spy } = createSpyWrapper()
  const { result } = renderHook(
    () => useJob('job-old', { onSettledInvalidate: [['knowledge', 'c1']] }),
    { wrapper: Wrapper },
  )

  await act(async () => {
    await vi.advanceTimersByTimeAsync(200)
  })
  expect(result.current.phase).toBe('succeeded')
  expect(spy).not.toHaveBeenCalled()
})

test('非终态→终态真实跃迁：按 onSettledInvalidate 失效一次', async () => {
  useSequentialJobHandler([
    makeJob({ status: 'running' }),
    makeJob({ status: 'succeeded' }),
  ])
  const { Wrapper, spy } = createSpyWrapper()
  const { result } = renderHook(
    () => useJob('job-live', { onSettledInvalidate: [['knowledge', 'c1']] }),
    { wrapper: Wrapper },
  )

  await act(async () => {
    await vi.advanceTimersByTimeAsync(200)
  })
  expect(result.current.phase).toBe('polling')
  expect(spy).not.toHaveBeenCalled()

  await act(async () => {
    await vi.advanceTimersByTimeAsync(1200)
  })
  expect(result.current.phase).toBe('succeeded')
  expect(spy).toHaveBeenCalledTimes(1)
  expect(spy).toHaveBeenCalledWith({ queryKey: ['knowledge', 'c1'] })
})

test('超时：超过 timeoutMs 仍在 running → 提示仍在处理并停止自动轮询', async () => {
  const getCalls = useSequentialJobHandler([makeJob({ status: 'running' })])
  const { result } = renderHook(() => useJob('job-4', { timeoutMs: 3000 }), {
    wrapper: createWrapper(),
  })

  await act(async () => {
    await vi.advanceTimersByTimeAsync(1)
  })
  expect(result.current.phase).toBe('polling')

  await act(async () => {
    await vi.advanceTimersByTimeAsync(3600)
  })
  expect(result.current.phase).toBe('timeout')
  expect(result.current.timedOut).toBe(true)

  const callsAtTimeout = getCalls()
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000)
  })
  expect(getCalls()).toBe(callsAtTimeout)
})
