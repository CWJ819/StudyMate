// 轻量骨架条（纯 CSS animate-pulse，不引库）：统一替代裸「加载中…」文本。
// role=status + aria-label="加载中" 保留加载语义（读屏器可感知）；条宽错落模拟列表节奏。

/** 列表/卡片容器内的骨架行；rows 按内容密度调整，className 微调间距 */
export function SkeletonRows({ rows = 3, className = '' }: { rows?: number; className?: string }) {
  return (
    <div className={`grid gap-2.5 ${className}`} role="status" aria-label="加载中">
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          className="h-3.5 animate-pulse rounded bg-untested-bg"
          style={{ width: `${92 - (i % 4) * 17}%` }}
        />
      ))}
    </div>
  )
}
