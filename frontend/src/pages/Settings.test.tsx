// 设置页：只读展示、不渲染 database_url/storage_root、mock:// 显示演示模式说明
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router'
import { server } from '../test/server'
import { settingsPlain } from '../test/fixtures'
import { AppShell } from '../components/AppShell'
import { SettingsPage } from './Settings'

type SettingsEntry = string | { pathname: string; state?: { returnTo?: string } }

function renderSettings(initialEntries: SettingsEntry[] = ['/settings']) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={initialEntries}>
        <Routes>
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/" element={<div>courses</div>} />
          <Route path="/courses/:courseId/quiz" element={<div>quiz-page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

test('mock:// 配置：展示字段值与演示模式说明，隐藏 database_url / storage_root', async () => {
  renderSettings()
  // 等设置数据真正渲染出来（h1 是静态的，等它不算数）
  expect(await screen.findByText('mock://local')).toBeTruthy()

  // 演示模式解释 + 字段值
  expect(screen.getByText('当前为演示模式')).toBeTruthy()
  expect(screen.getByText('mock-model')).toBeTruthy()

  // plan §5：数据库连接串与存储路径不渲染（fixtures 里有值，页面不能出现）
  expect(screen.queryByText(/sqlite\+pysqlite/)).toBeNull()
  expect(screen.queryByText(/data\/uploads/)).toBeNull()
  expect(screen.getByText(/不在页面上展示/)).toBeTruthy()

  // 健康卡
  expect(screen.getByText('服务健康')).toBeTruthy()
})

test('真实模型配置：不显示演示说明，Key 状态如实展示', async () => {
  server.use(http.get('*/api/settings', () => HttpResponse.json(settingsPlain)))
  renderSettings()

  await screen.findByText('https://open.bigmodel.cn/api/paas/v4')
  expect(screen.queryByText('当前为演示模式')).toBeNull()
  expect(screen.getByText('未配置', { exact: false })).toBeTruthy() // llm_auth_configured: false
})

test('直接打开设置：返回链接仍指向课程列表', () => {
  renderSettings()
  const back = screen.getByRole('link', { name: /返回我的课程/ })
  expect(back.getAttribute('href')).toBe('/')
})

test('从课程页进入设置：返回链接回到来源页面而不是课程列表', async () => {
  renderSettings([{ pathname: '/settings', state: { returnTo: '/courses/c1/quiz' } }])

  const back = screen.getByRole('link', { name: /返回上一页/ })
  expect(back.getAttribute('href')).toBe('/courses/c1/quiz')

  fireEvent.click(back)
  expect(await screen.findByText('quiz-page')).toBeTruthy()
})

test('课程页点击顶栏「设置」后再返回，回到原课程页', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/courses/c1/quiz']}>
        <Routes>
          <Route
            path="/courses/:courseId/quiz"
            element={
              <AppShell>
                <div>quiz-page</div>
              </AppShell>
            }
          />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )

  fireEvent.click(await screen.findByRole('link', { name: '设置' }))
  const back = await screen.findByRole('link', { name: /返回上一页/ })
  expect(back.getAttribute('href')).toBe('/courses/c1/quiz')

  fireEvent.click(back)
  expect(await screen.findByText('quiz-page')).toBeTruthy()
})
