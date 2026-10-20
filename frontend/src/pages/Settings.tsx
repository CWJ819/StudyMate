// 设置：服务地址/模型名/API Key 可在页面修改（PUT /api/settings，保存后下一次 LLM 调用即生效）；
// 本机运行的产品允许把 Key 存到本机（数据库同目录 local_secrets.json），页面只显示状态、不回显密钥；
// 不渲染 database_url / storage_root；llm_base_url 以 mock:// 开头时解释演示模式与退出方法。
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useLocation } from 'react-router'
import { getHealth, getSettings, updateSettings, type Settings } from '../api/endpoints'
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

/** 模型服务：服务地址 + 模型名 + API Key 可编辑保存；超时/重试只读 */
function ModelCard({ settings }: { settings: Settings }) {
  const queryClient = useQueryClient()
  // null = 用户还没动过，输入框回退显示服务器值（后台刷新也不会覆盖编辑中的内容）
  const [baseUrl, setBaseUrl] = useState<string | null>(null)
  const [model, setModel] = useState<string | null>(null)
  const [apiKey, setApiKey] = useState('')
  const [showApiKey, setShowApiKey] = useState(false)

  const shownBase = baseUrl ?? settings.llm_base_url ?? ''
  const shownModel = model ?? settings.llm_model ?? ''
  const trimmedBase = shownBase.trim()
  const trimmedModel = shownModel.trim()
  const trimmedKey = apiKey.trim()
  const serverBase = settings.llm_base_url ?? ''
  const serverModel = settings.llm_model ?? ''
  const baseLooksValid = /^(https?:\/\/|mock:\/\/)/.test(trimmedBase)
  const dirty = trimmedBase !== serverBase || trimmedModel !== serverModel || trimmedKey !== ''
  const keyIsLocal = settings.llm_api_key_source === 'local'

  const save = useMutation({
    mutationFn: () =>
      updateSettings({
        llm_base_url: trimmedBase,
        llm_model: trimmedModel,
        ...(trimmedKey ? { llm_api_key: trimmedKey } : {}),
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(['settings'], data)
      // 密钥不留在页面状态里；状态行会显示“已保存（本机）”
      setApiKey('')
    },
  })

  const clearKey = useMutation({
    mutationFn: () => updateSettings({ llm_api_key: '' }),
    onSuccess: (data) => {
      queryClient.setQueryData(['settings'], data)
      setApiKey('')
    },
  })

  const busy = save.isPending || clearKey.isPending

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!trimmedBase || !trimmedModel || !baseLooksValid || busy) return
    save.mutate()
  }

  return (
    <Card title="模型服务">
      <form onSubmit={submit} className="space-y-3 border-t border-border px-5 py-4">
        <label className="block">
          <span className="mb-1 block text-[13px] text-ink2">服务地址（OpenAI 兼容 base URL）</span>
          <input
            type="text"
            value={shownBase}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://api.deepseek.com"
            className="h-[34px] w-full rounded-md border border-border2 bg-bg px-2.5 font-mono text-[13px] text-ink"
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-[13px] text-ink2">模型名</span>
          <input
            type="text"
            value={shownModel}
            onChange={(e) => setModel(e.target.value)}
            placeholder="deepseek-chat"
            className="h-[34px] w-full rounded-md border border-border2 bg-bg px-2.5 font-mono text-[13px] text-ink"
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-[13px] text-ink2">API Key（可选，保存在本机）</span>
          <div className="flex items-center gap-2">
            <input
              type={showApiKey ? 'text' : 'password'}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={settings.llm_auth_configured ? '已配置；留空则不修改' : 'sk-...'}
              autoComplete="new-password"
              spellCheck={false}
              className="h-[34px] min-w-0 flex-1 rounded-md border border-border2 bg-bg px-2.5 font-mono text-[13px] text-ink"
            />
            <button
              type="button"
              onClick={() => setShowApiKey((value) => !value)}
              className="h-[34px] flex-none rounded-md border border-border2 px-3 text-[13px] text-ink2 hover:bg-bg"
            >
              {showApiKey ? '隐藏' : '显示'}
            </button>
          </div>
        </label>
        {shownBase !== '' && !baseLooksValid && (
          <p className="text-[12.5px] text-error">服务地址需以 http:// 、https:// 或 mock:// 开头</p>
        )}
        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={!dirty || !trimmedBase || !trimmedModel || !baseLooksValid || busy}
            className="rounded-md bg-accent px-3.5 py-1.5 text-[13px] font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {save.isPending ? '保存中…' : '保存'}
          </button>
          {keyIsLocal && (
            <button
              type="button"
              onClick={() => clearKey.mutate()}
              disabled={busy}
              className="rounded-md border border-border2 px-3.5 py-1.5 text-[13px] text-ink2 hover:bg-bg disabled:opacity-50"
            >
              {clearKey.isPending ? '清除中…' : '清除本机 Key'}
            </button>
          )}
          {save.isSuccess && !dirty && (
            <span className="text-[12.5px] text-success">已保存，下一次出题/材料解析即使用新配置</span>
          )}
          {clearKey.isSuccess && !keyIsLocal && (
            <span className="text-[12.5px] text-success">已清除本机保存的 Key</span>
          )}
        </div>
        {save.isError && <ErrorNotice error={save.error} />}
        {clearKey.isError && <ErrorNotice error={clearKey.error} />}
        <p className="text-[12.5px] leading-relaxed text-ink3">
          Key 只写入本机数据目录的 <code className="font-mono">local_secrets.json</code>
          （与数据库同目录），不写日志，也不会被{' '}
          <code className="font-mono">GET /api/settings</code> 返回；模型请求只会发给你在上方填写的服务地址。
          环境变量 <code className="font-mono">LLM_API_KEY</code> 仍可作兜底，本机保存的 Key 优先。
        </p>
      </form>
      <div className="border-t border-border">
        <Row label="超时">{settings.llm_timeout_seconds} 秒</Row>
        <Row label="失败重试">最多 {settings.llm_max_retries} 次</Row>
        <Row label="API Key">
          {settings.llm_auth_configured
            ? keyIsLocal
              ? '已保存（本机密钥文件）'
              : '已配置（环境变量）'
            : '未配置'}
        </Row>
      </div>
    </Card>
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
            不消耗 API 配额，页面顶部会显示演示横幅。要切换到真实模型，在下方「模型服务」里修改服务地址、模型名并填入
            API Key 保存即可（也可以改环境变量 <code className="font-mono">LLM_BASE_URL</code> 后重启后端）。
          </div>
        )}

        {settings.data && (
          <>
            <ModelCard settings={settings.data} />

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
