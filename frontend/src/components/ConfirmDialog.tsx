import { useEffect, useRef, type PropsWithChildren } from 'react'

interface Props {
  open: boolean
  title: string
  confirmText?: string
  onConfirm: () => void
  onCancel: () => void
}

/** 危险操作二次确认（删除 204 无体，必须挡一层） */
export function ConfirmDialog({
  open,
  title,
  confirmText = '删除',
  onConfirm,
  onCancel,
  children,
}: PropsWithChildren<Props>) {
  const cancelRef = useRef<HTMLButtonElement>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)
  // 调用方多传内联箭头函数：onCancel 若进 effect 依赖，父组件任何重渲染（如列表轮询）
  // 都会 cleanup+setup 抢焦点回「取消」，导致 Tab+Enter 误触发取消而非确认。
  const onCancelRef = useRef(onCancel)

  useEffect(() => {
    onCancelRef.current = onCancel
  })

  useEffect(() => {
    if (!open) return
    previousFocusRef.current = document.activeElement as HTMLElement | null
    cancelRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancelRef.current()
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      previousFocusRef.current?.focus?.()
    }
  }, [open])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" role="presentation">
      <div className="absolute inset-0 bg-black/15" onClick={onCancel} aria-hidden="true" />
      <div
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
        className="relative w-[420px] max-w-[92vw] rounded-lg border border-border bg-surface p-5"
      >
        <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
        <div className="mt-2 text-[13px] leading-relaxed text-ink2">{children}</div>
        <div className="mt-4 flex justify-end gap-2">
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            className="rounded-md border border-border2 px-3 py-1 text-[13px] text-ink2 hover:text-ink"
          >
            取消
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="rounded-md border border-error bg-error-bg px-3 py-1 text-[13px] font-medium text-error hover:bg-error hover:text-white"
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  )
}
