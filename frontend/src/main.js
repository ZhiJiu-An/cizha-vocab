import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { loadPrefs } from './utils/prefs'
import './style.css'

const app = createApp(App)
app.use(router)

// 先取回持久化的偏好、并等路由首屏解析完成再挂载：
// 选区 / 快查浮层窗口不会先渲染一下主界面（否则会全屏闪出侧边栏）
Promise.all([loadPrefs(), router.isReady().catch(() => {})]).finally(() => app.mount('#app'))
