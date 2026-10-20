// F0 验收核心用例：AppShell 显示 health ok 与演示模式横幅
// 顶栏检索：全局（跨课程）检索，结果在搜索框下方就地展开并标注所属课程，页面不跳转
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router'
import type { PropsWithChildren } from 'react'
import { AppShell } from './AppShell'

function withQueryClient(ui: PropsWithChildren['children'], initialEntry = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

test('mock LLM 设置下：显示演示模式横幅与服务正常', async () => {
  withQueryClient(<AppShell>内容</AppShell>)
  expect(await screen.findByText('演示模式')).toBeTruthy()
  expect(await screen.findByText('服务正常')).toBeTruthy()
  // 健康检查通过后不再显示“检查中”
  expect(screen.queryByText('检查中…')).toBeNull()
  // 全局检索入口在课程列表页也可用
  expect(screen.getByLabelText('搜索课件原文')).toBeTruthy()
})

test('全局检索：无需课程上下文，结果就地展开并逐条标注所属课程', async () => {
  const Probe = () => {
    const location = useLocation()
    return <p data-testid="loc">{location.pathname}</p>
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/']}>
        <Probe />
        <AppShell>内容</AppShell>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  const input = await screen.findByLabelText('搜索课件原文')
  fireEvent.change(input, { target: { value: '慢启动' } })
  fireEvent.submit(input.closest('form')!)

  expect(await screen.findByText('2 条命中')).toBeTruthy()
  // 每条命中都带课程标签
  expect(screen.getAllByText('计算机网络·运输层')).toHaveLength(2)
  // 命中片段直接展示完整原文，不需要再点“查看上下文”
  expect(await screen.findByText(/慢启动：拥塞窗口 cwnd 从 1 个 MSS 开始/)).toBeTruthy()
  expect(screen.getByText(/拥塞避免：cwnd 超过 ssthresh 后进入线性增长阶段/)).toBeTruthy()
  // 检索不改变当前路由
  expect(screen.getByTestId('loc').textContent).toBe('/')
})
