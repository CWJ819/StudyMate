// 设置页：只读展示、不渲染 database_url/storage_root、mock:// 显示演示模式说明
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router'
import { server } from '../test/server'
import { settingsPlain } from '../test/fixtures'
import { SettingsPage } from './Settings'

function renderSettings() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/settings']}>
        <Routes>
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/" element={<div>courses</div>} />
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
