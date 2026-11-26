import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  looksLikeSentence,
  nextReviewLabel,
  parseTags,
  relativeTime,
  stripTranslationMarker,
} from '../index'

const NOW = new Date(2026, 5, 15, 12, 0, 0)
const MINUTE = 60 * 1000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(NOW)
})

afterEach(() => {
  vi.useRealTimers()
})

/** 用本地时间构造，避免 ISO 字符串被按 UTC 解析导致日期偏移 */
const localIso = (y, m, d, h = 9) => new Date(y, m - 1, d, h, 0, 0).toISOString()

describe('parseTags', () => {
  it('去空格、去空项、保持顺序', () => {
    expect(parseTags(' 大模型, RAG ,, 向量 ')).toEqual(['大模型', 'RAG', '向量'])
    expect(parseTags('')).toEqual([])
    expect(parseTags(null)).toEqual([])
  })
})

describe('looksLikeSentence', () => {
  it('句末标点判定为整句', () => {
    expect(looksLikeSentence('This is a test.')).toBe(true)
    expect(looksLikeSentence('你好。')).toBe(true)
    expect(looksLikeSentence('Token?')).toBe(true)
  })

  it('英文词数达到 6 个也判定为整句', () => {
    expect(looksLikeSentence('one two three four five six')).toBe(true)
    expect(looksLikeSentence('machine learning model')).toBe(false)
  })

  it('单词与空串不是整句', () => {
    expect(looksLikeSentence('token')).toBe(false)
    expect(looksLikeSentence('   ')).toBe(false)
    expect(looksLikeSentence(null)).toBe(false)
  })
})

describe('stripTranslationMarker', () => {
  it('剥掉开头的【译文】标记', () => {
    expect(stripTranslationMarker('【译文】词元')).toBe('词元')
    expect(stripTranslationMarker('  【译文】  词元')).toBe('词元')
  })

  it('没有标记或空值原样返回', () => {
    expect(stripTranslationMarker('词元')).toBe('词元')
    expect(stripTranslationMarker('')).toBe('')
  })
})

describe('relativeTime', () => {
  it('按差值分档给文案', () => {
    const at = (ms) => new Date(NOW.getTime() - ms).toISOString()
    expect(relativeTime(at(30 * 1000))).toBe('刚刚')
    expect(relativeTime(at(5 * MINUTE))).toBe('5 分钟前')
    expect(relativeTime(at(3 * HOUR))).toBe('3 小时前')
    expect(relativeTime(at(2 * DAY))).toBe('2 天前')
    expect(relativeTime(at(61 * DAY))).toBe('2 个月前')
    expect(relativeTime(at(400 * DAY))).toBe('1 年前')
  })

  it('空值与非法时间返回空串', () => {
    expect(relativeTime('')).toBe('')
    expect(relativeTime(null)).toBe('')
    expect(relativeTime('not-a-date')).toBe('')
  })
})

describe('nextReviewLabel', () => {
  it('今天 / 明天 / N 天后', () => {
    expect(nextReviewLabel(localIso(2026, 6, 15, 1))).toBe('2026-06-15（今天）')
    expect(nextReviewLabel(localIso(2026, 6, 16))).toBe('2026-06-16（明天）')
    expect(nextReviewLabel(localIso(2026, 6, 18))).toBe('2026-06-18（3 天后）')
  })

  it('已过期的日期标出天数', () => {
    expect(nextReviewLabel(localIso(2026, 6, 13))).toBe('2026-06-13（已过期 2 天）')
  })

  it('空值与非法时间回落「未安排」', () => {
    expect(nextReviewLabel('')).toBe('未安排')
    expect(nextReviewLabel(null)).toBe('未安排')
    expect(nextReviewLabel('not-a-date')).toBe('未安排')
  })
})
