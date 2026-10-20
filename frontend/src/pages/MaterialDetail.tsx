// 材料详情：页级解析状态（GET /materials/{id}）
import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { getMaterial } from '../api/endpoints'
import { messageFor } from '../api/errors'
import { formatBytes, materialStatus, pageStatusLabel } from '../api/status'
import { ErrorNotice } from '../components/ErrorNotice'

export function MaterialDetailPage() {
  const { courseId, materialId } = useParams()
  const material = useQuery({
    queryKey: ['material', materialId],
    queryFn: () => getMaterial(materialId!),
    enabled: materialId !== undefined,
  })

  if (material.isError) return <ErrorNotice error={material.error} />
  if (material.isLoading || !material.data) return <p className="text-[13px] text-ink3">加载中…</p>

  const m = material.data
  const meta = materialStatus(m.status)

  return (
    <div>
      <p className="mb-2 text-[13px] text-ink3">
        <Link to={`/courses/${courseId}/materials`} className="text-accent no-underline">
          ← 返回资料列表
        </Link>
      </p>
      <div className="mb-4">
        <h1 className="break-all text-[22px] font-bold">{m.filename}</h1>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-ink2">
          <span className="flex items-center gap-1.5">
            <span className={`inline-block size-2 rounded-full ${meta.dot}`} />
            {meta.label}
          </span>
          <span>{formatBytes(m.size_bytes)}</span>
          {m.page_count != null && <span>{m.page_count} 页</span>}
          <span>{m.chunk_count} 个片段</span>
          {m.mime_type && <span className="text-ink3">{m.mime_type}</span>}
        </div>
        {m.error_code && (
          <p className="mt-2 max-w-xl rounded-md border border-error/40 bg-error-bg px-3 py-1.5 text-[13px] text-ink">
            解析失败：{messageFor(m.error_code) ?? m.error_code}
          </p>
        )}
        {m.no_text_pages && m.no_text_pages.length > 0 && (
          <p className="mt-2 rounded-md border border-warning-border bg-warning-bg px-3 py-1.5 text-[13px] text-ink">
            ⚠ 第 {m.no_text_pages.join('、')} 页未提取到文本（扫描图或纯图片页）
          </p>
        )}
      </div>

      <section className="overflow-hidden rounded-lg border border-border bg-surface">
        <div className="flex items-baseline gap-3 px-5 pb-2 pt-4">
          <h2 className="text-[15px] font-semibold">逐页解析</h2>
          <span className="text-[12.5px] text-ink3">文本预览为页首内容</span>
        </div>
        {m.pages.map((page) => (
          <div key={page.page_number} className="border-t border-border px-5 py-2.5">
            <div className="flex items-baseline gap-3 text-[13px]">
              <span className="w-16 flex-none font-mono text-ink3">第 {page.page_number} 页</span>
              <span
                className={
                  page.extraction_status === 'extracted'
                    ? 'text-success'
                    : page.extraction_status === 'empty'
                      ? 'text-ink3'
                      : 'text-warning'
                }
              >
                {pageStatusLabel(page)}
              </span>
              {page.error_code && <span className="text-error">{page.error_code}</span>}
            </div>
            {page.text_preview && (
              <p className="mt-1 line-clamp-2 whitespace-pre-wrap text-[12.5px] text-ink2">
                {page.text_preview}
              </p>
            )}
          </div>
        ))}
      </section>
    </div>
  )
}
