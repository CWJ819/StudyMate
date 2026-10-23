import type { PropsWithChildren, ReactNode } from 'react'

interface Props {
  title: string
  action?: ReactNode
}

export function EmptyState({ title, action, children }: PropsWithChildren<Props>) {
  return (
    <section className="rounded-lg border border-dashed border-border2 bg-surface px-6 py-10 text-center">
      <h2 className="text-title font-semibold text-ink2">{title}</h2>
      {children && <p className="mx-auto mt-1 max-w-md text-aux text-ink3">{children}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </section>
  )
}
