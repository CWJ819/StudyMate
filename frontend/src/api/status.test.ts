// plan §7 组件：上传预检（纯函数部分）
import { materialStatus, pageStatusLabel, validateUploadFile } from './status'

const MB = 1024 * 1024

describe('validateUploadFile', () => {
  test('接受 .pdf 与 .pptx（大小写不敏感）', () => {
    expect(validateUploadFile({ name: 'a.pdf', size: 1 }, 10 * MB)).toBeNull()
    expect(validateUploadFile({ name: 'B.PPTX', size: 1 }, 10 * MB)).toBeNull()
  })

  test('拒绝不支持的扩展名', () => {
    expect(validateUploadFile({ name: '笔记.docx', size: 1 }, 10 * MB)).toContain('.pdf')
    expect(validateUploadFile({ name: '无扩展名', size: 1 }, 10 * MB)).toContain('只支持')
  })

  test('拒绝超出 max_upload_bytes 的文件（服务端上限为准）', () => {
    expect(validateUploadFile({ name: '大课件.pdf', size: 10 * MB + 1 }, 10 * MB)).toContain('上限')
    expect(validateUploadFile({ name: '正好达标.pdf', size: 10 * MB }, 10 * MB)).toBeNull()
  })

  test('拒绝空文件', () => {
    expect(validateUploadFile({ name: '空.pdf', size: 0 }, 10 * MB)).toContain('空')
  })
})

describe('状态回退', () => {
  test('未知材料状态显示原文（不猜标签）', () => {
    expect(materialStatus('weird_new_status').label).toBe('weird_new_status')
  })

  test('页状态：已提取带字数，未提取显示中文', () => {
    expect(
      pageStatusLabel({
        page_number: 1,
        extraction_status: 'extracted',
        error_code: null,
        text_preview: null,
        text_length: 520,
      }),
    ).toContain('520')
    expect(
      pageStatusLabel({
        page_number: 2,
        extraction_status: 'no_extractable_text',
        error_code: null,
        text_preview: null,
        text_length: 0,
      }),
    ).toBe('无可用文本')
  })
})
