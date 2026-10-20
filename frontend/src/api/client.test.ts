// plan §7 单元：api client（JSON、空体、非 JSON 错误、信封与 x-request-id）
import { http, HttpResponse } from 'msw'
import { server } from '../test/server'
import { ApiError, request } from './client'

describe('request', () => {
  test('2xx JSON：解析并返回响应体', async () => {
    server.use(http.get('*/api/ping', () => HttpResponse.json({ ok: true })))
    await expect(request<{ ok: boolean }>('/api/ping')).resolves.toEqual({ ok: true })
  })

  test('204 空体：返回 undefined', async () => {
    server.use(http.get('*/api/no-content', () => new HttpResponse(null, { status: 204 })))
    await expect(request<unknown>('/api/no-content')).resolves.toBeUndefined()
  })

  test('路由层 404 {"detail":"Not Found"}：合成 HTTP_404 且有中文文案', async () => {
    server.use(
      http.get('*/api/nope', () =>
        HttpResponse.json({ detail: 'Not Found' }, { status: 404 }),
      ),
    )
    const err = await request('/api/nope').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    const apiError = err as ApiError
    expect(apiError.status).toBe(404)
    expect(apiError.code).toBe('HTTP_404')
    expect(apiError.displayMessage).toBe('接口不存在（前后端契约不一致）')
  })

  test('非 JSON 错误体（代理返回 HTML）：抛 ApiError 而不抛语法错误', async () => {
    server.use(
      http.get('*/api/html-error', () =>
        new HttpResponse('<html>Bad Gateway</html>', {
          status: 502,
          headers: { 'Content-Type': 'text/html' },
        }),
      ),
    )
    const err = await request('/api/html-error').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(502)
    expect((err as ApiError).code).toBe('HTTP_502')
  })

  test('信封错误：透传 code/message/details；body 缺 request_id 时读 x-request-id 头', async () => {
    server.use(
      http.post('*/api/materials/1', () =>
        HttpResponse.json(
          {
            error: {
              code: 'MATERIALS_NOT_READY',
              message: 'materials not ready',
              details: { material_id: 1 },
            },
          },
          { status: 400, headers: { 'x-request-id': 'rid-123' } },
        ),
      ),
    )
    const err = await request('/api/materials/1', { method: 'POST' }).catch(
      (e: unknown) => e,
    )
    expect(err).toBeInstanceOf(ApiError)
    const apiError = err as ApiError
    expect(apiError.code).toBe('MATERIALS_NOT_READY')
    expect(apiError.displayMessage).toBe('材料还未解析完成，请稍后再试')
    expect(apiError.details).toEqual({ material_id: 1 })
    expect(apiError.requestId).toBe('rid-123')
    expect(apiError.retryable).toBe(false)
  })
})
