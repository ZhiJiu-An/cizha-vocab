import { looksLikeSentence, stripTranslationMarker } from './index'

/* 流式翻译的共享实现：主窗口搜索页与快查浮窗共用同一套
 * SSE 解析、五段切分与通用翻译判定，避免两处口径再次分叉。 */

/** 把五段标记切成 [{ key, text }]；流式过程中最后一段可能还没闭合 */
export function parseSections(raw) {
  const marks = []
  const re = /【(定名|展开|详解|例句|译文)】/g
  let m
  while ((m = re.exec(raw))) marks.push({ key: m[1], index: m.index, end: re.lastIndex })
  return marks.map((mark, i) => ({
    key: mark.key,
    text: raw.slice(mark.end, i + 1 < marks.length ? marks[i + 1].index : undefined),
  }))
}

/** 去掉流式中途被截断的尾部标记（如「【译」），避免闪现半截标签 */
export function trimIncomplete(text) {
  return (text || '').replace(/【[^】]*$/, '').trim()
}

/**
 * 决定本次翻译用哪个领域提示词：
 * 整句/整段一律走通用翻译；单词、短语才尊重用户选择的领域。
 */
export function resolvePreset(word, preferred = '') {
  return looksLikeSentence(word) ? 'general' : preferred
}

function generalSections(raw) {
  return raw.trim() ? [{ key: '译文', text: stripTranslationMarker(raw) }] : []
}

/**
 * 流式翻译一个词/句子，逐段回调。
 * @param {string} word
 * @param {object} [options]
 * @param {string} [options.preset] 用户选择的领域；空则按是否整句自动决定
 * @param {AbortSignal} [options.signal]
 * @param {(raw: string, sections: Array<{key: string, text: string}>) => void} [options.onDelta]
 * @returns {Promise<{ raw: string, general: boolean }>}
 */
export async function streamTranslate(word, { preset = '', signal, onDelta } = {}) {
  const presetKey = resolvePreset(word, preset)
  const general = presetKey === 'general'
  const query = presetKey ? `?preset=${encodeURIComponent(presetKey)}` : ''
  const resp = await fetch(`/api/translate/${encodeURIComponent(word)}${query}`, { signal })
  if (!resp.ok) {
    const data = await resp.json().catch(() => ({}))
    throw new Error(data.detail || `翻译请求失败 (${resp.status})`)
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  let raw = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const events = buf.split('\n\n')
    buf = events.pop()
    for (const ev of events) {
      const line = ev.trim()
      if (!line.startsWith('data:')) continue
      const payload = line.slice(5).trim()
      if (payload === '[DONE]') continue
      let obj
      try {
        obj = JSON.parse(payload)
      } catch {
        continue
      }
      if (obj.error) throw new Error(obj.error)
      const delta = obj.choices?.[0]?.delta?.content || ''
      if (!delta) continue
      raw += delta
      onDelta?.(raw, general ? generalSections(raw) : parseSections(raw))
    }
  }
  return { raw, general }
}
