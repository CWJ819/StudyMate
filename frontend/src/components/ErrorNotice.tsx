import { ApiError } from '../api/client'
import { AlertTriangle } from './icons'

interface Props {
  error: unknown
  onRetry?: () => void
}

/** 错误提示：中文文案 + 可复制的请求编号（plan §4.1） */
export function ErrorNotice({ error, onRetry }: Props) {
  const apiError = error instanceof ApiError ? error : null
  const message = apiError ? apiError.displayMessage : String(error)
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-2 rounded-md border border-error/40 bg-error-bg px-3 py-2 text-aux text-ink"
    >
      <AlertTriangle className="size-4 flex-none text-error" />
      <span className="min-w-0 flex-1">{message}</span>
      {apiError?.requestId && (
        <span className="font-mono text-meta text-ink3">
          请求编号 {apiError.requestId}
          <button
            type="button"
            className="btn btn-secondary btn-sm ml-1"
            onClick={() => navigator.clipboard?.writeText(apiError.requestId ?? '')}
          >
            复制
          </button>
        </span>
      )}
      {apiError?.retryable && onRetry && (
        <button
          type="button"
          className="btn btn-secondary btn-sm ml-auto"
          onClick={onRetry}
        >
          重试
        </button>
      )}
    </div>
  )
}
