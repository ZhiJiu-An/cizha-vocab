/* 快捷键：默认表 / 按键解析 / 展示 / 校验
 *
 * 应用内组合键统一存成 "Mod+Shift+K"：
 *   Mod   = macOS ⌘ / Windows·Linux Ctrl
 *   Ctrl  = macOS 的 Control（独立于 ⌘）
 *   Alt / Shift / Esc / Space / 1 / Up ...
 * 全局快捷键交给 Rust，使用 Tauri 的 accelerator 语法（CmdOrCtrl+Shift+KeyC）。
 */

export const isMac = () => /Mac|iPhone|iPad/.test(navigator.platform || '')

/** 应用内动作目录。id 同时是 prefs.shortcuts.in_app 的键，改名要同步后端与调用点 */
export const IN_APP_ACTIONS = [
  { id: 'focus_search', group: '导航', label: '聚焦搜索', default: 'Mod+K' },
  { id: 'new_word', group: '导航', label: '新建词条', default: 'Mod+N' },
  { id: 'nav_dict', group: '导航', label: '打开词典', default: 'Mod+1' },
  { id: 'nav_words', group: '导航', label: '打开词库', default: 'Mod+2' },
  { id: 'nav_review', group: '导航', label: '打开复习', default: 'Mod+3' },
  { id: 'nav_stats', group: '导航', label: '打开统计', default: 'Mod+4' },
  { id: 'nav_settings', group: '导航', label: '打开设置', default: 'Mod+5' },
  { id: 'save_word', group: '编辑', label: '保存词条', default: 'Mod+S' },
  // 复习页的上下文快捷键：只在复习页生效，允许不带修饰键
  { id: 'review_flip', group: '复习', label: '翻面', default: 'Space', allowBare: true },
  { id: 'review_forget', group: '复习', label: '自评「忘记」', default: '1', allowBare: true },
  { id: 'review_fuzzy', group: '复习', label: '自评「模糊」', default: '2', allowBare: true },
  { id: 'review_remember', group: '复习', label: '自评「记住」', default: '3', allowBare: true },
  { id: 'close_quick', group: '浮层', label: '关闭快查浮窗', default: 'Esc', allowBare: true },
]

export const ACTION_BY_ID = Object.fromEntries(IN_APP_ACTIONS.map((a) => [a.id, a]))

export function defaultInAppShortcuts() {
  return Object.fromEntries(IN_APP_ACTIONS.map((a) => [a.id, a.default]))
}

/** 默认表 + 用户覆盖，缺项自动补齐（旧 prefs.json 也能用） */
export function effectiveInAppShortcuts(map) {
  return { ...defaultInAppShortcuts(), ...(map || {}) }
}

const MOD_ORDER = ['Mod', 'Ctrl', 'Alt', 'Shift']

function normalizeKeyName(value) {
  const raw = String(value || '').trim()
  if (!raw) return ''
  const low = raw.toLowerCase()
  if (low === 'esc' || low === 'escape') return 'Esc'
  if (low === 'space' || low === 'spacebar') return 'Space'
  if (low === 'enter' || low === 'return') return 'Enter'
  if (low === 'tab') return 'Tab'
  if (low === 'backspace') return 'Backspace'
  if (low === 'delete' || low === 'del') return 'Delete'
  if (low.startsWith('arrow')) return low.slice(5).replace(/^./, (c) => c.toUpperCase())
  if (/^f\d{1,2}$/.test(low)) return low.toUpperCase()
  if (raw.length === 1) return raw.toUpperCase()
  return raw
}

/** 归一化组合键；无法识别时返回空串 */
export function normalizeCombo(value) {
  if (typeof value !== 'string') return ''
  const parts = value.split('+').map((p) => p.trim()).filter(Boolean)
  if (!parts.length) return ''
  const key = normalizeKeyName(parts.pop())
  if (!key) return ''
  const mods = new Set()
  for (const part of parts) {
    const low = part.toLowerCase()
    if (['mod', 'cmd', 'command', 'meta', 'cmdorctrl', 'commandorcontrol'].includes(low)) mods.add('Mod')
    else if (['ctrl', 'control'].includes(low)) mods.add('Ctrl')
    else if (['alt', 'option'].includes(low)) mods.add('Alt')
    else if (low === 'shift') mods.add('Shift')
  }
  return [...MOD_ORDER.filter((m) => mods.has(m)), key].join('+')
}

