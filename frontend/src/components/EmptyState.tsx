import type { PropsWithChildren, ReactNode } from 'react'
import { Inbox } from './icons'

interface Props {
  title: string
  action?: ReactNode
}

export function EmptyState({ title, action, children }: PropsWithChildren<Props>) {
  return (
    <section className="rounded-lg border border-dashed border-border2 bg-surface px-6 py-10 text-center">
      <Inbox className="mx-auto mb-2 size-6 text-ink3" />
      <h2 className="text-title font-semibold text-ink2">{title}</h2>
      {children && <p className="mx-auto mt-1 max-w-md text-aux text-ink3">{children}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </section>
  )
}
