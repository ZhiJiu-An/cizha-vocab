import { reactive, watch } from 'vue'
import { getPrefs, savePrefs } from '../api'

/* 用户偏好：昵称、发音口音、学习提醒
 *
 * 桌面版后端用随机端口启动（--port 0），WebView 的 localStorage 按 origin
 * (scheme://host:port) 隔离，重启后等于换了一个存储空间，设置会全部回默认值。
 * 因此以 <data_dir>/prefs.json 为权威存储，localStorage 只作为同步缓存。
 */
const KEY = 'cizha_prefs'
const LEGACY_KEY = 'danciji_prefs'   // v0.14 前的 key，只读兼容，避免丢用户设置

const defaults = {
  nickname: '词札学习者',
  accent: 'us', // us / uk
  reminder: { enabled: false, time: '20:00', last_notified: '' },
}

function normalize(raw) {
  const data = raw && typeof raw === 'object' ? raw : {}
  return {
    ...defaults,
    ...data,
    reminder: { ...defaults.reminder, ...(data.reminder || {}) },
  }
}

function loadLocal() {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || localStorage.getItem(LEGACY_KEY) || '{}')
    return normalize(raw)
  } catch {
    return normalize({})
  }
}

export const prefs = reactive(loadLocal())

let remoteReady = false
let skipNextSave = false
let saveTimer = null

/** 启动时从后端读一次真实设置；失败则沿用本地缓存（浏览器单独跑时走这条） */
export async function loadPrefs() {
  // 回填数据会触发一次 watch，那次不该再写回后端
  skipNextSave = true
  try {
    Object.assign(prefs, normalize(await getPrefs()))
  } catch {
    /* 后端不可用时不阻塞启动 */
  } finally {
    remoteReady = true
    setTimeout(() => {
      skipNextSave = false
    }, 0)
  }
}

function scheduleSave(value) {
  clearTimeout(saveTimer)
  saveTimer = setTimeout(() => {
    savePrefs(JSON.parse(JSON.stringify(value))).catch(() => {
      /* 落盘失败不打断用户操作，下一次变更会重试 */
    })
  }, 400)
}

watch(
  prefs,
  (value) => {
    localStorage.setItem(KEY, JSON.stringify(value))
    if (remoteReady && !skipNextSave) scheduleSave(value)
  },
  { deep: true },
)

export const displayName = () => prefs.nickname.trim() || defaults.nickname
export const avatarText = () => displayName().slice(0, 1).toUpperCase()
