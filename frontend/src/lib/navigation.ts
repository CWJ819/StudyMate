// 设置页是全局页面，但用户从哪里进入就应该能回到哪里（课程 tab、资料详情等）。
// 通过路由 state 传来源路径；直接打开 #/settings 或 state 非法时回退到课程列表。
import type { Location } from 'react-router'

export interface SettingsReturnState {
  returnTo: string
}

/** 当前页进入设置时要带的 state；已在设置页时沿用原来路，避免二次点击丢失 */
export function settingsLinkState(location: Location): SettingsReturnState | undefined {
  if (location.pathname === '/settings') {
    const returnTo = settingsReturnTo(location.state)
    return returnTo === '/' ? undefined : { returnTo }
  }
  return { returnTo: `${location.pathname}${location.search}${location.hash}` }
}

/** 读取并校验来路；只接受应用内路径，不接受 //host 这类协议相对地址 */
export function settingsReturnTo(state: unknown): string {
  if (typeof state !== 'object' || state === null) return '/'
  const value = (state as { returnTo?: unknown }).returnTo
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) return '/'
  if (value === '/settings' || value.startsWith('/settings?') || value.startsWith('/settings#')) {
    return '/'
  }
  return value
}
