<template>
  <div class="settings-page">
    <h2 class="page-title">⚙️ 模型设置</h2>
    <p class="page-sub">切换大模型，无需重启服务。保存前会自动做连通性测试。</p>

    <div class="settings-card">
      <!-- 配置来源提示 -->
      <div class="source-banner" :class="source">
        <span v-if="source === 'runtime'">🟢 当前生效：前端保存的运行时配置</span>
        <span v-else-if="source === 'env'">🟡 当前生效：backend/.env 环境变量</span>
        <span v-else>⚪ 未配置大模型</span>
      </div>

      <div class="form-row">
        <label>API Base URL</label>
        <input
          v-model="form.base_url"
          type="text"
          placeholder="https://api.deepseek.com"
          autocomplete="off"
        />
        <span class="form-hint">OpenAI 兼容接口地址，到 /v1 这一层即可，不要带 /chat/completions</span>
      </div>

      <div class="form-row">
        <label>API Key</label>
        <input
          v-model="form.api_key"
          type="password"
          placeholder="sk-..."
          autocomplete="off"
        />
        <span v-if="hasMaskedKey" class="form-hint">已脱敏显示，如不修改可留空</span>
      </div>

      <div class="form-row">
        <label>Model Name</label>
        <input
          v-model="form.model"
          type="text"
          placeholder="deepseek-chat"
          autocomplete="off"
        />
      </div>

      <div class="form-actions">
        <button class="btn primary" :disabled="saving" @click="onSave">
          {{ saving ? '连通测试中…' : '保存并切换' }}
        </button>
        <button class="btn" :disabled="testing" @click="onTest">
          {{ testing ? '测试中…' : '仅测试连通' }}
        </button>
        <button v-if="source === 'runtime'" class="btn ghost" @click="onReset">
          恢复 .env 默认
        </button>
      </div>

      <p class="token-hint">⚠️ 连通测试会向模型发起一次最小请求（max_tokens=1），<b>会消耗少量 token</b>。</p>

      <!-- 测试 / 保存结果 -->
      <div v-if="result" class="result-line" :class="result.ok ? 'ok' : 'err'">
        {{ result.message }}
      </div>
    </div>

    <!-- 视觉模型说明 -->
    <div class="settings-card info">
      <h3>视觉模型（图片取词）</h3>
      <p>图片取词使用的视觉模型暂不支持前端切换，需在 <code>backend/.env</code> 中配置：</p>
      <ul>
        <li><code>LLM_VISION_MODEL</code> — 视觉模型名（如 qwen3-vl-plus）</li>
        <li><code>LLM_VISION_BASE_URL</code> / <code>LLM_VISION_API_KEY</code> — 可缺省，回落到上方文本模型配置</li>
      </ul>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getLlmConfig, saveLlmConfig, testLlmConfig, resetLlmConfig } from '../api'

const form = ref({ base_url: '', api_key: '', model: '' })
const source = ref('none')         // runtime / env / none
const saving = ref(false)
const testing = ref(false)
const result = ref(null)           // { ok, message }

// api_key 是否是脱敏值（含 *），用于提示用户
const hasMaskedKey = computed(() => form.value.api_key.includes('*'))

async function loadConfig() {
  try {
    const data = await getLlmConfig()
    form.value = {
      base_url: data.base_url || '',
      api_key: data.api_key || '',
      model: data.model || '',
    }
    source.value = data.source
  } catch (e) {
    result.value = { ok: false, message: '加载配置失败：' + e.message }
  }
}

function validate() {
  if (!form.value.base_url.trim()) return '请填写 Base URL'
  if (!form.value.model.trim()) return '请填写 Model Name'
  // api_key 允许为空（脱敏场景），但如果是全新配置则必填
  if (!form.value.api_key.trim() || hasMaskedKey.value) {
    if (source.value !== 'runtime') return '请填写 API Key'
  }
  return ''
}

async function onSave() {
  const err = validate()
  if (err) { result.value = { ok: false, message: err }; return }
  saving.value = true
  result.value = null
  try {
    const res = await saveLlmConfig(form.value)
    result.value = res
    if (res.ok) {
      source.value = 'runtime'
      // 保存成功后刷新表单的 api_key 为脱敏值
      await loadConfig()
    }
  } catch (e) {
    result.value = { ok: false, message: e.message || '保存失败' }
  } finally {
    saving.value = false
  }
}

async function onTest() {
  const err = validate()
  if (err) { result.value = { ok: false, message: err }; return }
  testing.value = true
  result.value = null
  try {
    const res = await testLlmConfig(form.value)
    result.value = res
  } catch (e) {
    result.value = { ok: false, message: e.message || '测试失败' }
  } finally {
    testing.value = false
  }
}

async function onReset() {
  if (!confirm('确定恢复 .env 默认配置？当前运行时配置将被清除。')) return
  try {
    await resetLlmConfig()
    result.value = { ok: true, message: '已恢复 .env 默认配置' }
    await loadConfig()
  } catch (e) {
    result.value = { ok: false, message: e.message || '恢复失败' }
  }
}

onMounted(loadConfig)
</script>

<style scoped>
.settings-page { max-width: 640px; margin: 0 auto; padding: 24px 16px; }
.page-title { font-size: 22px; font-weight: 700; color: var(--text); margin-bottom: 6px; }
.page-sub { color: var(--text-light); font-size: 13px; margin-bottom: 20px; }

.settings-card {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
  box-shadow: var(--shadow-sm);
  margin-bottom: 16px;
}
.settings-card.info { background: var(--bg-soft); }
.settings-card.info h3 { font-size: 15px; margin-bottom: 8px; }
.settings-card.info p { font-size: 13px; color: var(--text-light); margin-bottom: 8px; }
.settings-card.info ul { font-size: 13px; color: var(--text-light); padding-left: 20px; line-height: 1.8; }
.settings-card.info code { background: #e8e8e8; padding: 1px 5px; border-radius: 3px; font-size: 12px; }

.source-banner {
  font-size: 13px;
  padding: 8px 12px;
  border-radius: 8px;
  margin-bottom: 18px;
  font-weight: 500;
}
.source-banner.runtime { background: #e6f7ec; color: #1a7f37; }
.source-banner.env { background: #fff8e1; color: #b36b00; }
.source-banner.none { background: #fee; color: #c0392b; }

.form-row { margin-bottom: 16px; }
.form-row label { display: block; font-size: 13px; font-weight: 600; color: var(--text); margin-bottom: 6px; }
.form-row input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 14px;
  background: #fff;
  box-sizing: border-box;
}
.form-row input:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.15); }
.form-hint { display: block; font-size: 11px; color: var(--text-light); margin-top: 4px; }

.form-actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 8px; }
.btn {
  padding: 9px 18px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  border: 1px solid var(--border);
  background: #fff;
  color: var(--text);
  cursor: pointer;
  transition: all 0.15s;
}
.btn:hover:not(:disabled) { border-color: var(--primary); color: var(--primary); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn.primary { background: var(--primary); color: #fff; border-color: var(--primary); }
.btn.primary:hover:not(:disabled) { background: var(--primary-dark); color: #fff; }
.btn.ghost { background: transparent; color: var(--text-light); }

.token-hint { font-size: 12px; color: var(--text-light); margin-top: 14px; line-height: 1.6; }
.token-hint b { color: #b36b00; }

.result-line {
  margin-top: 16px;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
}
.result-line.ok { background: #e6f7ec; color: #1a7f37; }
.result-line.err { background: #fee; color: #c0392b; white-space: pre-wrap; word-break: break-all; }
</style>
