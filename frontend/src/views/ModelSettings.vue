<template>
  <div class="models-page">
    <section class="intro">
      <div>
        <div class="eyebrow">MODELS &amp; PROMPTS</div>
        <h1>选模型，也选语气。</h1>
        <p class="subtitle">
          文本模型负责翻译与领域详解，视觉模型负责图片取词；每种类型各有一个默认模型。
        </p>
      </div>
      <button class="primary" @click="startCreate">＋ 新建模型</button>
    </section>

    <div class="models-layout">
      <!-- ===== 左：模型列表 ===== -->
      <aside class="model-list">
        <div class="list-head">
          <span>已配置 {{ models.length }} 个模型</span>
          <button class="link" :disabled="loading" @click="load()">刷新</button>
        </div>

        <div v-if="!models.length" class="list-empty">
          还没有模型。点右上角「新建模型」，填好地址与 Key 后保存即可。
        </div>

        <button
          v-for="m in models"
          :key="m.id"
          class="model-item"
          :class="{ active: selectedId === m.id }"
          @click="select(m.id)"
        >
          <div class="mi-top">
            <span class="mi-name">{{ m.name }}</span>
            <span v-if="m.role" class="mi-badge">默认</span>
          </div>
          <div class="mi-meta">
            <span class="mi-type" :class="m.type">{{ m.type === 'vision' ? '视觉' : '文本' }}</span>
            <span class="mi-model">{{ m.model || '未填模型名' }}</span>
          </div>
        </button>

        <p v-if="models.length" class="list-note">
          只有标了「默认」的模型会被翻译 / 图片取词使用。
        </p>
      </aside>

      <!-- ===== 右：详情编辑 ===== -->
      <section class="model-detail">
        <div v-if="!form" class="detail-empty">
          <span>✦</span>
          <p>选择左侧的模型查看详情，或新建一个。</p>
        </div>

        <template v-else>
          <header class="detail-head">
            <div>
              <h2>{{ isNew ? '新建模型' : form.name || form.model || '未命名模型' }}</h2>
              <p>{{ subtitle }}</p>
            </div>
            <div class="detail-actions">
              <button
                v-if="!isNew && !form.role"
                class="btn btn-outline"
                :disabled="busy"
                @click="makeDefault"
              >设为默认</button>
              <button v-if="!isNew" class="btn btn-ghost danger" :disabled="busy" @click="remove">
                删除
              </button>
            </div>
          </header>

          <div class="form-grid">
            <div class="field">
              <label>名称</label>
              <input v-model="form.name" type="text" placeholder="例如 DeepSeek 翻译" autocomplete="off" />
              <span class="hint">留空时用模型名代替。</span>
            </div>

            <div class="field">
              <label>模型类型</label>
              <div v-if="isNew" class="type-seg">
                <button :class="{ active: form.type === 'text' }" @click="setType('text')">文本模型</button>
                <button :class="{ active: form.type === 'vision' }" @click="setType('vision')">视觉模型</button>
              </div>
              <span v-else class="type-fixed" :class="form.type">
                {{ form.type === 'vision' ? '视觉模型 · 图片取词' : '文本模型 · 翻译 / 领域详解' }}
              </span>
            </div>
          </div>

          <div class="field">
            <label>API Base URL<span v-if="isVision" class="optional">可留空</span></label>
            <input v-model="form.base_url" type="text" :placeholder="basePlaceholder" autocomplete="off" />
            <span class="hint">{{ baseHint }}</span>
          </div>

          <div class="field">
            <label>API Key<span v-if="isVision" class="optional">可留空</span></label>
            <input v-model="form.api_key" type="password" placeholder="sk-..." autocomplete="off" />
            <span class="hint">{{ apiKeyHint }}</span>
          </div>

          <div class="field">
            <label>Model Name</label>
            <input v-model="form.model" type="text" :placeholder="modelPlaceholder" autocomplete="off" />
          </div>

          <!-- 提示词：仅文本模型可配 -->
          <div v-if="!isVision" class="prompt-block">
            <div class="prompt-head">
              <label>提示词</label>
              <div class="preset-seg">
                <button
                  v-for="p in presets"
                  :key="p.key"
                  :class="{ active: form.prompt_preset === p.key }"
                  @click="applyPreset(p)"
                >{{ p.label }}</button>
              </div>
            </div>
            <textarea
              v-model="form.prompt"
              rows="14"
              spellcheck="false"
              @input="onPromptInput"
            ></textarea>
            <span class="hint">
              五段标记 <b>【定名】【展开】【详解】【例句】【译文】</b> 与
              <code>{word}</code> 占位符必须保留，否则无法保存；语境与措辞可以随意改。
            </span>
          </div>

          <div v-else class="prompt-note">
            视觉模型使用内置的图片识别提示词（原文 + 译文 + 术语 JSON），无需在这里配置。
          </div>

          <div class="form-actions">
            <button class="btn btn-primary" :disabled="busy" @click="save">
              {{ saving ? '连通测试中…' : isNew ? '测试并添加' : '测试并保存' }}
            </button>
            <button class="btn btn-outline" :disabled="busy" @click="testOnly">
              {{ testing ? '测试中…' : '仅测试连通' }}
            </button>
          </div>

          <p class="token-hint">
            ⚠️ 保存与测试都会向模型发一次最小请求（max_tokens=1
            {{ isVision ? '，并附带一张 32×32 测试图' : '' }}），会消耗少量 token。
          </p>

          <div v-if="result" class="result-line" :class="result.ok ? 'ok' : 'err'">
            {{ result.message }}
          </div>
        </template>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  createModel,
  deleteModel,
  listModels,
  setDefaultModel,
  testModel,
  updateModel,
} from '../api'
import { toast } from '../utils'

