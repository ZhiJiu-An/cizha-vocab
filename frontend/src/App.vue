<template>
  <!-- 桌面浮层（快查 / 截图选区）：只渲染页面本身，不套侧边栏与顶栏 -->
  <div v-if="isBare" class="bare-shell"><router-view /></div>
  <!-- 浮层窗口路由就绪前保持空白（透明），绝不渲染主界面 -->
  <div v-else-if="overlayBooting" class="bare-shell"></div>

  <div v-else class="app">
    <aside class="sidebar">
      <router-link to="/" class="logo">
        <span class="icon">✳</span>
        <b>词札<span>单词库</span></b>
      </router-link>
      <div class="workspace">PERSONAL WORKSPACE</div>
      <nav>
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          :class="{ active: isActive(item.path) }"
        >
          <span class="ic">{{ item.icon }}</span><label>{{ item.title }}</label>
          <!-- 复习到期数徽章 -->
          <span v-if="item.path === '/review' && dueCount > 0" class="nav-badge">{{ dueCount }}</span>
        </router-link>
      </nav>
      <div class="side-bottom">
        <div class="plant">✳</div>
        <strong>每天一点，词汇成林。</strong>
        <p>给好奇心留一点生长的空间。</p>
        <div class="profile"><span class="avatar">{{ avatar }}</span><div><b>{{ name }}</b><small>终身学习者</small></div></div>
      </div>
    </aside>

    <main class="main">
      <header class="app-header">
        <div><span>我的学习空间</span><i>/</i><b>{{ currentTitle }}</b></div>

        <!-- 顶栏全局搜索（v0.11）：任意页面直接搜词，不用先回首页。
             桌面版新增 ⌘K 聚焦，网页版仍以鼠标入口为主。 -->
        <form class="header-search" role="search" @submit.prevent="goSearch">
          <span class="hs-icon">⌕</span>
          <input
            ref="headerSearchRef"
            v-model="globalQuery"
            type="search"
            placeholder="搜索词条、术语…"
            aria-label="全局搜索词条"
          >
          <button type="submit" class="hs-go" aria-label="搜索">↵</button>
        </form>

        <div class="header-meta"><span>♧ 今日待复习 <b>{{ dueCount }}</b></span><span class="header-divider"></span><span>{{ today }}</span><span class="avatar small">{{ avatar }}</span></div>
      </header>
      <div class="page-content"><router-view /></div>
      <footer class="app-footer"><span>一点一滴，皆有回响。</span><span>MADE FOR YOUR CURIOUS MIND <b>✳</b></span></footer>
    </main>

    <!-- 全局提示 -->
    <div class="toast-wrap">
      <div v-for="t in toastState.items" :key="t.id" class="toast" :class="t.type">
        <span>{{ t.message }}</span>
        <button v-if="t.action" class="toast-act" @click="runToastAction(t)">
          {{ t.action.label }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { deliverReminder, dismissToast, toastState, toast } from './utils'
import { prefs, displayName, avatarText } from './utils/prefs'
import { effectiveInAppShortcuts, matchesCombo } from './utils/shortcuts'
import { getReviewOverview } from './api'

const route = useRoute()
const router = useRouter()
const dueCount = ref(0)
const globalQuery = ref('')
const headerSearchRef = ref(null)
// 当前窗口是否是桌面浮层（由 URL 决定，路由就绪与否都成立）
const overlayWindow =
  typeof window !== 'undefined' &&
  (window.location.pathname === '/quick' || window.location.pathname === '/shot')
const isQuick = computed(() => route.path === '/quick')
// 截图选区层同样不跑主界面逻辑（不能用快捷键切页、不弹提醒）
const isBare = computed(() => isQuick.value || route.path === '/shot')
// 浮层窗口在路由解析完成前保持空白，避免把主界面铺满整个屏幕
const overlayBooting = computed(() => overlayWindow && !isBare.value)
const name = computed(displayName)
const avatar = computed(avatarText)
const currentTitle = computed(() => ({ '/': '词典', '/words': '词库', '/review': '复习', '/stats': '统计', '/tags': '标签', '/settings': '设置', '/settings/general': '通用设置', '/settings/models': '模型配置', '/settings/shortcuts': '快捷键', '/new': '新建词条' }[route.path] || (route.path.includes('/edit') || route.path.match(/^\/words\/\d+$/) ? '词条详情' : '词典')))
const today = new Intl.DateTimeFormat('zh-CN', { weekday: 'long', month: 'long', day: 'numeric' }).format(new Date())

const navItems = [
  { path: '/', icon: '⌕', title: '词典' },
  { path: '/words', icon: '▤', title: '词库' },
  { path: '/review', icon: '◷', title: '复习' },
  { path: '/stats', icon: '▥', title: '统计' },
  { path: '/settings', icon: '⚙', title: '设置' },
]

// 「首页」需精确匹配；其余前缀匹配，使详情/编辑页仍高亮「词库」
function isActive(path) {
  if (path === '/') return route.path === '/'
  return route.path === path || route.path.startsWith(`${path}/`)
}

// 顶栏全局搜索（v0.11）：跳回词典页并把关键词交给它自动查询
function goSearch() {
  const q = globalQuery.value.trim()
  if (!q) return
  router.push({ path: '/', query: { q } })
  globalQuery.value = ''
}

/* ===== 应用内快捷键（桌面版）=====
   组合键来自 prefs.shortcuts.in_app，默认 ⌘K 聚焦搜索 / ⌘N 新建 / ⌘1~5 切页。
   保存、复习自评、关闭浮窗由各自页面处理（见 utils/shortcuts.js 的动作表）。 */
const shortcuts = computed(() => effectiveInAppShortcuts(prefs.shortcuts.in_app))
const NAV_ACTIONS = {
  nav_dict: '/',
  nav_words: '/words',
  nav_review: '/review',
  nav_stats: '/stats',
  nav_settings: '/settings',
}

function onShortcutKeydown(e) {
  if (overlayWindow) return
  if (matchesCombo(e, shortcuts.value.focus_search)) {
    e.preventDefault()
    headerSearchRef.value?.focus()
    headerSearchRef.value?.select()
    return
  }
  if (matchesCombo(e, shortcuts.value.new_word)) {
    e.preventDefault()
    router.push('/new')
    return
  }
  for (const [id, path] of Object.entries(NAV_ACTIONS)) {
    if (matchesCombo(e, shortcuts.value[id])) {
      e.preventDefault()
      router.push(path)
      return
    }
  }
}

// Toast 上的操作按钮（v0.11）：如删除后的「撤销」
async function runToastAction(item) {
  const action = item.action
  dismissToast(item.id)
  try {
    await action.handler()
  } catch (e) {
    toast(e.message || '操作失败', 'error')
  }
}

// 路由切换时刷新复习到期数徽章
// 返回是否刷新成功：首次提醒要等真实到期数拿到后再判断，否则会拿着初始 0
// 写入「今天已提醒」导致当天真正的提醒被吞掉（v0.13）。
async function refreshDue() {
  try {
    const ov = await getReviewOverview()
    dueCount.value = ov.due_today
    return true
  } catch {
    dueCount.value = 0
    return false
  }
}

// 学习提醒：页面保持打开时，到点后 1 小时内提醒一次，每天最多一次
// 「今天已提醒」跟着偏好一起落盘 —— localStorage 会随随机端口重置（v0.16）
function checkReminder() {
  const { enabled, time } = prefs.reminder
  if (!enabled) return
  const [h, m] = time.split(':').map(Number)
  const now = new Date()
  const nowMin = now.getHours() * 60 + now.getMinutes()
  const target = h * 60 + m
  if (nowMin < target || nowMin - target > 60) return
  const dayKey = `${now.toDateString()} ${time}`
  if (prefs.reminder.last_notified === dayKey) return
  prefs.reminder.last_notified = dayKey
  // v0.11：页面在后台时走系统通知，否则用应用内 toast（见 utils.deliverReminder）
  deliverReminder(
    dueCount.value > 0
      ? `今天还有 ${dueCount.value} 个词等着复习 🌱`
      : '今天还没有新词，去词典逛逛吧 🌱',
  )
}

let reminderTimer

onMounted(async () => {
  // 浮层窗口不跑主界面的复习提醒，避免多个窗口重复计时
  if (overlayWindow) return
  window.addEventListener('keydown', onShortcutKeydown)
  // 先拿到真实到期数再判断是否提醒；拉取失败则跳过本次，也不写提醒键
  if (await refreshDue()) checkReminder()
  reminderTimer = setInterval(checkReminder, 60_000)
})
onUnmounted(() => {
  window.removeEventListener('keydown', onShortcutKeydown)
  clearInterval(reminderTimer)
})
watch(() => route.path, refreshDue)
</script>
