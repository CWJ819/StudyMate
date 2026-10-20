// 课程页：空态 + 创建（POST 体形状）+ 删除确认链路
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router'
import { server } from '../test/server'
import { course1 } from '../test/fixtures'
import { CoursesPage } from './Courses'

function renderCourses() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CoursesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

test('课程列表为空：显示空态', async () => {
  server.use(http.get('*/api/courses', () => HttpResponse.json([])))
  renderCourses()
  expect(await screen.findByText('还没有课程')).toBeTruthy()
})

test('课程列表页：标题为「课程列表」，导航只保留可点击的「我的课程」', async () => {
  renderCourses()
  expect(await screen.findByRole('heading', { name: '课程列表' })).toBeTruthy()

  const nav = screen.getByRole('navigation')
  expect(within(nav).queryByText('课程列表')).toBeNull()
  const navLink = within(nav).getByRole('link', { name: '我的课程' })
  expect(navLink.getAttribute('href')).toBe('/')
})

test('新建课程：提交 POST，成功后出现在列表', async () => {
  let postedBody: unknown
  server.use(
    http.post('*/api/courses', async ({ request }) => {
      postedBody = await request.json()
      return HttpResponse.json(
        { ...course1, id: 'c-new', name: '操作系统', description: '' },
        { status: 201 },
      )
    }),
  )
  server.use(
    http.get('*/api/courses', () => HttpResponse.json([{ ...course1, id: 'c-new', name: '操作系统' }])),
  )
  renderCourses()

  fireEvent.click(screen.getByRole('button', { name: '+ 新建课程' }))
  fireEvent.change(screen.getByLabelText('课程名 *'), { target: { value: '操作系统' } })
  fireEvent.click(screen.getByRole('button', { name: '保存' }))

  expect(await screen.findByText('操作系统')).toBeTruthy()
  await waitFor(() =>
    expect(postedBody).toEqual({ name: '操作系统', description: '' }),
  )
})

test('删除课程：二次确认后才发 DELETE', async () => {
  let deleted = false
  server.use(http.delete('*/api/courses/c1', () => {
    deleted = true
    return new HttpResponse(null, { status: 204 })
  }))
  renderCourses()
  await screen.findByText('计算机网络·运输层')

  // 行内删除按钮 hover 才显示（opacity），但仍可点击
  fireEvent.click(screen.getByRole('button', { name: '删除' }))
  expect(deleted).toBe(false) // 确认框挡住直接删除
  expect(screen.getByText(/都会一并删除/)).toBeTruthy()

  const confirms = screen.getAllByRole('button', { name: '删除' })
  fireEvent.click(confirms[confirms.length - 1]!)
  await waitFor(() => expect(deleted).toBe(true))
})