const models = ref([])
const presets = ref([])
const selectedId = ref('')
const form = ref(null)
const isNew = ref(false)
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const result = ref(null)

const isVision = computed(() => form.value?.type === 'vision')
const busy = computed(() => saving.value || testing.value)
const subtitle = computed(() => {
  if (isNew.value) return '保存前会自动做一次连通测试，通过后立即生效。'
  if (form.value.role === 'default_text') return '当前默认文本模型 · 翻译与领域详解都会用它。'
  if (form.value.role === 'default_vision') return '当前默认视觉模型 · 图片取词会用它。'
  return '这张卡尚未设为默认，可在右上角切换。'
})

const basePlaceholder = computed(() =>
  isVision.value ? '留空则与默认文本模型共用' : 'https://api.deepseek.com')
const modelPlaceholder = computed(() =>
  isVision.value ? 'qwen3-vl-plus' : 'deepseek-chat')
const baseHint = computed(() =>
  isVision.value
    ? 'OpenAI 兼容地址。留空时沿用默认文本模型的 Base URL，适合两家共用同一个聚合网关。'
    : 'OpenAI 兼容接口地址，到 /v1 这一层即可，不要带 /chat/completions。')
const apiKeyHint = computed(() =>
  form.value?.api_key?.includes('*')
    ? '已脱敏显示。不修改可直接保存，后端会还原完整 Key。'
    : isVision.value
      ? '留空时沿用默认文本模型的 Key。'
      : '只保存在本地 backend/data/llm_config.json。')

function presetPrompt(key) {
  return presets.value.find((p) => p.key === key)?.prompt || ''
}

function blankForm() {
  return {
    name: '',
    type: 'text',
    base_url: '',
    api_key: '',
    model: '',
    enabled: true,
    prompt_preset: 'llm',
    prompt: presetPrompt('llm'),
  }
}

async function load(preferId = '') {
  loading.value = true
  try {
    const data = await listModels()
    models.value = data.models
    presets.value = data.presets
    const target = preferId
      || (models.value.some((m) => m.id === selectedId.value) ? selectedId.value : '')
      || models.value.find((m) => m.role)?.id
      || models.value[0]?.id
    if (target) select(target)
    else { selectedId.value = ''; form.value = null; isNew.value = false }
  } catch (e) {
    result.value = { ok: false, message: '加载模型列表失败：' + e.message }
  } finally {
    loading.value = false
  }
}

function select(id) {
  const card = models.value.find((m) => m.id === id)
  if (!card) return
  selectedId.value = id
  isNew.value = false
  result.value = null
  form.value = { ...card }
}

function startCreate() {
  selectedId.value = ''
  isNew.value = true
  result.value = null
  form.value = blankForm()
}

function setType(type) {
  if (!form.value || form.value.type === type) return
  form.value.type = type
  if (type === 'vision') {
    form.value.prompt = ''
    form.value.prompt_preset = 'custom'
  } else {
    form.value.prompt_preset = 'llm'
    form.value.prompt = presetPrompt('llm')
  }
}

function applyPreset(preset) {
  form.value.prompt_preset = preset.key
  if (preset.key !== 'custom') form.value.prompt = preset.prompt
}