/** 从 keydown 事件取出组合键；不满足录制条件时返回空串 */
export function comboFromEvent(e, { allowBare = false } = {}) {
  const key = keyFromEvent(e)
  if (!key) return ''
  const mac = isMac()
  const mods = []
  if (mac ? e.metaKey : e.ctrlKey) mods.push('Mod')
  if (mac && e.ctrlKey) mods.push('Ctrl')
  if (e.altKey) mods.push('Alt')
  if (e.shiftKey) mods.push('Shift')
  if (!mods.length) {
    if (!allowBare) return ''
    // 不带修饰键时只允许功能键 / 数字 / 空格等，避免录制出 "A" 抢输入
    if (!['Esc', 'Space', 'Enter', 'Tab', 'Backspace', 'Delete'].includes(key)
      && !/^\d$/.test(key) && !/^F\d{1,2}$/.test(key)) return ''
  }
  return normalizeCombo([...mods, key].join('+'))
}

/** 事件是否命中组合键（修饰键必须完全一致） */
export function matchesCombo(e, combo) {
  const normalized = normalizeCombo(combo)
  if (!normalized) return false
  const parts = normalized.split('+')
  const key = parts.pop()
  if (keyFromEvent(e) !== key) return false
  const mods = new Set(parts)
  const mac = isMac()
  const hasMod = mac ? e.metaKey : e.ctrlKey
  if (hasMod !== mods.has('Mod')) return false
  if (mac) {
    if (e.ctrlKey !== mods.has('Ctrl')) return false
  } else if (mods.has('Ctrl')) {
    return false
  }
  if (e.altKey !== mods.has('Alt')) return false
  if (e.shiftKey !== mods.has('Shift')) return false
  return true
}

function keyFromEvent(e) {
  if (e.code === 'Space') return 'Space'
  if (e.key === 'Escape') return 'Esc'
  if (e.key === 'Enter') return 'Enter'
  if (e.key === 'Tab') return 'Tab'
  if (e.key === 'Backspace') return 'Backspace'
  if (e.key === 'Delete') return 'Delete'
  if (e.key.startsWith('Arrow')) return e.key.slice(5)
  if (/^F\d{1,2}$/.test(e.key)) return e.key
  if (/^Key[A-Z]$/.test(e.code)) return e.code.slice(3)
  if (/^Digit\d$/.test(e.code)) return e.code.slice(5)
  if (e.key.length === 1) return e.key.toUpperCase()
  return ''
}

/** 展示成一段段键帽：['⌘','⇧','K'] / ['Ctrl','Shift','K'] */
export function comboTokens(combo) {
  const normalized = normalizeCombo(combo)
  if (!normalized) return []
  const mac = isMac()
  return normalized.split('+').map((token) => {
    if (token === 'Mod') return mac ? '⌘' : 'Ctrl'
    if (token === 'Ctrl') return mac ? '⌃' : 'Ctrl'
    if (token === 'Alt') return mac ? '⌥' : 'Alt'
    if (token === 'Shift') return mac ? '⇧' : 'Shift'
    if (token === 'Esc') return 'Esc'
    if (token === 'Space') return '空格'
    if (token === 'Up') return '↑'
    if (token === 'Down') return '↓'
    if (token === 'Left') return '←'
    if (token === 'Right') return '→'
    return token
  })
}

export function comboText(combo) {
  return comboTokens(combo).join(isMac() ? '' : '+')
}

