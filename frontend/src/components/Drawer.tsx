import { useEffect, useRef, type PropsWithChildren, type ReactNode } from 'react'

interface Props {
  open: boolean
  title: ReactNode
  onClose: () => void
}

/** 右侧抽屉（B-2：约 400px 宽，点遮罩或 Esc 关闭，焦点进面板、关闭后归还） */
export function Drawer({ open, title, onClose, children }: PropsWithChildren<Props>) {
  const panelRef = useRef<HTMLDivElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (!open) return
    previousFocusRef.current = document.activeElement as HTMLElement | null
    closeRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      previousFocusRef.current?.focus?.()
    }
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-40" role="presentation">
      <div className="absolute inset-0 bg-black/10" onClick={onClose} aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        className="absolute inset-y-0 right-0 flex w-[440px] max-w-[92vw] flex-col border-l border-border bg-surface"
      >
        <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
          <div className="min-w-0 flex-1 truncate text-[13.5px] font-semibold text-ink">{title}</div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            className="rounded border border-border2 px-2 py-0.5 text-xs text-ink2 hover:text-ink"
          >
            关闭
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-4 py-3">{children}</div>
      </div>
    </div>
  )
}