function onPromptInput() {
  const current = presetPrompt(form.value.prompt_preset)
  if (form.value.prompt !== current) form.value.prompt_preset = 'custom'
}

function validate() {
  if (!form.value.model.trim()) return '请填写 Model Name'
  if (!isVision.value) {
    if (!form.value.base_url.trim()) return '请填写 Base URL'
    if (!form.value.api_key.trim()) return '请填写 API Key'
    if (!form.value.prompt.includes('{word}')) return '提示词里缺少 {word} 占位符'
    const missing = ['【定名】', '【展开】', '【详解】', '【例句】', '【译文】']
      .filter((marker) => !form.value.prompt.includes(marker))
    if (missing.length) return `提示词缺少分段标记：${missing.join('、')}`
  }
  return ''
}

async function save() {
  if (!form.value || busy.value) return
  const error = validate()
  if (error) { result.value = { ok: false, message: error }; return }

  saving.value = true
  result.value = null
  try {
    const payload = { ...form.value }
    const res = isNew.value
      ? await createModel(payload)
      : await updateModel(selectedId.value, payload)
    result.value = { ok: res.ok, message: res.message }
    if (res.ok) {
      toast(isNew.value ? '模型已添加' : '模型已保存', 'success')
      await load(res.model?.id || selectedId.value)
    }
  } catch (e) {
    result.value = { ok: false, message: e.message || '保存失败' }
  } finally {
    saving.value = false
  }
}

async function testOnly() {
  if (!form.value || busy.value) return
  const error = validate()
  if (error) { result.value = { ok: false, message: error }; return }

  testing.value = true
  result.value = null
  try {
    result.value = await testModel({ ...form.value, id: isNew.value ? null : selectedId.value })
  } catch (e) {
    result.value = { ok: false, message: e.message || '测试失败' }
  } finally {
    testing.value = false
  }
}

async function makeDefault() {
  if (!form.value || busy.value) return
  try {
    await setDefaultModel(selectedId.value)
    toast('已设为默认模型', 'success')
    await load(selectedId.value)
  } catch (e) {
    toast(e.message || '切换默认模型失败', 'error')
  }
}

async function remove() {
  if (!form.value || busy.value) return
  if (!confirm(`确定删除模型「${form.value.name || form.value.model}」？`)) return
  try {
    await deleteModel(selectedId.value)
    toast('模型已删除', 'success')
    selectedId.value = ''
    await load()
  } catch (e) {
    toast(e.message || '删除失败', 'error')
  }
}

onMounted(() => load())
</script>

<style scoped>
.models-page { max-width: 1120px; margin: 0 auto; }

.models-layout {
  display: grid;
  grid-template-columns: 282px minmax(0, 1fr);
  gap: 22px;
  align-items: start;
}

/* ---- 左侧列表 ---- */
.model-list {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 14px;
  box-shadow: var(--shadow-sm);
  position: sticky;
  top: 20px;
}
.list-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 4px 10px;
  font-size: 11px;
  color: var(--muted);
}
.list-head .link {
  border: 0;
  background: transparent;
  color: var(--primary);
  font-size: 11px;
  cursor: pointer;
  font-family: inherit;
  padding: 0;
}
.list-head .link:disabled { opacity: .5; cursor: default; }

.list-empty {
  font-size: 12px;
  color: var(--muted);
  line-height: 1.8;
  padding: 18px 10px;
  text-align: center;
}

