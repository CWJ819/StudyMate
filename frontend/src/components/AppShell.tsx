// 应用骨架：演示横幅(38) → 顶栏(58，品牌 + 全文检索 + 状态) → 课程 tab(46) → 内容区
// 视觉基线方向一（plan §4.5 / docs/design/mockups/dir1-overview.html）
import { useQuery } from '@tanstack/react-query'
import { Link, NavLink } from 'react-router'
import {
  getHealth,
  getSettings,
  listCourses,
  searchChunks,
  type ChunkSearchResult,
  type Course,
} from '../api/endpoints'
import { useEffect, useRef, useState, type FormEvent, type PropsWithChildren } from 'react'
import { ErrorNotice } from './ErrorNotice'

export type TabKey = 'overview' | 'materials' | 'knowledge' | 'quiz' | 'review' | 'plan'

/** 全局检索命中：附加所属课程，用于每条结果的课程标签 */
type CourseHit = ChunkSearchResult & { course_id: string; course_name: string }

const TABS: Array<{ key: TabKey; label: string; suffix: string }> = [
  { key: 'overview', label: '总览', suffix: '' },
  { key: 'materials', label: '资料', suffix: '/materials' },
  { key: 'knowledge', label: '知识框架', suffix: '/knowledge' },
  { key: 'quiz', label: '测验', suffix: '/quiz' },
  { key: 'review', label: '复习', suffix: '/review' },
  { key: 'plan', label: '复习计划', suffix: '/plan' },
]

interface AppShellProps extends PropsWithChildren {
  /** 有课程上下文时 crumb 与 tab 变成真实路由；无则只显示「我的课程」入口 */
  course?: Course | null
  active?: TabKey
}

function HealthBadge() {
  const health = useQuery({ queryKey: ['health'], queryFn: getHealth, refetchInterval: 30_000 })
  return (
    <span
      aria-live="polite"
      title={health.isError ? '后端健康检查失败' : health.data ? health.data.status : '检查中'}
      className="flex items-center gap-1.5 text-[13px]"
    >
      {health.isError && (
        <>
          <span className="inline-block size-2 rounded-full bg-error" />
          <span className="text-error">服务异常</span>
        </>
      )}
      {health.isLoading && <span className="text-ink3">检查中…</span>}
      {health.data && (
        <>
          <span className="inline-block size-2 rounded-full bg-success" />
          <span>服务正常</span>
        </>
      )}
    </span>
  )
}

function DemoBanner() {
  const settings = useQuery({ queryKey: ['settings'], queryFn: getSettings, staleTime: 300_000 })
  const demo = settings.data?.llm_base_url?.startsWith('mock://') ?? false
  if (!demo) return null
  return (
    <div className="flex h-[38px] items-center gap-2.5 border-b border-warning-border bg-warning-bg px-7 text-[13px] text-ink">
      <span className="flex size-3.5 items-center justify-center rounded-full bg-warning text-[10px] font-bold text-white">
        演
      </span>
      <span>
        <b className="font-semibold text-warning">演示模式</b> — 示例数据，操作不保存
      </span>
      <a href="#/settings" className="ml-auto text-xs text-accent no-underline">
        如何退出演示？
      </a>
    </div>
  )
}

