<template>
  <div class="app">
    <aside class="sidebar">
      <router-link to="/" class="logo">
        <span class="icon">✳</span>
        <b>拾词<span>Lexi</span></b>
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
             刻意不绑定快捷键 —— 快捷键只在标签页聚焦时有效，鼠标入口才是主路径。 -->
        <form class="header-search" role="search" @submit.prevent="goSearch">
          <span class="hs-icon">⌕</span>
          <input
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
import { getReviewOverview } from './api'

const route = useRoute()
const router = useRouter()
const dueCount = ref(0)
const globalQuery = ref('')
const name = computed(displayName)
const avatar = computed(avatarText)
const currentTitle = computed(() => ({ '/': '词典', '/words': '词库', '/review': '复习', '/stats': '统计', '/tags': '标签', '/settings': '设置', '/new': '新建词条' }[route.path] || (route.path.includes('/edit') || route.path.match(/^\/words\/\d+$/) ? '词条详情' : '词典')))
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
async function refreshDue() {
  try {
    const ov = await getReviewOverview()
    dueCount.value = ov.due_today
  } catch {
    dueCount.value = 0
  }
}

// 学习提醒：页面保持打开时，到点后 1 小时内提醒一次，每天最多一次
const REMIND_KEY = 'danciji_reminded_on'

function checkReminder() {
  const { enabled, time } = prefs.reminder
  if (!enabled) return
  const [h, m] = time.split(':').map(Number)
  const now = new Date()
  const nowMin = now.getHours() * 60 + now.getMinutes()
  const target = h * 60 + m
  if (nowMin < target || nowMin - target > 60) return
  const dayKey = `${now.toDateString()} ${time}`
  if (localStorage.getItem(REMIND_KEY) === dayKey) return
  localStorage.setItem(REMIND_KEY, dayKey)
  // v0.11：页面在后台时走系统通知，否则用应用内 toast（见 utils.deliverReminder）
  deliverReminder(
    dueCount.value > 0
      ? `今天还有 ${dueCount.value} 个词等着复习 🌱`
      : '今天还没有新词，去词典逛逛吧 🌱',
  )
}

let reminderTimer

onMounted(() => {
  refreshDue()
  checkReminder()
  reminderTimer = setInterval(checkReminder, 60_000)
})
onUnmounted(() => clearInterval(reminderTimer))
watch(() => route.path, refreshDue)
</script>
