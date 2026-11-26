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
      <div v-if="error" class="q-error">
        <span>{{ error }}</span>
        <button v-if="needsPermission" class="q-error-act" @click="openScreenRecordingSettings">
          打开屏幕录制设置
        </button>
      </div>

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

      <!-- 截图取词：不再展示图片，识别完成后文字直接进输入框 -->
      <div v-if="ocrLoading" class="q-dict-hint">正在识别截图中的文字…</div>

      <!-- 词典释义：命中的词/短语才显示；未收录时不占位，只保留大模型翻译 -->
      <div v-if="dictLoading || (dict && dict.found)" class="q-dict">
        <div class="q-block-head">📖 词典释义</div>
        <div v-if="dictLoading" class="q-dict-hint">查询词典中…</div>
        <template v-else>
          <div class="q-dict-word">
            <b>{{ dict.word }}</b>
            <span v-if="dict.phonetic_uk" class="q-phon">{{ dict.phonetic_uk }}</span>
            <span v-if="dict.phonetic_us" class="q-phon">{{ dict.phonetic_us }}</span>
          </div>
          <div v-if="dict.api_meaning" class="q-dict-mean">{{ dict.api_meaning }}</div>
          <div v-for="(ex, i) in dict.examples || []" :key="i" class="q-dict-ex">
            {{ ex.en }}<span v-if="ex.zh" class="q-dict-zh">{{ ex.zh }}</span>
          </div>
        </template>
      </div>
      <div v-if="dictError" class="q-dict-hint err">词典暂不可用：{{ dictError }}</div>

      <!-- 领域翻译结果（只展示紧凑的三段，完整内容去主窗口看） -->
      <div v-if="visibleSections.length" class="q-result">
        <div v-for="sec in visibleSections" :key="sec.key" class="q-sec">
          <span class="q-tag">{{ sec.label }}</span>
          <div class="q-text">{{ sec.text }}</div>
        </div>
        <span v-if="streaming" class="q-cursor">▍</span>
      </div>

      <div v-if="isEmpty" class="q-empty">
        输入单词或句子，回车翻译。
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
import { extractWordsFromImage, lookupDictionary } from '../api'
import { looksLikeSentence, stripTranslationMarker } from '../utils'
import { prefs } from '../utils/prefs'
import { effectiveInAppShortcuts, matchesCombo } from '../utils/shortcuts'

// 同一份前端也会跑在浏览器里（npm run dev），非 Tauri 环境下 IPC 一律跳过
const isTauri = Boolean(window.__TAURI_INTERNALS__)

const mode = ref('text')
const keyword = ref('')
const error = ref('')
// 截图取词缺少「屏幕录制」权限时，错误块里给出直达系统设置的按钮
const needsPermission = ref(false)
const inputRef = ref(null)

const loading = ref(false)
const streaming = ref(false)
const sections = ref([])
const currentWord = ref('')

const ocrLoading = ref(false)

const dict = ref(null)
const dictLoading = ref(false)
const dictError = ref('')

const SECTION_META = { 译文: '通用译文', 定名: '中文定名', 展开: '缩写展开', 详解: '领域详解' }

let lastPayloadId = 0
let streamSeq = 0
let dictSeq = 0
let abortCtrl = null
let unlisten = null

const visibleSections = computed(() => {
  const map = {}
  for (const s of sections.value) map[s.key] = trimIncomplete(s.text)
  const out = []
  for (const key of ['译文', '定名', '展开', '详解']) {
    const text = map[key]
    if (text && text !== '无') out.push({ key, label: SECTION_META[key], text })
  }
  return out
})

const isEmpty = computed(
  () =>
    !error.value &&
    !visibleSections.value.length &&
    !ocrLoading.value &&
    !loading.value &&
    !dictLoading.value &&
    !(dict.value && dict.value.found),
)

