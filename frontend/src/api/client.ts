// 统一请求层（docs/frontend-plan.md §4.1）
// - 路径直接用生成类型里的完整路径（已含 /api），baseUrl 留空
// - 先读 text 再解析 JSON；解析失败也抛 ApiError
// - 路由层 404/405 无 error 信封时合成 HTTP_xxx；信封缺 request_id 时读 x-request-id 头
// - 非 GET 带 X-Requested-With；JSON 请求设 Content-Type，FormData 不设

import { isRetryable, messageFor } from './errors'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown
  readonly requestId: string | null

  constructor(
    status: number,
    code: string,
    message: string,
    details: unknown = null,
    requestId: string | null = null,
    options?: ErrorOptions,
  ) {
    super(message, options)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
    this.requestId = requestId
  }

  get retryable(): boolean {
    return isRetryable(this.code)
  }

  /** 有映射文案用中文文案，否则显示后端 message 原文 */
  get displayMessage(): string {
    return messageFor(this.code) ?? this.message
  }
}

interface ErrorEnvelope {
  error?: {
    code?: string
    message?: string
    details?: unknown
    request_id?: string
  }
}

function toApiError(response: Response, text: string, body: unknown): ApiError {
  const envelope =
    body != null && typeof body === 'object' && 'error' in body
      ? ((body as ErrorEnvelope).error ?? {})
      : {}
  const requestId = envelope.request_id ?? response.headers.get('x-request-id') ?? null

  if (typeof envelope.code === 'string' && envelope.code !== '') {
    return new ApiError(
      response.status,
      envelope.code,
      envelope.message ?? '',
      envelope.details ?? null,
      requestId,
    )
  }

  // FastAPI 路由层 404/405：{"detail":"Not Found"}，没有 error 信封
  const code = `HTTP_${response.status}`
  let fallback: string
  if (
    body != null &&
    typeof body === 'object' &&
    'detail' in body &&
    (body as { detail?: unknown }).detail != null
  ) {
    fallback = String((body as { detail: unknown }).detail)
  } else if (text !== '') {
    fallback = '服务返回了非 JSON 响应（可能经过了代理）'
  } else {
    fallback = `请求失败（HTTP ${response.status}）`
  }
  return new ApiError(response.status, code, fallback, null, requestId)
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    const headers = new Headers(init.headers)
    const method = (init.method ?? 'GET').toUpperCase()
    if (
      init.body != null &&
      !(init.body instanceof FormData) &&
      !headers.has('Content-Type')
    ) {
      headers.set('Content-Type', 'application/json')
    }
    if (method !== 'GET') {
      headers.set('X-Requested-With', 'XMLHttpRequest')
    }
    response = await fetch(path, { ...init, headers })
  } catch (cause) {
    throw new ApiError(0, 'NETWORK_ERROR', '网络请求失败', null, null, { cause })
  }

  const text = await response.text()
  let body: unknown
  if (text !== '') {
    try {
      body = JSON.parse(text)
    } catch {
      body = undefined
    }
  }

  if (!response.ok) {
    throw toApiError(response, text, body)
  }
  // 204 或空体 → undefined
  return body as T
}
