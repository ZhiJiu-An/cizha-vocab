<template>
  <div class="app">
    <aside class="sidebar">
      <div class="logo">📖 DanCiJi</div>
      <nav>
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          :class="{ active: isActive(item.path) }"
        >
          <span class="ic">{{ item.icon }}</span>{{ item.title }}
        </router-link>
      </nav>
    </aside>

    <main class="main">
      <router-view />
    </main>

    <!-- 全局提示 -->
    <div class="toast-wrap">
      <div v-for="t in toastState.items" :key="t.id" class="toast" :class="t.type">
        {{ t.message }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { useRoute } from 'vue-router'
import { toastState } from './utils'

const route = useRoute()

const navItems = [
  { path: '/', icon: '🔍', title: '词典' },
  { path: '/new', icon: '📝', title: '新建' },
  { path: '/words', icon: '📚', title: '词库' },
  { path: '/tags', icon: '🏷️', title: '标签' },
]

// 「首页」需精确匹配；其余前缀匹配，使详情/编辑页仍高亮「词库」
function isActive(path) {
  if (path === '/') return route.path === '/'
  return route.path === path || route.path.startsWith(`${path}/`)
}
</script>
