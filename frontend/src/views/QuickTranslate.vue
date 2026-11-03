<template>
  <div class="quick-root">
    <!-- 无边框窗口的拖动区 -->
    <header class="q-head" data-tauri-drag-region>
      <span class="q-mark">✳</span>
      <b>词札快查</b>
      <span class="q-kind">{{ mode === 'image' ? '截图取词' : '输入翻译' }}</span>
      <span class="q-spacer"></span>
      <button class="q-icon" title="关闭 (Esc)" @click="hideSelf">✕</button>
    </header>

    <div class="q-body">
      <div v-if="error" class="q-error">{{ error }}</div>

      <!-- 输入翻译 -->
      <div v-if="mode === 'text'" class="q-search">
        <span class="q-search-icon">⌕</span>
        <input
          ref="inputRef"
          v-model="keyword"
          class="q-input"
          placeholder="输入单词或短语，回车查询"
          @keydown.enter="doTranslate"
        >
        <button class="q-go" :disabled="!keyword.trim() || loading" @click="doTranslate">
          翻译
        </button>
      </div>

      <!-- 截图取词：预览 + 识别中 -->
      <div v-if="mode === 'image' && imageUrl" class="q-shot">
        <img :src="imageUrl" alt="截图预览">
        <span v-if="ocrLoading" class="q-shot-mask">识别中…</span>
      </div>

      <!-- 领域翻译结果（只展示紧凑的三段，完整内容去主窗口看） -->
      <div v-if="visibleSections.length" class="q-result">
        <div v-for="sec in visibleSections" :key="sec.key" class="q-sec">
          <span class="q-tag">{{ sec.label }}</span>
          <div class="q-text">{{ sec.text }}</div>
        </div>
        <span v-if="streaming" class="q-cursor">▍</span>
      </div>

      <!-- 截图取词结果 -->
      <div v-if="ocrTranslation" class="q-trans">
        <span class="q-trans-label">译文</span>
        <span>{{ ocrTranslation }}</span>
      </div>
      <div v-if="ocrWords.length" class="q-chips">
        <button
          v-for="w in ocrWords"
          :key="w.word"
          class="q-chip"
          :title="w.zh || `查询「${w.word}」`"
          @click="openInMain(w.word)"
        >
          {{ w.word }}<em v-if="w.zh">{{ w.zh }}</em>
        </button>
      </div>

      <div v-if="isEmpty" class="q-empty">
        {{ mode === 'image' ? '截图已就绪，正在等待识别结果…' : '输入一个词，回车看领域翻译。' }}
      </div>
    </div>

    <footer class="q-foot">
      <button v-if="currentWord" class="q-link" @click="openInMain(currentWord)">
        在主窗口查看完整结果 →
      </button>
      <span class="q-hint">Esc 关闭 · ⌥A 输入翻译 · ⌥S 截图取词</span>
    </footer>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'
import { extractWordsFromImage } from '../api'

// 同一份前端也会跑在浏览器里（npm run dev），非 Tauri 环境下 IPC 一律跳过
const isTauri = Boolean(window.__TAURI_INTERNALS__)

const mode = ref('text')
const keyword = ref('')
const error = ref('')
const imageUrl = ref('')
const inputRef = ref(null)

const loading = ref(false)
const streaming = ref(false)
const sections = ref([])
const currentWord = ref('')

const ocrLoading = ref(false)
const ocrTranslation = ref('')
const ocrWords = ref([])

const SECTION_META = { 定名: '中文定名', 展开: '缩写展开', 详解: '领域详解' }

let lastPayloadId = 0
let streamSeq = 0
let abortCtrl = null
let unlisten = null

const visibleSections = computed(() => {
  const map = {}
  for (const s of sections.value) map[s.key] = trimIncomplete(s.text)
  const out = []
  for (const key of ['定名', '展开', '详解']) {
    const text = map[key]
    if (text && text !== '无') out.push({ key, label: SECTION_META[key], text })
  }
  return out
})

const isEmpty = computed(
  () =>
    !error.value &&
    !visibleSections.value.length &&
    !ocrTranslation.value &&
    !ocrLoading.value &&
    !loading.value,
)

