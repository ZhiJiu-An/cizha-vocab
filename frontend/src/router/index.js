import { createRouter, createWebHistory } from 'vue-router'

// 词典搜索为默认首页
const WordList = () => import('../views/WordList.vue')

const routes = [
  { path: '/', name: 'Search', component: () => import('../views/Search.vue') },
  { path: '/words', name: 'Words', component: WordList },
  { path: '/new', name: 'New', component: () => import('../views/WordForm.vue') },
  { path: '/words/:id/edit', name: 'Edit', component: () => import('../views/WordForm.vue') },
  { path: '/words/:id', name: 'Detail', component: () => import('../views/WordDetail.vue') },
  { path: '/tags', name: 'Tags', component: () => import('../views/TagList.vue') },
  { path: '/review', name: 'Review', component: () => import('../views/Review.vue') },
  { path: '/stats', name: 'Stats', component: () => import('../views/Stats.vue') },
  { path: '/settings', name: 'Settings', component: () => import('../views/Settings.vue') },
  // 模型与提示词（v0.12）：从设置页进入，导航栏保持 5 项不变
  { path: '/settings/models', name: 'ModelSettings', component: () => import('../views/ModelSettings.vue') },
  // 兜底路由（P1-5）：没有它时未知 URL 会让主区域整片空白。
  // 重定向回首页（词典搜索），用户至少能继续用。
  { path: '/:pathMatch(.*)*', name: 'NotFound', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
