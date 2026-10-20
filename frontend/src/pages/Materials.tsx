// 资料页：上传（多选顺序传）+ 解析状态轮询 + 删除（全文检索在顶栏，结果就地展开，不在本页放搜索框）
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { useRef, useState, type ChangeEvent } from 'react'
import {
  deleteMaterial,
  getSettings,
  listMaterials,
  uploadMaterial,
  type MaterialSummary,
} from '../api/endpoints'
import { ApiError } from '../api/client'
import { formatBytes, isPending, materialStatus, validateUploadFile } from '../api/status'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { EmptyState } from '../components/EmptyState'
import { ErrorNotice } from '../components/ErrorNotice'

interface UploadEntry {
  name: string
  state: 'uploading' | 'ok' | 'error'
  error?: string
}

function StatusDot({ status }: { status: string }) {
  const meta = materialStatus(status)
  return (
    <span className="flex items-center gap-1.5 text-[12.5px]">
      <span className={`inline-block size-2 flex-none rounded-full ${meta.dot}`} />
      {isPending(status) && <span className="animate-pulse text-ink2">{meta.label}…</span>}
      {!isPending(status) && <span className="text-ink2">{meta.label}</span>}
    </span>
  )
}

export function MaterialsPage() {
  const { courseId } = useParams()
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [uploads, setUploads] = useState<UploadEntry[]>([])
  const [deleting, setDeleting] = useState<MaterialSummary | null>(null)
  const [deleteError, setDeleteError] = useState<unknown>(null)

  const settings = useQuery({ queryKey: ['settings'], queryFn: getSettings, staleTime: 300_000 })
  const materials = useQuery({
    queryKey: ['materials', courseId],
    queryFn: () => listMaterials(courseId!),
    enabled: courseId !== undefined,
    // 有排队/处理中的材料时轮询，其余情况停
    refetchInterval: (query) =>
      (query.state.data ?? []).some((m) => isPending(m.status)) ? 1500 : false,
  })

  const remove = useMutation({
    mutationFn: (id: string) => deleteMaterial(id),
    onSuccess: () => {
      setDeleting(null)
      setDeleteError(null)
      queryClient.invalidateQueries({ queryKey: ['materials', courseId] })
    },
    onError: (err) => setDeleteError(err),
  })

  // 多选顺序上传；每个文件在上传条目上反馈预检/上传/解析结果
  async function onFilesChosen(e: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? [])
    e.target.value = ''
    if (files.length === 0 || !courseId) return
    const maxBytes = settings.data?.max_upload_bytes ?? 0

    for (const file of files) {
      const invalid = validateUploadFile(file, maxBytes)
      if (invalid) {
        setUploads((prev) => [{ name: file.name, state: 'error' as const, error: invalid }, ...prev].slice(0, 6))
        continue
      }
      setUploads((prev) => [{ name: file.name, state: 'uploading' as const }, ...prev].slice(0, 6))
      try {
        await uploadMaterial(courseId, file)
        setUploads((prev) =>
          prev.map((u) => (u.name === file.name && u.state === 'uploading' ? { ...u, state: 'ok' } : u)),
        )
        queryClient.invalidateQueries({ queryKey: ['materials', courseId] })
      } catch (err) {
        const message = err instanceof ApiError ? err.displayMessage : String(err)
        setUploads((prev) =>
          prev.map((u) => (u.name === file.name && u.state === 'uploading' ? { ...u, state: 'error', error: message } : u)),
        )
      }
    }
  }

  const list = materials.data ?? []

  return (
    <div>
      <div className="mb-3 flex items-end justify-between">
        <div>
          <h1 className="text-[22px] font-bold">资料</h1>
          <p className="mt-0.5 text-[13px] text-ink2">
            {list.length} 份材料 · 支持 PDF / PPTX 课件 · 解析后可搜索原文
          </p>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".pdf,.pptx"
          className="hidden"
          onChange={onFilesChosen}
          aria-label="选择课件文件"
        />
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          className="rounded-md bg-accent px-3.5 py-1.5 text-[13px] font-medium text-white"
        >
          上传课件
        </button>
      </div>

      {deleteError != null && (
        <div className="mb-3">
          <ErrorNotice error={deleteError} />
        </div>
      )}

      {uploads.length > 0 && (
        <div className="mb-3 grid gap-1.5 rounded-lg border border-border bg-surface px-5 py-3">
          {uploads.map((u, i) => (
            <div key={`${u.name}-${i}`} className="flex items-center gap-2 text-[13px]">
              <span className="min-w-0 flex-1 truncate text-ink2">{u.name}</span>
              {u.state === 'uploading' && <span className="text-ink3">上传中…</span>}
              {u.state === 'ok' && (
                <span className="text-success">已上传，等待解析（见下方列表）</span>
              )}
              {u.state === 'error' && <span className="text-error">{u.error}</span>}
            </div>
          ))}
        </div>
      )}

      {materials.isError && <ErrorNotice error={materials.error} />}

      {materials.isLoading && <p className="text-[13px] text-ink3">加载中…</p>}

      {!materials.isLoading && list.length === 0 && (
        <EmptyState title="这门课还没有资料">
          上传课件 PDF / PPTX，解析完成后会在这里显示页数与可搜索状态。
        </EmptyState>
      )}

      {list.length > 0 && (
        <section className="overflow-hidden rounded-lg border border-border bg-surface">
          {list.map((m) => (
            <div
              key={m.id}
              className="group flex items-center gap-4 border-t border-border px-5 py-3 first:border-t-0 hover:bg-bg focus-within:bg-bg"
            >
              <div className="min-w-0 flex-1">
                <Link
                  to={`/courses/${courseId}/materials/${m.id}`}
                  className="truncate text-[14px] font-semibold text-ink no-underline hover:text-accent"
                >
                  {m.filename}
                </Link>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[12.5px] text-ink3">
                  <span>{formatBytes(m.size_bytes)}</span>
                  {m.page_count != null && m.page_count > 0 && <span>{m.page_count} 页</span>}
                  {m.chunk_count > 0 && <span>{m.chunk_count} 个片段</span>}
                  {m.no_text_pages && m.no_text_pages.length > 0 && (
                    <span className="text-warning" title={`第 ${m.no_text_pages.join('、')} 页未提取到文本`}>
                      ⚠ 第 {m.no_text_pages.join('、')} 页无文本
                    </span>
                  )}
                  {m.status === 'failed' && m.error_code && (
                    <span className="text-error">{m.error_code}</span>
                  )}
                </div>
              </div>
              <StatusDot status={m.status} />
              <span className="flex flex-none gap-3 text-xs text-ink3 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                <button type="button" className="text-error" onClick={() => setDeleting(m)}>
                  删除
                </button>
              </span>
            </div>
          ))}
        </section>
      )}

      <ConfirmDialog
        open={deleting !== null}
        title={`删除「${deleting?.filename ?? ''}」？`}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
        onCancel={() => {
          setDeleting(null)
          setDeleteError(null)
        }}
      >
        材料的解析结果与片段会一并删除；若知识框架正引用它，后端会拒绝并提示。
      </ConfirmDialog>
    </div>
  )
}