/* ===== 流式解析：与搜索页保持同一套五段格式 ===== */
function parseSections(raw) {
  const marks = []
  const re = /【(定名|展开|详解|例句|译文)】/g
  let m
  while ((m = re.exec(raw))) marks.push({ key: m[1], index: m.index, end: re.lastIndex })
  return marks.map((mark, i) => ({
    key: mark.key,
    text: raw.slice(mark.end, i + 1 < marks.length ? marks[i + 1].index : undefined),
  }))
}

function trimIncomplete(text) {
  return (text || '').replace(/【[^】]*$/, '').trim()
}

/* ===== 输入翻译 ===== */
async function doTranslate() {
  const word = keyword.value.trim()
  if (!word || loading.value) return
  error.value = ''
  currentWord.value = word
  ocrTranslation.value = ''
  ocrWords.value = []
  imageUrl.value = ''

  abortCtrl?.abort()
  abortCtrl = new AbortController()
  const seq = ++streamSeq
  sections.value = []
  loading.value = true
  streaming.value = true
  let raw = ''

  try {
    const resp = await fetch(`/api/translate/${encodeURIComponent(word)}`, {
      signal: abortCtrl.signal,
    })
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}))
      throw new Error(data.detail || `翻译请求失败 (${resp.status})`)
    }
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      if (seq !== streamSeq) return
      buf += decoder.decode(value, { stream: true })
      const events = buf.split('\n\n')
      buf = events.pop()
      for (const ev of events) {
        const line = ev.trim()
        if (!line.startsWith('data:')) continue
        const payload = line.slice(5).trim()
        if (payload === '[DONE]') continue
        let obj
        try {
          obj = JSON.parse(payload)
        } catch {
          continue
        }
        if (obj.error) throw new Error(obj.error)
        const delta = obj.choices?.[0]?.delta?.content || ''
        if (delta) {
          raw += delta
          sections.value = parseSections(raw)
        }
      }
    }
  } catch (e) {
    if (e.name !== 'AbortError' && seq === streamSeq) {
      error.value = e.message || '翻译失败'
    }
  } finally {
    if (seq === streamSeq) {
      loading.value = false
      streaming.value = false
    }
  }
}

/* ===== 截图取词 ===== */
async function runOcr(dataUrl) {
  ocrLoading.value = true
  ocrTranslation.value = ''
  ocrWords.value = []
  try {
    const blob = await (await fetch(dataUrl)).blob()
    const file = new File([blob], 'screenshot.png', { type: blob.type || 'image/png' })
    const res = await extractWordsFromImage(file)
    ocrTranslation.value = res.translation || ''
    ocrWords.value = res.words || []
    currentWord.value = res.original_text || ''
    if (!ocrTranslation.value && !ocrWords.value.length) {
      error.value = '未识别到文字，换个区域再试'
    }
  } catch (e) {
    error.value = e.message || '图片识别失败'
  } finally {
    ocrLoading.value = false
  }
}

/* ===== 打开载荷 ===== */
async function applyPayload(payload) {
  if (!payload || payload.id <= lastPayloadId) return
  lastPayloadId = payload.id

  abortCtrl?.abort()
  streamSeq++
  mode.value = payload.mode === 'image' ? 'image' : 'text'
  sections.value = []
  keyword.value = ''
  error.value = payload.error || ''
  ocrTranslation.value = ''
  ocrWords.value = []
  imageUrl.value = ''
  currentWord.value = ''
  loading.value = false
  streaming.value = false

  if (payload.image) {
    imageUrl.value = payload.image
    await runOcr(payload.image)
  }

  await nextTick()
  if (mode.value === 'text') inputRef.value?.focus()
}

async function openInMain(word) {
  const text = (word || '').trim()
  if (!text || !isTauri) return
  try {
    await invoke('open_main_query', { word: text })
  } catch (e) {
    error.value = String(e)
  }
}

async function hideSelf() {
  if (!isTauri) return
  try {
    await invoke('quick_hide')
  } catch {
    /* 浮窗已不在时忽略 */
  }
}

