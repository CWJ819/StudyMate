import { ApiError } from '../api/client'

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
      className="flex flex-wrap items-center gap-2 rounded-md border border-error/40 bg-error-bg px-3 py-2 text-[13px] text-ink"
    >
      <span>{message}</span>
      {apiError?.requestId && (
        <span className="font-mono text-xs text-ink3">
          请求编号 {apiError.requestId}
          <button
            type="button"
            className="ml-1 text-accent underline-offset-2 hover:underline"
            onClick={() => navigator.clipboard?.writeText(apiError.requestId ?? '')}
          >
            复制
          </button>
        </span>
      )}
      {apiError?.retryable && onRetry && (
        <button
          type="button"
          className="ml-auto rounded border border-border2 bg-surface px-2 py-0.5 text-xs text-ink2 hover:text-ink"
          onClick={onRetry}
        >
          重试
        </button>
      )}
    </div>
  )
}
