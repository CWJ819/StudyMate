// 幂等键需要 UUID。crypto.randomUUID 只在安全上下文（HTTPS / localhost / 127.0.0.1）存在，
// 而 StudyMate 的部署形态包含受信内网 http 访问（README「已知限制」），必须提供
// 基于 getRandomValues 的 v4 fallback——否则内网用户点「提交答卷」会抛未捕获 TypeError。

/** 生成 UUID v4；`cryptoObj` 参数仅供测试注入 */
export function randomUuid(cryptoObj: Crypto = globalThis.crypto): string {
  if (typeof cryptoObj.randomUUID === 'function') {
    return cryptoObj.randomUUID()
  }
  const bytes = new Uint8Array(16)
  cryptoObj.getRandomValues(bytes)
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40 // version 4
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80 // variant 10xx
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}
