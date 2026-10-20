<template>
  <div class="settings-card">
    <h3 class="card-title">{{ title }}</h3>
    <p class="card-sub">{{ subtitle }}</p>

    <!-- 配置来源提示 -->
    <div class="source-banner" :class="source">
      <span v-if="source === 'runtime'">🟢 当前生效：前端保存的运行时配置</span>
      <span v-else-if="source === 'env'">🟡 当前生效：backend/.env 环境变量</span>
      <span v-else>⚪ 未配置{{ isVision ? '视觉模型' : '大模型' }}</span>
    </div>

    <div class="form-row">
      <label>
        API Base URL
        <span v-if="isVision" class="optional">可留空</span>
      </label>
      <input v-model="form.base_url" type="text" :placeholder="basePh" autocomplete="off" />
      <span class="form-hint">{{ baseHint }}</span>
    </div>

    <div class="form-row">
      <label>
        API Key
        <span v-if="isVision" class="optional">可留空</span>
      </label>
      <input v-model="form.api_key" type="password" placeholder="sk-..." autocomplete="off" />
      <span v-if="hasMaskedKey" class="form-hint">已脱敏显示，如不修改可留空</span>
    </div>

    <div class="form-row">
      <label>Model Name</label>
      <input v-model="form.model" type="text" :placeholder="modelPh" autocomplete="off" />
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

    <p class="token-hint">
      ⚠️ 连通测试会向模型发起一次最小请求（max_tokens=1{{ isVision ? '，并附带一张 32×32 测试图' : '' }}），<b>会消耗少量 token</b>。
    </p>

    <!-- 测试 / 保存结果 -->
    <div v-if="result" class="result-line" :class="result.ok ? 'ok' : 'err'">
      {{ result.message }}
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getLlmConfig, saveLlmConfig, testLlmConfig, resetLlmConfig } from '../api'

const props = defineProps({
  kind: { type: String, default: 'text' },   // text / vision
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
})

const isVision = computed(() => props.kind === 'vision')

const form = ref({ base_url: '', api_key: '', model: '' })
const source = ref('none')         // runtime / env / none
const saving = ref(false)
const testing = ref(false)
const result = ref(null)           // { ok, message }

// api_key 是否是脱敏值（含 *），用于提示用户
const hasMaskedKey = computed(() => form.value.api_key.includes('*'))

const basePh = computed(() =>
  isVision.value ? '留空则与文本模型共用' : 'https://api.deepseek.com')
const modelPh = computed(() =>
  isVision.value ? 'qwen3-vl-plus' : 'deepseek-chat')
const baseHint = computed(() => {
  if (isVision.value) return '留空则沿用文本模型的 Base URL，适合两家模型共用同一个聚合网关'
  return 'OpenAI 兼容接口地址，到 /v1 这一层即可，不要带 /chat/completions'
})

async function loadConfig() {
  try {
    const data = await getLlmConfig(props.kind)
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
  if (!form.value.model.trim()) return '请填写 Model Name'
  // 视觉模型的地址与 Key 允许留空（回落文本模型），文本模型必须自己填
  if (!isVision.value && !form.value.base_url.trim()) return '请填写 Base URL'
  return ''
}

async function onSave() {
  const err = validate()
  if (err) { result.value = { ok: false, message: err }; return }
  saving.value = true
  result.value = null
  try {
    const res = await saveLlmConfig(props.kind, form.value)
    result.value = res
    // 保存成功后刷新表单（拿到脱敏 Key 与新的来源标记）
    if (res.ok) await loadConfig()
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
    result.value = await testLlmConfig(props.kind, form.value)
  } catch (e) {
    result.value = { ok: false, message: e.message || '测试失败' }
  } finally {
    testing.value = false
  }
}

async function onReset() {
  const label = isVision.value ? '视觉模型' : '文本模型'
  if (!confirm(`确定清除运行时${label}配置，回退到 .env？`)) return
  try {
    const res = await resetLlmConfig(props.kind)
    result.value = { ok: true, message: res.message || '已恢复 .env 默认配置' }
    await loadConfig()
  } catch (e) {
    result.value = { ok: false, message: e.message || '恢复失败' }
  }
}

onMounted(loadConfig)

defineExpose({ reload: loadConfig })
</script>

<style scoped>
.settings-card {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
  box-shadow: var(--shadow-sm);
  margin-bottom: 16px;
}

.card-title { font-size: 15px; font-weight: 700; color: var(--text); margin-bottom: 4px; }
.card-sub { font-size: 12px; color: var(--text-light); margin-bottom: 14px; line-height: 1.6; }

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
.form-row label .optional {
  font-weight: 400;
  font-size: 11px;
  color: var(--text-light);
  margin-left: 4px;
}
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
.form-hint { display: block; font-size: 11px; color: var(--text-light); margin-top: 4px; line-height: 1.5; }

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