export function AppShell({ course, active, children }: AppShellProps) {
  const [q, setQ] = useState('')
  const [submitted, setSubmitted] = useState('')
  const [open, setOpen] = useState(false)
  const searchBoxRef = useRef<HTMLDivElement>(null)

  // 检索是全局的：并行查所有课程，命中带上所属课程；结果在搜索框下方就地展开，页面不跳转
  const search = useQuery({
    queryKey: ['search-global', submitted],
    queryFn: async () => {
      const courses = await listCourses()
      const settled = await Promise.allSettled(
        courses.map(async (c) => {
          const hits = await searchChunks(c.id, submitted)
          return hits.map((h) => ({ ...h, course_id: c.id, course_name: c.name }))
        }),
      )
      const results = settled.flatMap((s) => (s.status === 'fulfilled' ? s.value : []))
      const failed = settled.filter((s) => s.status === 'rejected').length
      return { results, failed }
    },
    enabled: open && submitted !== '',
  })

  // Esc 或点击搜索框以外区域时收起结果
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    const onPointerDown = (e: MouseEvent) => {
      if (searchBoxRef.current && !searchBoxRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onPointerDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onPointerDown)
    }
  }, [open])

  const submitSearch = (e: FormEvent) => {
    e.preventDefault()
    const query = q.trim()
    if (query === '') return
    setSubmitted(query)
    setOpen(true)
  }

  const hits: CourseHit[] = search.data?.results ?? []

  return (
    <div className="flex min-h-screen flex-col">
      <DemoBanner />
      <header className="flex h-[58px] items-center gap-5 border-b border-border bg-surface px-7">
        <div className="text-base font-bold tracking-wide">
          智学伴
          <small className="ml-1.5 text-[11px] font-normal tracking-normal text-ink3">StudyMate</small>
        </div>
        <div ref={searchBoxRef} className="relative mx-auto w-full max-w-[560px]">
            <form onSubmit={submitSearch}>
              <input
                type="text"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                aria-label="搜索课件原文"
                placeholder="搜索课件原文，如：慢启动、ssthresh、校验和"
                className="h-[34px] w-full rounded-md border border-border2 bg-bg pr-[92px] pl-[34px] text-[13px] text-ink3 outline-none focus:border-accent"
              />
              <span className="pointer-events-none absolute left-[11px] top-[7px] text-sm text-ink3">⌕</span>
              <button
                type="submit"
                className="absolute right-[6px] top-[4px] rounded border border-border2 bg-surface px-1.5 py-px text-[11px] text-ink3 hover:border-accent hover:text-accent"
              >
                全文检索
              </button>
            </form>
            {open && (
              <div className="absolute left-0 right-0 top-full z-30 mt-1 max-h-[420px] overflow-y-auto rounded-md border border-border bg-surface shadow-lg">
                <div className="flex items-center gap-2 border-b border-border px-3 py-2 text-[12.5px]">
                  <span className="min-w-0 truncate text-ink2">「{submitted}」</span>
                {search.isSuccess && (
                  <span className="flex-none text-ink3">{hits.length} 条命中</span>
                )}
                {search.isSuccess && (search.data?.failed ?? 0) > 0 && (
                  <span className="flex-none text-warning">{search.data?.failed} 门课程检索失败</span>
                )}
                  <button
                    type="button"
                    onClick={() => setOpen(false)}
                    aria-label="关闭检索结果"
                    className="ml-auto flex-none text-[13px] text-ink3 hover:text-ink"
                  >
                    ×
                  </button>
                </div>
                {search.isLoading && <p className="px-3 py-3 text-[13px] text-ink3">检索中…</p>}
                {search.isError && (
                  <div className="px-3 py-3">
                    <ErrorNotice error={search.error} />
                  </div>
                )}
                {search.isSuccess && hits.length === 0 && (
                  <p className="px-3 py-3 text-[13px] text-ink3">
                    「{submitted}」没有命中任何课件片段。检索是子串匹配，试试更短的词。
                  </p>
                )}
                {hits.map((r) => (
                  <div key={r.chunk_id} className="border-t border-border px-3 py-2">
                    <div className="flex items-baseline gap-2 text-[12px] text-ink3">
                      <span className="flex-none rounded bg-accent-bg px-1.5 py-0.5 text-[11px] text-accent">
                        {r.course_name}
                      </span>
                      <span className="min-w-0 truncate font-medium text-ink2">{r.filename}</span>
                      <span className="flex-none">
                        第 {r.page_start}
                        {r.page_end > r.page_start ? `–${r.page_end}` : ''} 页
                      </span>
                    </div>
                    <p className="mt-1 whitespace-pre-wrap text-[13px] leading-[1.65] text-ink">{r.text}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        <div className="ml-auto flex items-center gap-4 text-[13px] text-ink2">
          <HealthBadge />
          <span>使用说明</span>
          <Link to="/settings" className="text-ink2 no-underline hover:text-accent">
            设置
          </Link>
        </div>
      </header>
      <nav className="flex h-[46px] items-stretch gap-1 border-b border-border bg-surface px-7">
        {course ? (
          <>
            <span className="mr-4 flex items-center gap-1 text-[13px] text-ink3">
              <Link to="/" className="text-ink3 no-underline hover:text-accent">
                我的课程
              </Link>
              <span>/</span>
              <span className="max-w-[220px] truncate text-ink2" title={course.name}>
                {course.name}
              </span>
            </span>
            {TABS.map((tab) => (
              <Link
                key={tab.key}
                to={`/courses/${course.id}${tab.suffix}`}
                className={`-mb-px flex items-center border-b-2 px-3.5 no-underline ${
                  active === tab.key
                    ? 'border-accent font-semibold text-ink'
                    : 'border-transparent text-ink2 hover:text-ink'
                }`}
              >
                {tab.label}
              </Link>
            ))}
          </>
        ) : (
          <NavLink
            to="/"
            end
            className={({ isActive }) =>
              `-mb-px flex items-center border-b-2 px-3.5 text-sm no-underline ${
                isActive
                  ? 'border-accent font-semibold text-ink'
                  : 'border-transparent text-ink2 hover:text-ink'
              }`
            }
          >
            我的课程
          </NavLink>
        )}
      </nav>
      <main className="flex-1 px-8 py-4">{children}</main>
    </div>
  )
}
