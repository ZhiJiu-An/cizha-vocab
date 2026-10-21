import { reactive } from 'vue'

/* ========= 轻量 Toast ========= */
export const toastState = reactive({ items: [] })

/**
 * 轻量 Toast
 * @param {string} message 文案
 * @param {'info'|'success'|'error'} type 类型
 * @param {{label: string, handler: Function}} [action] 可选操作按钮（如「撤销」），
 *        带操作时停留更久，让用户来得及点
 */
export function toast(message, type = 'info', action = null) {
  const id = Date.now() + Math.random()
  toastState.items.push({ id, message, type, action })
  setTimeout(() => dismissToast(id), action ? 8000 : 2800)
  return id
}

export function dismissToast(id) {
  const i = toastState.items.findIndex((t) => t.id === id)
  if (i > -1) toastState.items.splice(i, 1)
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

/* ========= 复习档位（与后端 STAGES_DAYS 保持一致）========= */
export const STAGE_DAYS = [1, 2, 4, 7, 15, 30]

export function stageDays(stage) {
  return STAGE_DAYS[stage] ?? STAGE_DAYS[0]
}

/** 下次复习日期的人话描述：2026-10-25（3 天后）/（今天）/（已过期 2 天） */
export function nextReviewLabel(iso) {
  if (!iso) return '未安排'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '未安排'

  const startOf = (x) => {
    const y = new Date(x)
    y.setHours(0, 0, 0, 0)
    return y
  }
  const diffDays = Math.round((startOf(d) - startOf(new Date())) / 86400000)
  const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

  if (diffDays < 0) return `${date}（已过期 ${-diffDays} 天）`
  if (diffDays === 0) return `${date}（今天）`
  if (diffDays === 1) return `${date}（明天）`
  return `${date}（${diffDays} 天后）`
}

/* ========= 学习提醒投递（v0.11）========= */
/**
 * 到点提醒怎么送到用户眼前：
 * - 页面在后台、且用户已授权桌面通知 → 用系统通知（这正是提醒存在的意义：
 *   你没盯着这个页面的时候才需要被提醒）；
 * - 其余情况（页面可见 / 未授权 / 浏览器不支持）→ 回落应用内 toast。
 * 通知构造失败也回落 toast，绝不因为通知异常吞掉提醒。
 */
export function deliverReminder(message, title = '拾词 Lexi · 学习提醒') {
  const supported = typeof Notification !== 'undefined'
  const granted = supported && Notification.permission === 'granted'
  const hidden = typeof document !== 'undefined' && document.hidden

  if (hidden && granted) {
    try {
      new Notification(title, { body: message, tag: 'danciji-reminder' })
      return 'notification'
    } catch {
      /* 落到下面的 toast */
    }
  }
  toast(message, 'info')
  return 'toast'
}
