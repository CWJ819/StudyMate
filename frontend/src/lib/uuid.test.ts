import { randomUuid } from './uuid'

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

test('安全上下文：优先使用原生 crypto.randomUUID', () => {
  const fake = {
    randomUUID: () => 'native-uuid',
    getRandomValues: () => {
      throw new Error('should not be called')
    },
  } as unknown as Crypto
  expect(randomUuid(fake)).toBe('native-uuid')
})

test('非安全上下文（无 randomUUID）：用 getRandomValues 拼出合法 v4 UUID', () => {
  const fake = {
    getRandomValues: (arr: Uint8Array) => {
      for (let i = 0; i < arr.length; i += 1) arr[i] = i * 7 + 3
      return arr
    },
  } as unknown as Crypto
  const uuid = randomUuid(fake)
  expect(uuid).toMatch(UUID_V4)
  // 确定性输入 → 确定性输出；版本位（4）与变体位（8/9/a/b）被正确改写
  expect(randomUuid(fake)).toBe(uuid)
})

test('真实 crypto：默认参数产出合法 v4 UUID', () => {
  expect(randomUuid()).toMatch(UUID_V4)
  expect(randomUuid()).not.toBe(randomUuid())
})