.model-item {
  display: block;
  width: 100%;
  text-align: left;
  font-family: inherit;
  background: transparent;
  border: 1px solid transparent;
  border-left: 3px solid transparent;
  border-radius: 10px;
  padding: 11px 12px;
  margin-bottom: 4px;
  cursor: pointer;
  transition: background .16s, border-color .16s;
}
.model-item:hover { background: #f7faf5; }
.model-item.active {
  background: #f1f6ee;
  border-color: var(--border);
  border-left-color: var(--primary);
}
.mi-top { display: flex; align-items: center; gap: 8px; justify-content: space-between; }
.mi-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mi-badge {
  flex: 0 0 auto;
  font-size: 10px;
  color: #fff;
  background: var(--primary);
  border-radius: 20px;
  padding: 1px 7px;
}
.mi-meta {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 6px;
  font-size: 11px;
  color: var(--muted);
}
.mi-type {
  flex: 0 0 auto;
  border-radius: 4px;
  padding: 1px 5px;
  font-size: 10px;
  background: #e9f1e6;
  color: var(--primary);
}
.mi-type.vision { background: #fdf5e2; color: #a67c16; }
.mi-model { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.list-note {
  font-size: 10px;
  color: var(--muted-2);
  line-height: 1.7;
  padding: 10px 6px 2px;
  margin: 0;
}

/* ---- 右侧详情 ---- */
.model-detail {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 24px 26px 26px;
  box-shadow: var(--shadow-sm);
  min-height: 420px;
}
.detail-empty {
  height: 100%;
  min-height: 360px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--muted);
  font-size: 13px;
}
.detail-empty span { font-size: 26px; color: var(--primary-2); }

.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 18px;
  margin-bottom: 20px;
  border-bottom: 1px solid var(--border);
}
.detail-head h2 { font-size: 19px; font-weight: 600; margin: 0 0 5px; color: var(--text); }
.detail-head p { font-size: 11px; color: var(--muted); margin: 0; line-height: 1.6; }
.detail-actions { display: flex; gap: 6px; flex: 0 0 auto; }
.detail-actions .btn { font-size: 12px; padding: 7px 12px; }
.btn.danger { color: var(--danger); }
.btn.danger:hover:not(:disabled) { background: #fdf0f0; }

.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.field { margin-bottom: 16px; }
.field label,
.prompt-head label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 7px;
}
.field label .optional,
.prompt-head label .optional {
  font-weight: 400;
  font-size: 10px;
  color: var(--muted);
  margin-left: 5px;
}
.field input {
  width: 100%;
  box-sizing: border-box;
  font-family: inherit;
  font-size: 13px;
  color: var(--text);
  background: #fbfcf9;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  transition: border-color .2s, box-shadow .2s;
}
.field input:focus,
.prompt-block textarea:focus {
  outline: none;
  border-color: var(--primary-2);
  box-shadow: 0 0 0 3px rgba(52, 103, 79, .12);
}
.hint {
  display: block;
  font-size: 10px;
  color: var(--muted-2);
  line-height: 1.6;
  margin-top: 5px;
}
.hint b { color: var(--text-light); font-weight: 500; }
.hint code {
  background: #eef3eb;
  border-radius: 3px;
  padding: 0 3px;
  font-size: 10px;
}

.type-seg {
  display: inline-flex;
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}
.type-seg button {
  font-family: inherit;
  font-size: 12px;
  color: var(--muted);
  background: #fbfcf9;
  border: 0;
  padding: 9px 16px;
  cursor: pointer;
  transition: background .2s, color .2s;
}
.type-seg button + button { border-left: 1px solid var(--border); }
.type-seg button.active { background: var(--primary); color: #fff; }
.type-fixed {
  display: inline-block;
  font-size: 11px;
  color: var(--primary);
  background: #eef4eb;
  border-radius: 6px;
  padding: 7px 11px;
}
.type-fixed.vision { color: #a67c16; background: #fdf5e2; }

.prompt-block { margin-top: 4px; }
.prompt-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.prompt-head label { margin-bottom: 0; }
.preset-seg {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 5px;
}
.preset-seg button {
  font-family: inherit;
  font-size: 11px;
  color: var(--muted);
  background: #fbfcf9;
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 4px 11px;
  cursor: pointer;
  transition: all .18s;
}
.preset-seg button:hover { color: var(--primary); border-color: #c5d0c8; }
.preset-seg button.active {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}

.prompt-block textarea {
  width: 100%;
  box-sizing: border-box;
  resize: vertical;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  line-height: 1.75;
  color: var(--text);
  background: #fbfcf9;
  border: 1px solid var(--border);
  border-radius: 9px;
  padding: 12px 14px;
}

.prompt-note {
  margin-top: 4px;
  padding: 13px 15px;
  background: var(--bg-soft);
  border-radius: 9px;
  font-size: 11px;
  color: var(--text-light);
  line-height: 1.7;
}

.form-actions { display: flex; gap: 9px; flex-wrap: wrap; margin-top: 18px; }
.form-actions .btn { font-size: 12px; }
.token-hint { font-size: 10px; color: var(--muted-2); margin: 12px 0 0; line-height: 1.7; }

.result-line {
  margin-top: 14px;
  padding: 10px 13px;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.6;
}
.result-line.ok { background: #e9f5ee; color: #1a7f37; }
.result-line.err { background: #fdeeee; color: #c0392b; white-space: pre-wrap; word-break: break-all; }

@media (max-width: 900px) {
  .models-layout { grid-template-columns: 1fr; }
  .model-list { position: static; }
  .form-grid { grid-template-columns: 1fr; }
}
</style>
