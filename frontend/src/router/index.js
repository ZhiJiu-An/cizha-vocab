import { createRouter, createWebHistory } from 'vue-router'

// 词库列表组件同时用于「首页」与「词库」
const WordList = () => import('../views/WordList.vue')

const routes = [
  { path: '/', name: 'Home', component: WordList },
  { path: '/words', name: 'Words', component: WordList },
  { path: '/new', name: 'New', component: () => import('../views/WordForm.vue') },
  { path: '/words/:id/edit', name: 'Edit', component: () => import('../views/WordForm.vue') },
  { path: '/words/:id', name: 'Detail', component: () => import('../views/WordDetail.vue') },
  { path: '/tags', name: 'Tags', component: () => import('../views/TagList.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
