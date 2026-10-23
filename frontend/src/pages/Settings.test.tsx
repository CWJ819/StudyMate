// 设置页：服务地址/模型名/API Key 可编辑保存、密钥不回显、不渲染 database_url/storage_root、mock:// 显示演示模式说明
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router'
import { server } from '../test/server'
import { settingsMock, settingsPlain } from '../test/fixtures'
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

test('mock:// 配置：表单回填当前值与演示模式说明，隐藏 database_url / storage_root', async () => {
  renderSettings()
  // 等设置数据真正渲染出来（h1 是静态的，等它不算数）；值在输入框里，用 DisplayValue 断言
  expect(await screen.findByDisplayValue('mock://local')).toBeTruthy()

  // 演示模式解释 + 字段值
  expect(screen.getByText('当前为演示模式')).toBeTruthy()
  expect(screen.getByDisplayValue('mock-model')).toBeTruthy()

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

  await screen.findByDisplayValue('https://open.bigmodel.cn/api/paas/v4')
  expect(screen.queryByText('当前为演示模式')).toBeNull()
  expect(screen.getByText('未配置', { exact: false })).toBeTruthy() // llm_auth_configured: false
})

test('修改服务地址与模型名：保存发 PUT /api/settings，成功后显示新值与成功提示', async () => {
  const saved = {
    ...settingsMock,
    llm_base_url: 'https://api.deepseek.com',
    llm_model: 'deepseek-chat',
  }
  const puts: unknown[] = []
  server.use(
    http.put('*/api/settings', async ({ request }) => {
      puts.push(await request.json())
      return HttpResponse.json(saved)
    }),
  )
  renderSettings()

  await screen.findByDisplayValue('mock://local')
  fireEvent.change(screen.getByLabelText(/服务地址/), {
    target: { value: 'https://api.deepseek.com' },
  })
  fireEvent.change(screen.getByLabelText(/模型名/), {
    target: { value: 'deepseek-chat' },
  })
  fireEvent.click(screen.getByRole('button', { name: '保存' }))

  expect(await screen.findByText(/已保存/)).toBeTruthy()
  expect(puts).toEqual([
    { llm_base_url: 'https://api.deepseek.com', llm_model: 'deepseek-chat' },
  ])
  expect(screen.getByDisplayValue('deepseek-chat')).toBeTruthy()
})

test('服务地址格式校验：非 http(s):// 或 mock:// 前缀不给保存并提示', async () => {
  renderSettings()

  fireEvent.change(await screen.findByDisplayValue('mock://local'), {
    target: { value: 'ftp://example.com' },
  })
  expect(screen.getByText(/需以 http/)).toBeTruthy()
  expect((screen.getByRole('button', { name: '保存' }) as HTMLButtonElement).disabled).toBeTruthy()
})

test('保存 API Key：随设置一起 PUT，成功后清空输入并显示保存位置', async () => {
  const saved = {
    ...settingsMock,
    llm_auth_configured: true,
    llm_api_key_source: 'local' as const,
  }
  const puts: unknown[] = []
  server.use(
    http.put('*/api/settings', async ({ request }) => {
      puts.push(await request.json())
      return HttpResponse.json(saved)
    }),
  )
  renderSettings()

  await screen.findByDisplayValue('mock://local')
  const keyInput = screen.getByLabelText(/API Key/) as HTMLInputElement
  // 默认不把密钥明文显示在屏幕上
  expect(keyInput.type).toBe('password')
  fireEvent.change(keyInput, { target: { value: 'sk-local-secret' } })
  fireEvent.click(screen.getByRole('button', { name: '保存' }))

  expect(await screen.findByText('已保存（本机密钥文件）')).toBeTruthy()
  expect(puts).toEqual([
    { llm_base_url: 'mock://local', llm_model: 'mock-model', llm_api_key: 'sk-local-secret' },
  ])
  // 保存后输入框清空，页面不再持有密钥
  expect((screen.getByLabelText(/API Key/) as HTMLInputElement).value).toBe('')
})

test('环境变量提供的 Key：显示来源，且不提供“清除本机 Key”', async () => {
  server.use(
    http.get('*/api/settings', () =>
      HttpResponse.json({
        ...settingsPlain,
        llm_auth_configured: true,
        llm_api_key_source: 'environment',
      }),
    ),
  )
  renderSettings()

  expect(await screen.findByText('已配置（环境变量）')).toBeTruthy()
  expect(screen.queryByRole('button', { name: '清除本机 Key' })).toBeNull()
})

test('清除本机 Key：PUT 空字符串，状态回到未配置', async () => {
  const local = {
    ...settingsPlain,
    llm_auth_configured: true,
    llm_api_key_source: 'local' as const,
  }
  const puts: unknown[] = []
  server.use(
    http.get('*/api/settings', () => HttpResponse.json(local)),
    http.put('*/api/settings', async ({ request }) => {
      puts.push(await request.json())
      return HttpResponse.json({ ...local, llm_auth_configured: false, llm_api_key_source: null })
    }),
  )
  renderSettings()

  await screen.findByText('已保存（本机密钥文件）')
  fireEvent.click(screen.getByRole('button', { name: '清除本机 Key' }))
  // 破坏性操作需二次确认：确认前不发请求
  expect(puts).toEqual([])
  expect(screen.getByText('清除本机保存的 API Key？')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '清除' }))

  expect(await screen.findByText('未配置')).toBeTruthy()
  expect(puts).toEqual([{ llm_api_key: '' }])
})

test('Key 格式被后端拒绝：显示中文文案', async () => {
  server.use(
    http.put(
      '*/api/settings',
      () =>
        HttpResponse.json(
          {
            error: {
              code: 'INVALID_LLM_API_KEY',
              message: 'LLM API key must not contain line breaks.',
            },
          },
          { status: 400 },
        ),
    ),
  )
  renderSettings()

  await screen.findByDisplayValue('mock://local')
  fireEvent.change(screen.getByLabelText(/API Key/), { target: { value: 'sk-bad' } })
  fireEvent.click(screen.getByRole('button', { name: '保存' }))

  expect(await screen.findByText(/API Key 不合法/)).toBeTruthy()
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
