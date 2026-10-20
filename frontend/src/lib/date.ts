// 本地日期工具：后端的 exam_date / scheduled_date 都是 YYYY-MM-DD（无时区）

/** 本地今天的 YYYY-MM-DD */
export function todayISO(): string {
  return toISODate(new Date())
}

export function toISODate(d: Date): string {
  const m = `${d.getMonth() + 1}`.padStart(2, '0')
  const day = `${d.getDate()}`.padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

/** n 天后（本地）的 YYYY-MM-DD */
export function addDaysISO(iso: string, n: number): string {
  const d = fromISODate(iso)
  d.setDate(d.getDate() + n)
  return toISODate(d)
}

function fromISODate(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y!, m! - 1, d!)
}

/** 距离 iso 还有几天（同日为 0；过去为负） */
export function daysUntil(iso: string): number {
  const diff = fromISODate(iso).getTime() - fromISODate(todayISO()).getTime()
  return Math.round(diff / 86_400_000)
}

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

/** 「1月5日（周一）」 */
export function formatDateCN(iso: string): string {
  const d = fromISODate(iso)
  return `${d.getMonth() + 1}月${d.getDate()}日（${WEEKDAYS[d.getDay()]}）`
}

/** 「2026-01-12（周一）」 */
export function formatDateLong(iso: string): string {
  const d = fromISODate(iso)
  return `${toISODate(d)}（${WEEKDAYS[d.getDay()]}）`
}
