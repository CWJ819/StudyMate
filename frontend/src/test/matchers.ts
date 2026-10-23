/** 视觉打磨轮把数字包进等宽 span，断言不能再按「直接文本」命中；
 * 按 textContent 在最深层匹配：元素自身匹配且没有任何子元素匹配 */
export function deepestText(re: RegExp) {
  return (_: string, el: Element | null): boolean =>
    el != null &&
    re.test(el.textContent ?? '') &&
    !Array.from(el.children).some((c) => re.test(c.textContent ?? ''))
}
