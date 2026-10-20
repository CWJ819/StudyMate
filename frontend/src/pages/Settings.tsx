// 设置：只读展示（plan §5）。不渲染 database_url / storage_root（服务器路径不该出现在浏览器）；
// llm_base_url 以 mock:// 开头时解释演示模式与退出方法。
import { useQuery } from '@tanstack/react-query'
import { Link, useLocation } from 'react-router'
import { getHealth, getSettings } from '../api/endpoints'
import { formatBytes } from '../api/status'
import { AppShell } from '../components/AppShell'
import { ErrorNotice } from '../components/ErrorNotice'
import { settingsReturnTo } from '../lib/navigation'

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-4 border-t border-border px-5 py-2.5 first:border-t-0">
      <span className="w-36 flex-none text-[13px] text-ink2">{label}</span>
      <span className="min-w-0 flex-1 break-all font-mono text-[13px] text-ink">{children}</span>
    </div>
  )
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="overflow-hidden rounded-lg border border-border bg-surface">
      <h2 className="px-5 pb-2 pt-4 text-[15px] font-semibold">{title}</h2>
      <div className="pb-2">{children}</div>
    </section>
  )
}

export function SettingsPage() {
  const settings = useQuery({ queryKey: ['settings'], queryFn: getSettings })
  const health = useQuery({ queryKey: ['health'], queryFn: getHealth })
  const location = useLocation()
  const returnTo = settingsReturnTo(location.state)
  const hasOrigin = returnTo !== '/'
  const demo = settings.data?.llm_base_url?.startsWith('mock://') ?? false

  // 不走 CourseLayout：设置页在课程外，自带无课程上下文的 AppShell（顶栏/横幅/健康状态）
  return (
    <AppShell>
    <div className="mx-auto max-w-[760px]">
      <div className="mb-3 flex items-baseline gap-3">
        <h1 className="text-[22px] font-bold">设置</h1>
        <Link to={returnTo} className="text-[13px] text-accent">
          {hasOrigin ? '← 返回上一页' : '← 返回我的课程'}
        </Link>
      </div>

      <div className="flex flex-col gap-4">
        {settings.isLoading && <p className="text-[13px] text-ink3">加载中…</p>}
        {settings.isError && <ErrorNotice error={settings.error} />}

        {demo && (
          <div className="rounded-lg border border-warning-border bg-warning-bg px-5 py-3 text-[13px] leading-relaxed">
            <b className="font-semibold text-warning">当前为演示模式</b>
            （llm_base_url 以 <code className="font-mono">mock://</code> 开头）：材料解析、出题与批改全部由内置假模型即时生成，
            不消耗 API 配额，页面顶部会显示演示横幅。要切换到真实模型，把环境变量{' '}
            <code className="font-mono">LLM_BASE_URL</code> 指向真实服务并重启后端即可；API Key
            只能通过环境变量配置，不接受接口写入。
          </div>
        )}

        {settings.data && (
          <>
            <Card title="模型">
              <Row label="服务地址">{settings.data.llm_base_url ?? '—（未配置）'}</Row>
              <Row label="模型名">{settings.data.llm_model ?? '—'}</Row>
              <Row label="超时">{settings.data.llm_timeout_seconds} 秒</Row>
              <Row label="失败重试">最多 {settings.data.llm_max_retries} 次</Row>
              <Row label="API Key">
                {settings.data.llm_auth_configured ? '已配置（仅服务器可见）' : '未配置'}
              </Row>
            </Card>

            <Card title="上传与任务限制">
              <Row label="文件大小上限">
                {formatBytes(settings.data.max_upload_bytes)}（.pdf / .pptx）
              </Row>
              <Row label="文档页数上限">{settings.data.max_document_pages} 页</Row>
              <Row label="任务重试上限">{settings.data.job_max_attempts} 次</Row>
            </Card>
          </>
        )}

        <Card title="服务健康">
          {health.isLoading && <p className="px-5 pb-3 text-[13px] text-ink3">检查中…</p>}
          {health.isError && (
            <div className="px-5 pb-3">
              <ErrorNotice error={health.error} />
            </div>
          )}
          {health.data && (
            <>
              <Row label="状态">
                <span className={health.data.status === 'ok' ? 'text-success' : 'text-error'}>
                  {health.data.status}
                </span>
              </Row>
              <Row label="数据库">{health.data.database}</Row>
              <Row label="环境">{health.data.environment}</Row>
            </>
          )}
        </Card>

        <p className="px-1 text-[12.5px] leading-relaxed text-ink3">
          数据库连接串与存储路径属于服务器配置，不在页面上展示。
        </p>
      </div>
    </div>
    </AppShell>
  )
}