/** 展示 Tauri accelerator（如 CmdOrCtrl+Shift+KeyC） */
export function acceleratorTokens(accelerator) {
  if (!accelerator) return []
  const mac = isMac()
  return accelerator.split('+').map((token) => {
    const low = token.trim().toLowerCase()
    if (['cmdorctrl', 'cmdorcontrol', 'commandorcontrol', 'commandorctrl'].includes(low)) return mac ? '⌘' : 'Ctrl'
    if (['cmd', 'command', 'super', 'meta'].includes(low)) return mac ? '⌘' : 'Super'
    if (['ctrl', 'control'].includes(low)) return mac ? '⌃' : 'Ctrl'
    if (['alt', 'option'].includes(low)) return mac ? '⌥' : 'Alt'
    if (low === 'shift') return mac ? '⇧' : 'Shift'
    if (/^key[a-z]$/.test(low)) return token.slice(3).toUpperCase()
    if (/^digit\d$/.test(low)) return token.slice(5)
    if (low === 'escape' || low === 'esc') return 'Esc'
    if (low === 'space') return mac ? '空格' : 'Space'
    if (low.startsWith('arrow')) {
      return { arrowup: '↑', arrowdown: '↓', arrowleft: '←', arrowright: '→' }[low] || token
    }
    return token
  })
}

export function acceleratorText(accelerator) {
  return acceleratorTokens(accelerator).join(isMac() ? '' : '+')
}

const SAFE_CODES = new Set([
  ...Array.from({ length: 26 }, (_, i) => `Key${String.fromCharCode(65 + i)}`),
  ...Array.from({ length: 10 }, (_, i) => `Digit${i}`),
  ...Array.from({ length: 12 }, (_, i) => `F${i + 1}`),
  'Space', 'Escape', 'Tab', 'Enter', 'Backspace', 'Delete',
  'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
  'Home', 'End', 'PageUp', 'PageDown',
  'Minus', 'Equal', 'Comma', 'Period', 'Slash', 'Semicolon', 'Quote',
  'BracketLeft', 'BracketRight', 'Backslash', 'Backquote',
])

/** 从 keydown 生成 Tauri accelerator；不满足「至少一个修饰键」时返回空串 */
export function acceleratorFromEvent(e) {
  if (!(e.metaKey || e.ctrlKey || e.altKey)) return ''
  const mac = isMac()
  const parts = []
  if (e.metaKey || (!mac && e.ctrlKey)) parts.push('CmdOrCtrl')
  if (mac && e.ctrlKey) parts.push('Ctrl')
  if (e.altKey) parts.push('Alt')
  if (e.shiftKey) parts.push('Shift')
  if (!SAFE_CODES.has(e.code)) return ''
  parts.push(e.code)
  return parts.join('+')
}

// 系统 / WebView 保留组合：录进去也抢不到，直接拦下
const RESERVED = new Set([
  'Mod+Q', 'Mod+W', 'Mod+R', 'Mod+Shift+R', 'Mod+Tab', 'Mod+Shift+Tab',
  'Mod+Alt+Esc', 'Ctrl+Alt+Delete',
  // 文本编辑常用键：局内快捷键占用后会破坏输入框
  'Mod+C', 'Mod+V', 'Mod+X', 'Mod+A', 'Mod+Z', 'Mod+Shift+Z', 'Mod+F',
])

/** 校验局内组合键；返回错误文案，空串表示可用 */
export function validateInAppCombo(combo, { id, map } = {}) {
  const normalized = normalizeCombo(combo)
  if (!normalized) return '请按下一个组合键'
  const action = ACTION_BY_ID[id]
  const parts = normalized.split('+')
  const key = parts.pop()
  const hasModifier = parts.length > 0
  if (!hasModifier && !action?.allowBare) return '至少需要一个修饰键（⌘ / ⌥ / ⇧）'
  if (!hasModifier && /^[A-Z]$/.test(key)) return '字母键需要配合修饰键'
  if (RESERVED.has(normalized)) return '这个组合被系统或编辑器占用了，换一个'
  for (const [otherId, otherCombo] of Object.entries(effectiveInAppShortcuts(map))) {
    if (otherId !== id && normalizeCombo(otherCombo) === normalized) {
      return `与「${ACTION_BY_ID[otherId]?.label || otherId}」冲突`
    }
  }
  return ''
}
