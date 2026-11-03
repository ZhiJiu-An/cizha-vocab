import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { loadPrefs } from './utils/prefs'
import './style.css'

const app = createApp(App)
app.use(router)

// 先取回持久化的偏好再挂载，避免首屏闪一下默认昵称 / 口音
loadPrefs().finally(() => app.mount('#app'))
