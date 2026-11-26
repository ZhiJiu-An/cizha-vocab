import { describe, expect, it } from 'vitest'

import { parseSections, resolvePreset, trimIncomplete } from '../stream'

describe('parseSections', () => {
  it('按五段标记切分并保持顺序', () => {
    const raw = '【定名】词元【展开】token【详解】最小语义单元【例句】A token.【译文】词元'
    expect(parseSections(raw)).toEqual([
      { key: '定名', text: '词元' },
      { key: '展开', text: 'token' },
      { key: '详解', text: '最小语义单元' },
      { key: '例句', text: 'A token.' },
      { key: '译文', text: '词元' },
    ])
  })

  it('只有部分段时只返回已出现的段', () => {
    expect(parseSections('【定名】词元【展开】token')).toEqual([
      { key: '定名', text: '词元' },
      { key: '展开', text: 'token' },
    ])
  })

  it('空段落保留为空字符串', () => {
    expect(parseSections('【定名】【展开】x')).toEqual([
      { key: '定名', text: '' },
      { key: '展开', text: 'x' },
    ])
  })

  it('流式中途的未闭合标记不算段', () => {
    expect(parseSections('【定名】词元【译')).toEqual([{ key: '定名', text: '词元【译' }])
  })

  it('没有标记或空串返回空数组', () => {
    expect(parseSections('')).toEqual([])
    expect(parseSections('一段没有标记的文字')).toEqual([])
  })
})

describe('trimIncomplete', () => {
  it('去掉尾部被截断的半个标记', () => {
    expect(trimIncomplete('词元【译')).toBe('词元')
    expect(trimIncomplete('词元【')).toBe('词元')
  })

  it('完整标记与普通文本不受影响', () => {
    expect(trimIncomplete('词元【译文】x')).toBe('词元【译文】x')
    expect(trimIncomplete('  词元  ')).toBe('词元')
  })

  it('空值安全', () => {
    expect(trimIncomplete('')).toBe('')
    expect(trimIncomplete(undefined)).toBe('')
  })
})

describe('resolvePreset', () => {
  it('单词与短语沿用用户选择的领域', () => {
    expect(resolvePreset('token', 'cs')).toBe('cs')
    expect(resolvePreset('machine learning', 'medical')).toBe('medical')
  })

  it('整句一律走通用翻译', () => {
    expect(resolvePreset('This is a test sentence.', 'cs')).toBe('general')
    expect(resolvePreset('one two three four five six', 'cs')).toBe('general')
  })

  it('未选择领域时保持空串（由后端用模型卡提示词）', () => {
    expect(resolvePreset('token')).toBe('')
  })
})
