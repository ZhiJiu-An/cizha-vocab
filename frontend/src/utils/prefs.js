import { reactive, watch } from 'vue'

/* 本地偏好设置：昵称、发音口音、学习提醒（纯前端，存 localStorage） */
const KEY = 'danciji_prefs'

const defaults = {
  nickname: '拾词学习者',
  accent: 'us', // us / uk
  reminder: { enabled: false, time: '20:00' },
}

function load() {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || '{}')
    return {
      ...defaults,
      ...raw,
      reminder: { ...defaults.reminder, ...(raw.reminder || {}) },
    }
  } catch {
    return { ...defaults, reminder: { ...defaults.reminder } }
  }
}

export const prefs = reactive(load())

watch(
  prefs,
  (val) => localStorage.setItem(KEY, JSON.stringify(val)),
  { deep: true },
)

export const displayName = () => prefs.nickname.trim() || defaults.nickname
export const avatarText = () => displayName().slice(0, 1).toUpperCase()
