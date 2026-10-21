<template>
  <div class="settings-page">
    <section class="intro">
      <div>
        <div class="eyebrow">PREFERENCES &amp; MODELS</div>
        <h1>调一调，更顺手。</h1>
        <p class="subtitle">昵称、发音与提醒保存在本地；模型配置保存前会自动做连通性测试。</p>
      </div>
    </section>

    <!-- ===== 个人资料 ===== -->
    <section class="settings-group">
      <div class="group-head">
        <h3>个人资料</h3>
        <p>昵称会显示在左上角与顶部栏。</p>
      </div>
      <div class="settings-card">
        <div class="set-row">
          <div class="set-info">
            <b>昵称</b>
            <small>最多 16 个字符，留空则显示「拾词学习者」</small>
          </div>
          <input
            v-model="prefs.nickname"
            class="set-input"
            maxlength="16"
            placeholder="拾词学习者"
          />
        </div>
      </div>
    </section>

    <!-- ===== 发音偏好 ===== -->
    <section class="settings-group">
      <div class="group-head">
        <h3>发音偏好</h3>
        <p>发音功能即将上线，先选好你习惯的口音。</p>
      </div>
      <div class="settings-card">
        <div class="set-row">
          <div class="set-info">
            <b>口音</b>
            <small>卡片与详情页的音标会优先展示所选口音</small>
          </div>
          <div class="seg">
            <button :class="{ active: prefs.accent === 'uk' }" @click="setAccent('uk')">英式</button>
            <button :class="{ active: prefs.accent === 'us' }" @click="setAccent('us')">美式</button>
          </div>
        </div>
      </div>
    </section>

    <!-- ===== 学习提醒 ===== -->
    <section class="settings-group">
      <div class="group-head">
        <h3>学习提醒</h3>
        <p>
          到点提醒你今天还有多少词等着复习。页面在后台时用系统通知
          （需在浏览器弹窗里允许通知），页面可见时用应用内提示。
        </p>
      </div>
      <div class="settings-card">
        <div class="set-row">
          <div class="set-info">
            <b>每日提醒</b>
            <small>{{ prefs.reminder.enabled ? `每天 ${prefs.reminder.time} 提醒你复习` : '当前已关闭' }}</small>
          </div>
          <button
            class="toggle"
            :class="{ on: prefs.reminder.enabled }"
            :aria-pressed="prefs.reminder.enabled"
            @click="toggleReminder"
          ></button>
        </div>
        <div v-if="prefs.reminder.enabled" class="set-row">
          <div class="set-info">
            <b>提醒时间</b>
          </div>
          <input v-model="prefs.reminder.time" type="time" class="set-input time" />
        </div>
      </div>
    </section>

    <!-- ===== 模型配置 ===== -->
    <div class="group-head">
      <h3>模型配置</h3>
      <p>切换大模型，无需重启服务。</p>
    </div>

    <!-- 默认收起：只显示当前模型摘要 + 入口按钮，避免设置页被大段表单淹没 -->
    <div v-if="!modelEditorOpen" class="model-collapsed">
      <div class="mc-summary">
        <div class="mc-item">
          <span class="mc-label">文本模型</span>
          <span class="mc-value">{{ textModel || '未配置（使用 .env 默认）' }}</span>
        </div>
        <div class="mc-item">
          <span class="mc-label">视觉模型</span>
          <span class="mc-value">{{ visionModel || '未配置（与文本模型共用）' }}</span>
        </div>
      </div>
      <button class="btn btn-primary" @click="modelEditorOpen = true">⚙ 修改模型配置</button>
    </div>

    <template v-else>
      <!-- 文本模型：翻译、领域详解 -->
      <ModelConfigCard
        kind="text"
        title="文本模型"
        subtitle="用于单词翻译与领域详解的生成。"
      />

      <!-- 视觉模型：图片取词 -->
      <ModelConfigCard
        kind="vision"
        title="视觉模型（图片取词）"
        subtitle="用于识别截图里的术语。模型名必填；Base URL 与 API Key 留空则与文本模型共用，切换后立即生效。"
        class="vision-card"
      />

      <div style="text-align: center; margin-top: 14px">
        <button class="btn btn-ghost" @click="modelEditorOpen = false">收起</button>
      </div>
    </template>

    <!-- 配置小抄 -->
    <div class="settings-card info">
      <h3>配置小抄</h3>
      <ul>
        <li>地址填到 <code>/v1</code> 这一层，不要带 <code>/chat/completions</code>。</li>
        <li>DeepSeek 官方 API 没有视觉模型，视觉模型需另配一家（如阿里百炼 <code>qwen3-vl-plus</code>、智谱 <code>glm-4v</code>）。</li>
        <li>两套配置独立保存于 <code>backend/data/llm_config.json</code>，优先于 <code>backend/.env</code>；点「恢复 .env 默认」只清除当前这张卡片。</li>
        <li>「连通测试会消耗少量 token」：每次点保存或测试都会真实调用一次模型。</li>
      </ul>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import ModelConfigCard from '../components/ModelConfigCard.vue'
