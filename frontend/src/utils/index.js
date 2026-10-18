import { reactive } from 'vue'

/* ========= 轻量 Toast ========= */
export const toastState = reactive({ items: [] })

export function toast(message, type = 'info') {
  const id = Date.now() + Math.random()
  toastState.items.push({ id, message, type })
  setTimeout(() => {
    const i = toastState.items.findIndex((t) => t.id === id)
    if (i > -1) toastState.items.splice(i, 1)
  }, 2800)
}

/* ========= 标签字符串 ↔ 数组 ========= */
export function parseTags(raw) {
  return (raw || '')
    .split(',')
    .map((t) => t.trim())
    .filter(Boolean)
}

/* ========= 相对时间 ========= */
export function relativeTime(iso) {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const diff = Date.now() - then
  const min = 60 * 1000
  const hour = 60 * min
  const day = 24 * hour

  if (diff < min) return '刚刚'
  if (diff < hour) return `${Math.floor(diff / min)} 分钟前`
  if (diff < day) return `${Math.floor(diff / hour)} 小时前`
  if (diff < 30 * day) return `${Math.floor(diff / day)} 天前`
  if (diff < 365 * day) return `${Math.floor(diff / (30 * day))} 个月前`
  return `${Math.floor(diff / (365 * day))} 年前`
}

/* ========= 卡片类型（决定色条与徽章） ========= */
export function cardType(word) {
  if (word.has_abbr) {
    return word.api_meaning
      ? { cls: 'has-abbr', badge: 'badge-abbr', text: '缩写·有通用释义' }
      : { cls: 'has-abbr no-api', badge: 'badge-term', text: '缩写·纯术语' }
  }
  return { cls: 'no-abbr', badge: 'badge-word', text: '普通单词' }
}
