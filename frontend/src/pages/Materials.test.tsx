// 资料页：五态渲染 / 警告与失败原因 / MATERIAL_IN_USE / 列表轮询（检索在顶栏，不在本页）
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router'
import { server } from '../test/server'
import { materialWarn } from '../test/fixtures'
import { MaterialsPage } from './Materials'

function renderMaterials(initialEntry = '/courses/c1/materials') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/courses/:courseId/materials" element={<MaterialsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

test('材料列表：渲染排队/警告完成/失败三态与无文本页、失败原因', async () => {
  renderMaterials()
  expect(await screen.findByText('第3章-运输层（新）.pptx')).toBeTruthy()
  expect(screen.getByText('排队…')).toBeTruthy()
  expect(screen.getByText('有警告完成')).toBeTruthy()
  expect(screen.getByText('失败')).toBeTruthy()
  expect(screen.getByText(/第 2、19 页无文本/)).toBeTruthy()
  // 失败材料展示 error_code 原文（未知码回退原文，已知码此处直接显示码 + 详情页有文案）
  expect(screen.getByText('DOCUMENT_TOO_MANY_PAGES')).toBeTruthy()
})

test('删除被知识框架引用的材料：显示 MATERIAL_IN_USE 中文提示', async () => {
  server.use(
    http.post('*/api/materials/m2/delete', () =>
      HttpResponse.json(
        {
          error: {
            code: 'MATERIAL_IN_USE',
            message: 'material in use',
            details: null,
            request_id: 'req-miu',
          },
        },
        { status: 409 },
      ),
    ),
  )
  renderMaterials()
  await screen.findByText('运输层讲义.pdf')

  // 运输层讲义这一行的删除按钮：行内有多个删除按钮，按行定位
  const rows = document.querySelectorAll('section .group')
  const targetRow = Array.from(rows).find((r) => r.textContent?.includes('运输层讲义.pdf'))
  const rowButton = targetRow!.querySelector<HTMLButtonElement>('button')
  fireEvent.click(rowButton!)

  const confirms = await screen.findAllByRole('button', { name: '删除' })
  fireEvent.click(confirms[confirms.length - 1]!)

  expect(await screen.findByText('材料正被知识框架引用，不能删除')).toBeTruthy()
  expect(screen.getByText(/req-miu/)).toBeTruthy()
})

test('轮询条件：全部终态后不再报错（refetchInterval 关闭路径可执行）', async () => {
  server.use(http.get('*/api/courses/c1/materials', () => HttpResponse.json([materialWarn])))
  renderMaterials()
  expect(await screen.findByText(/1 份材料/)).toBeTruthy()
})