import { getLlmConfig } from '../api'
import { prefs } from '../utils/prefs'
import { toast } from '../utils'

const modelEditorOpen = ref(false)
const textModel = ref('')
const visionModel = ref('')

onMounted(async () => {
  try {
    const [t, v] = await Promise.all([getLlmConfig('text'), getLlmConfig('vision')])
    textModel.value = t.model || ''
    visionModel.value = v.model || ''
  } catch {
    /* 配置读取失败不阻塞设置页 */
  }
})

function setAccent(accent) {
  if (prefs.accent === accent) return
  prefs.accent = accent
  toast(`发音偏好已设为${accent === 'uk' ? '英式' : '美式'}`, 'success')
}

async function toggleReminder() {
  const next = !prefs.reminder.enabled
  if (next && 'Notification' in window && Notification.permission === 'default') {
    try {
      await Notification.requestPermission()
    } catch {
      /* 用户拒绝也不阻断开关 */
    }
  }
  prefs.reminder.enabled = next
  toast(next ? `已开启每日提醒（${prefs.reminder.time}）` : '已关闭学习提醒', 'success')
}
</script>

<style scoped>
.settings-page { max-width: 640px; margin: 0 auto; padding: 24px 16px; }

.settings-group { margin-bottom: 26px; }
.group-head { margin-bottom: 10px; }
.group-head h3 { font-size: 14px; font-weight: 600; color: var(--text); }
.group-head p { font-size: 11px; color: var(--muted); margin-top: 4px; }

/* 视觉模型卡片用左边框颜色区分，避免两张卡片长得一模一样 */
.vision-card {
  border-left: 3px solid var(--yellow);
}

.settings-card {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 6px 20px;
  box-shadow: var(--shadow-sm);
  margin-bottom: 16px;
}
.settings-card.info { padding: 20px; background: var(--bg-soft); }
.settings-card.info h3 { font-size: 15px; margin-bottom: 8px; }
.settings-card.info ul { font-size: 13px; color: var(--text-light); padding-left: 20px; line-height: 1.8; }
.settings-card.info code { background: #e8ede4; padding: 1px 5px; border-radius: 3px; font-size: 12px; }

/* 模型配置收起态：只显示当前模型名 + 修改按钮 */
.model-collapsed {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 20px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: var(--shadow-sm);
}
.mc-summary { display: flex; flex-direction: column; gap: 6px; }
.mc-item { font-size: 13px; }
.mc-label { color: var(--muted); margin-right: 8px; }
.mc-value { color: var(--text); font-weight: 500; }

.set-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 0;
  border-bottom: 1px solid var(--border);
}
.set-row:last-child { border-bottom: 0; }
.set-info b { display: block; font-size: 13px; font-weight: 500; color: var(--text); }
.set-info small { display: block; font-size: 11px; color: var(--muted); margin-top: 5px; }

.set-input {
  font-family: inherit;
  font-size: 12px;
  color: var(--text);
  background: #fbfcf9;
  border: 1px solid var(--border);
  border-radius: 7px;
  padding: 9px 12px;
  width: 180px;
  transition: border-color .2s, box-shadow .2s;
}
.set-input:focus {
  outline: none;
  border-color: var(--primary-2);
  box-shadow: 0 0 0 3px rgba(52, 103, 79, .12);
}
.set-input.time { width: 130px; }

.seg { display: flex; border: 1px solid var(--border); border-radius: 7px; overflow: hidden; }
.seg button {
  font-family: inherit;
  font-size: 12px;
  color: var(--muted);
  background: #fbfcf9;
  border: 0;
  padding: 9px 16px;
  cursor: pointer;
  transition: background .2s, color .2s;
}
.seg button + button { border-left: 1px solid var(--border); }
.seg button.active { background: var(--primary); color: #fff; }

.toggle {
  width: 38px;
  height: 22px;
  flex: 0 0 auto;
  border: 0;
  border-radius: 15px;
  background: #d5ddd0;
  position: relative;
  cursor: pointer;
  transition: background .2s;
}
.toggle.on { background: var(--primary); }
.toggle:after {
  content: '';
  position: absolute;
  left: 3px;
  top: 3px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #fff;
  transition: left .2s;
}
.toggle.on:after { left: 19px; }
</style>