function onKeydown(e) {
  if (e.key === 'Escape') {
    e.preventDefault()
    hideSelf()
  }
}

onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  if (isTauri) {
    unlisten = await listen('quick-open', (e) => applyPayload(e.payload))
    try {
      const pending = await invoke('quick_get_pending')
      if (pending) applyPayload(pending)
    } catch {
      /* 首次打开时后端未必就绪 */
    }
  }
  nextTick(() => inputRef.value?.focus())
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  unlisten?.()
  abortCtrl?.abort()
})
</script>

<style scoped>
.quick-root {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #f7f8f5;
  overflow: hidden;
}

.q-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: #f0f5f0;
  border-bottom: 1px solid var(--border);
  user-select: none;
  cursor: default;
}
.q-mark { color: var(--primary); font-size: 16px; }
.q-head b { font-size: 13px; letter-spacing: 1px; color: var(--text); }
.q-kind {
  font-size: 11px;
  color: var(--primary);
  background: #e3ede5;
  border-radius: 999px;
  padding: 1px 8px;
}
.q-spacer { flex: 1; }
.q-icon {
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: 14px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 6px;
}
.q-icon:hover { background: #e6ede7; color: var(--text); }

.q-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.q-error {
  font-size: 12px;
  color: #b3541e;
  background: #fff4e8;
  border: 1px solid #f3d7bb;
  border-radius: 8px;
  padding: 8px 10px;
  line-height: 1.5;
}

.q-search {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 0 10px;
  box-shadow: var(--shadow);
}
.q-search-icon { color: var(--muted-2); }
.q-input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 14px;
  color: var(--text);
  padding: 10px 0;
  font-family: inherit;
}
.q-go {
  border: none;
  background: var(--primary);
  color: #fff;
  font-size: 12px;
  border-radius: 7px;
  padding: 5px 12px;
  cursor: pointer;
}
.q-go:disabled { background: #c8d3ca; cursor: default; }

.q-shot {
  position: relative;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--border);
  max-height: 84px;
  background: #fff;
}
.q-shot img { width: 100%; height: 84px; object-fit: cover; display: block; }
.q-shot-mask {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.82);
  font-size: 12px;
  color: var(--primary);
}

.q-result { display: flex; flex-direction: column; gap: 8px; }
.q-sec { display: flex; flex-direction: column; gap: 2px; }
.q-tag {
  align-self: flex-start;
  font-size: 10px;
  color: var(--primary);
  background: #eaf1eb;
  border-radius: 5px;
  padding: 1px 6px;
}
.q-text { font-size: 13px; line-height: 1.6; color: var(--text); white-space: pre-wrap; }
.q-cursor { color: var(--primary); font-size: 12px; }

.q-trans {
  font-size: 12px;
  line-height: 1.6;
  color: var(--text);
  background: #f1f5f1;
  border-radius: 8px;
  padding: 8px 10px;
  max-height: 92px;
  overflow-y: auto;
}
.q-trans-label {
  color: var(--primary);
  font-size: 11px;
  margin-right: 6px;
}

.q-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.q-chip {
  border: 1px solid #dce7dd;
  background: #fff;
  color: var(--text);
  border-radius: 999px;
  padding: 3px 10px;
  font-size: 12px;
  cursor: pointer;
  font-family: inherit;
}
.q-chip:hover { border-color: var(--primary); color: var(--primary); }
.q-chip em { font-style: normal; color: var(--muted); font-size: 11px; margin-left: 4px; }

.q-empty { font-size: 12px; color: var(--muted); text-align: center; padding: 18px 0; }

.q-foot {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  border-top: 1px solid var(--border);
  background: #fbfcf9;
}
.q-link {
  border: none;
  background: transparent;
  color: var(--primary);
  font-size: 12px;
  cursor: pointer;
  padding: 0;
  font-family: inherit;
}
.q-link:hover { text-decoration: underline; }
.q-hint { margin-left: auto; font-size: 11px; color: var(--muted-2); }
</style>