/* ===== 词典释义（目标词/短语命中才展示） ===== */
async function loadDictionary(word) {
  const text = (word || '').trim()
  const seq = ++dictSeq
  dict.value = null
  dictError.value = ''
  dictLoading.value = Boolean(text)
  if (!text) return
  try {
    const res = await lookupDictionary(text)
    if (seq !== dictSeq) return
    dict.value = res
  } catch (e) {
    if (seq !== dictSeq) return
    dictError.value = e.message || '词典查询失败'
  } finally {
    if (seq === dictSeq) dictLoading.value = false
  }
}

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
  needsPermission.value = false
  currentWord.value = word
  ocrLoading.value = false
  // 整句不做词典查询：省一次往返，直接等通用译文
  if (looksLikeSentence(word)) {
    dict.value = null
    dictLoading.value = false
    dictError.value = ''
  } else {
    loadDictionary(word)
  }

  abortCtrl?.abort()
  abortCtrl = new AbortController()
  const seq = ++streamSeq
  sections.value = []
  loading.value = true
  streaming.value = true
  let raw = ''
  // 整句 / 整段走通用翻译；前端按纯文本渲染，不依赖模型输出【译文】标记
  const general = looksLikeSentence(word)

  try {
    const preset = general ? '?preset=general' : ''
    const resp = await fetch(`/api/translate/${encodeURIComponent(word)}${preset}`, {
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
          sections.value = general
            ? raw.trim()
              ? [{ key: '译文', text: stripTranslationMarker(raw) }]
              : []
            : parseSections(raw)
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

/* ===== 截图取词：识别结果直接写进输入框，再走普通查询流程 ===== */
async function runOcr(dataUrl) {
  ocrLoading.value = true
  dictSeq++
  dict.value = null
  dictLoading.value = false
  dictError.value = ''
  try {
    const blob = await (await fetch(dataUrl)).blob()
    const file = new File([blob], 'screenshot.png', { type: blob.type || 'image/png' })
    const res = await extractWordsFromImage(file)
    const text = (res.original_text || '').trim()
    if (!text) {
      error.value = '未识别到文字，换个区域再试'
      return
    }
    // 图片不再展示：识别出的文字放进输入框，用户仍可编辑后再查
    keyword.value = text
    mode.value = 'text'
    ocrLoading.value = false
    await nextTick()
    inputRef.value?.focus()
    await doTranslate()
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
  needsPermission.value = Boolean(payload.needs_permission)
  currentWord.value = ''
  dictSeq++
  dict.value = null
  dictLoading.value = false
  dictError.value = ''
  loading.value = false
  streaming.value = false

  // 壳层端上 OCR 已识别出文字：直接填入输入框并翻译，不再上传图片
  if (payload.text) {
    keyword.value = String(payload.text).trim()
    mode.value = 'text'
    await nextTick()
    inputRef.value?.focus()
    await doTranslate()
    return
  }

  if (payload.image) {
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

// 直达「系统设置 → 隐私与安全性 → 屏幕录制」，授权后需重启词札
async function openScreenRecordingSettings() {
  if (!isTauri) return
  try {
    await invoke('open_screen_recording_settings')
  } catch (e) {
    error.value = String(e)
  }
}

function onKeydown(e) {
  const combo = effectiveInAppShortcuts(prefs.shortcuts.in_app).close_quick
  if (!matchesCombo(e, combo)) return
  e.preventDefault()
  hideSelf()
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
  dictSeq++
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
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}
.q-error-act {
  border: 1px solid #e0b98f;
  background: #fff;
  color: #9c4210;
  border-radius: 7px;
  padding: 4px 10px;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
}
.q-error-act:hover { border-color: #b3541e; }

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

.q-dict {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.q-block-head {
  font-size: 11px;
  color: var(--primary);
  letter-spacing: 0.5px;
}
.q-dict-hint { font-size: 12px; color: var(--muted); }
.q-dict-hint.err { color: #b3541e; }
.q-dict-word { display: flex; align-items: baseline; flex-wrap: wrap; gap: 8px; }
.q-dict-word b { font-size: 15px; color: var(--text); }
.q-phon { font-size: 11px; color: var(--muted); }
.q-dict-mean { font-size: 12px; line-height: 1.6; color: var(--text); white-space: pre-wrap; }
.q-dict-ex {
  font-size: 12px;
  line-height: 1.55;
  color: var(--text);
  border-left: 2px solid #dfe9e0;
  padding-left: 8px;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.q-dict-zh { font-size: 11px; color: var(--muted); }

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
