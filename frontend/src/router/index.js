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
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
