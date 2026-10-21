<template>
  <div>
    <!-- ===== 搜索区 ===== -->
    <section class="intro">
      <div>
        <div class="eyebrow">EXPLORE A WORLD OF WORDS</div>
        <h1>让每个单词，慢慢生根。</h1>
        <p class="subtitle">同时查看词典通用释义与 AI 领域解读，遇到值得记住的词，一键收进自己的词库。</p>
      </div>
      <span class="intro-note">Stay curious. Keep growing.</span>
    </section>

    <div class="search-hero">
      <div class="search-box">
        <span class="search-icon">⌕</span>
        <input
          v-model="keyword"
          placeholder="搜索单词、短语或领域缩写，开启一次新的发现…"
          autofocus
          @keydown.enter="doSearch"
          @paste="onPaste"
        >
        <span class="key">⌘ K</span>
        <button class="ocr-btn" :disabled="ocrLoading" @click="pickImage">
          {{ ocrLoading ? '识别中…' : '📷 图片取词' }}
        </button>
        <button class="primary" @click="doSearch">查找单词 ↗</button>
        <input ref="fileInput" type="file" accept="image/*" class="ocr-file" @change="onFileChange">
      </div>
      <p class="search-caption">
        随手一查，让好奇心有迹可循。
        <span>试试：token · RAG · attention · chain of thought</span>
      </p>

      <!-- ===== 图片取词候选 ===== -->
      <div v-if="ocrLoading || ocrError || ocrOriginal || ocrWords.length" class="ocr-panel">
        <div v-if="ocrLoading" class="ocr-hint">📷 正在识别图片中的文字…</div>
        <div v-else-if="ocrError" class="ocr-hint err">⚠️ {{ ocrError }}</div>
        <template v-else>
          <div v-if="ocrTranslation" class="ocr-translation">
            <span class="tr-label">译文</span>
            <span class="tr-text">{{ ocrTranslation }}</span>
          </div>
          <div v-if="ocrWords.length" class="ocr-hint">
            识别到 {{ ocrWords.length }} 个术语，点击查询 👇
          </div>
          <div class="ocr-chips">
            <template v-for="w in ocrWords" :key="w.word">
              <div v-if="isPhrase(w.word)" class="ocr-phrase-block">
                <span
                  class="ocr-chip phrase"
                  :class="{ collected: w.in_library }"
                  :title="`点击查询整句「${w.word}」`"
                  @click="pickWord(w)"
                >
                  {{ w.word }}
                  <em v-if="w.zh" class="zh">{{ w.zh }}</em>
                  <i v-if="w.in_library" class="dot-tag">已收藏</i>
                </span>
                <div class="ocr-subchips">
                  <span
                    v-for="sub in splitPhrase(w.word)"
                    :key="sub"
                    class="ocr-chip sub"
                    :title="`查询「${sub}」`"
                    @click="searchWord(sub)"
                  >{{ sub }}</span>
                </div>
              </div>
              <span
                v-else
                class="ocr-chip"
                :class="{ collected: w.in_library }"
                :title="w.in_library ? '已在词库中' : `点击查询「${w.word}」`"
                @click="pickWord(w)"
              >
                {{ w.word }}
                <em v-if="w.zh" class="zh">{{ w.zh }}</em>
                <i v-if="w.in_library" class="dot-tag">已收藏</i>
              </span>
            </template>
          </div>
        </template>
      </div>
    </div>

    <!-- ===== 空状态 ===== -->
    <div v-if="!searched" class="empty-hint">
      <span class="empty-hint-mark">✳</span>
      <p>随手一查，让好奇心有迹可循。<br>查到之后，收藏进自己的词库。</p>
    </div>

    <template v-else>
      <!-- ===== 双栏结果区 ===== -->
      <div class="result-grid">
        <!-- 左栏：词典 -->
        <div class="panel panel-dict">
          <div class="panel-head">📖 词典释义</div>
          <div class="panel-body">
            <div v-if="dictLoading" class="skeleton" style="padding:0">
              <div class="sk-line" style="width:40%"></div>
              <div class="sk-line" style="width:90%"></div>
              <div class="sk-line" style="width:75%"></div>
            </div>
            <div v-else-if="dictError" class="panel-hint">⚠️ {{ dictError }}</div>
            <div v-else-if="dict && !dict.found" class="panel-hint">
              词典未收录「{{ currentWord }}」<br>
              <span class="sub">可能是短语或领域缩写，可参考右侧大模型的解读 👉</span>
            </div>
            <template v-else-if="dict">
              <div class="dict-word-row">
                <span class="dict-word">{{ dict.word }}</span>
                <Phonetics
                  :uk="dict.phonetic_uk"
                  :us="dict.phonetic_us"
                  :word="dict.word"
                  wrapper-class="dict-phos"
                  item-class="dict-phonetic"
                />
              </div>
              <div v-if="dict.api_meaning" class="dict-section">
                <div class="dict-label">释义</div>
                <div class="dict-meaning">{{ dict.api_meaning }}</div>
              </div>
              <div v-if="dict.examples.length" class="dict-section">
                <div class="dict-label">例句</div>
                <div v-for="(e, i) in dict.examples" :key="i" class="dict-example">
                  {{ e.en }}<span v-if="e.zh" class="zh">{{ e.zh }}</span>
                </div>
              </div>
            </template>
          </div>
        </div>

        <!-- 右栏：大模型领域翻译 -->
        <div class="panel panel-llm">
          <div class="panel-head">🤖 大模型 · 领域翻译</div>
          <div class="panel-body">
            <div v-if="llmError" class="panel-hint">⚠️ {{ llmError }}</div>
            <template v-else>
              <div v-if="!visibleSections.length" class="skeleton" style="padding:0">
                <div class="sk-line" style="width:30%"></div>
                <div class="sk-line" style="width:85%"></div>
                <div class="sk-line" style="width:70%"></div>
              </div>
              <div v-for="sec in visibleSections" :key="sec.key" class="llm-block">
                <span class="llm-tag" :class="sec.tagCls">{{ sec.label }}</span>
                <div v-if="sec.text" class="llm-text" :class="sec.textCls">{{ sec.text }}</div>
                <div v-if="sec.zh" class="llm-text llm-example-zh">{{ sec.zh }}</div>
              </div>
              <span v-if="llmStreaming" class="cursor"></span>
            </template>
          </div>
        </div>
      </div>

      <!-- ===== 收藏栏 ===== -->
      <div v-if="streamDone" class="fav-bar">
        <button class="btn btn-fav" :class="{ saved: favSaved }" :disabled="favSaving || favSaved" @click="doFav">
          {{ favSaved ? '✓ 已收藏到词库' : (favSaving ? '收藏中…' : '⭐ 收藏入词库') }}
        </button>
        <button class="btn btn-outline" :disabled="llmStreaming" @click="doRegen">🔄 重新生成</button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import Phonetics from '../components/Phonetics.vue'
import { lookupDictionary, createWord, extractWordsFromImage } from '../api'
import { toast } from '../utils'

const keyword = ref('')
const searched = ref(false)
const currentWord = ref('')

/* ========= 左栏：词典 ========= */
const dictLoading = ref(false)
const dict = ref(null)
const dictError = ref('')

/* ========= 右栏：大模型流式翻译 ========= */
const llmSections = ref([])
const llmStreaming = ref(false)
const llmError = ref('')
const streamDone = ref(false)
let abortCtrl = null
let dictSeq = 0
let llmSeq = 0

/* ========= 收藏 ========= */
const favSaving = ref(false)
const favSaved = ref(false)

/* ========= 图片取词（v0.7）========= */
const fileInput = ref(null)
const ocrLoading = ref(false)
const ocrError = ref('')
const ocrOriginal = ref('')
const ocrTranslation = ref('')
const ocrWords = ref([])

function pickImage() {
  fileInput.value?.click()
}

function onFileChange(e) {
  const file = e.target.files?.[0]
  if (file) runOcr(file)
  e.target.value = ''
}

function onPaste(e) {
  const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith('image/'))
  if (!item) return
  e.preventDefault()
  runOcr(item.getAsFile())
}

async function runOcr(file) {
  if (!file) return
  ocrLoading.value = true
  ocrError.value = ''
  ocrOriginal.value = ''
  ocrTranslation.value = ''
  ocrWords.value = []
  try {
    const res = await extractWordsFromImage(file)
    ocrOriginal.value = res.original_text || ''
    ocrTranslation.value = res.translation || ''
    ocrWords.value = res.words || []
    if (ocrOriginal.value) keyword.value = ocrOriginal.value
    if (!ocrWords.value.length && !ocrOriginal.value) {
      ocrError.value = '未识别到文字，换张更清晰的图片试试'
    }
  } catch (e) {
    ocrError.value = e.message || '图片识别失败'
  } finally {
    ocrLoading.value = false
  }
}

function pickWord(w) {
  keyword.value = w.word
  doSearch()
}

function isPhrase(word) {
  return /\s/.test((word || '').trim())
}

function splitPhrase(word) {
  return (word || '').trim().split(/\s+/).filter(Boolean)
}

function searchWord(text) {
  keyword.value = text
  doSearch()
}

const SECTION_META = {
  '定名': { label: '中文定名', tagCls: 'tag-term', textCls: 'llm-term' },
  '展开': { label: '缩写展开', tagCls: 'tag-abbr', textCls: '' },
  '详解': { label: '领域详解', tagCls: 'tag-domain', textCls: 'domain' },
}

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

const sectionMap = computed(() => {
  const map = {}
  for (const s of llmSections.value) map[s.key] = trimIncomplete(s.text)
  return map
})

const visibleSections = computed(() => {
  const map = sectionMap.value
  const out = []
  for (const key of ['定名', '展开', '详解']) {
    if (key in map && map[key] && map[key] !== '无') {
      out.push({ key, ...SECTION_META[key], text: map[key] })
    }
  }
  const en = map['例句'], zh = map['译文']
  const showEn = en && en !== '无', showZh = zh && zh !== '无'
  if ('例句' in map && (showEn || showZh || llmStreaming.value)) {
    out.push({
      key: '例句', label: '领域例句', tagCls: 'tag-example',
      textCls: 'llm-example-text', text: showEn ? en : '', zh: showZh ? zh : '',
    })
  }
  return out
})

function doSearch() {
  const kw = keyword.value.trim()
  if (!kw) return
  currentWord.value = kw
  searched.value = true
  favSaved.value = false
  fetchDict(kw)
  streamTranslate(kw)
}

async function fetchDict(word) {
  const seq = ++dictSeq
  dictLoading.value = true
  dict.value = null
  dictError.value = ''
  try {
    const data = await lookupDictionary(word)
    if (seq !== dictSeq) return
    dict.value = data
  } catch (e) {
    if (seq !== dictSeq) return
    dictError.value = e.message || '词典查询失败'
  } finally {
    if (seq === dictSeq) dictLoading.value = false
  }
}

async function streamTranslate(word) {
  abortCtrl?.abort()
  abortCtrl = new AbortController()
  const seq = ++llmSeq
  llmSections.value = []
  llmError.value = ''
  llmStreaming.value = true
  streamDone.value = false
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
      if (seq !== llmSeq) return
      buf += decoder.decode(value, { stream: true })
      const events = buf.split('\n\n')
      buf = events.pop()
      for (const ev of events) {
        const line = ev.trim()
        if (!line.startsWith('data:')) continue
        const payload = line.slice(5).trim()
        if (payload === '[DONE]') continue
        let obj
        try { obj = JSON.parse(payload) } catch { continue }
        if (obj.error) throw new Error(obj.error)
        const delta = obj.choices?.[0]?.delta?.content || ''
        if (delta) {
          raw += delta
          llmSections.value = parseSections(raw)
        }
      }
    }
    if (seq === llmSeq) streamDone.value = true
  } catch (e) {
    if (e.name === 'AbortError' || seq !== llmSeq) return
    llmError.value = e.message || '翻译失败'
  } finally {
    if (seq === llmSeq) llmStreaming.value = false
  }
}

function doRegen() {
  favSaved.value = false
  streamTranslate(currentWord.value)
}

function clean(text) {
  return !text || text === '无' ? '' : text
}

async function doFav() {
  const map = sectionMap.value
  const examples = dict.value?.found ? [...dict.value.examples] : []
  const en = clean(map['例句'])
  if (en) examples.push({ en, zh: clean(map['译文']) })

  const cnTerm = clean(map['定名'])
  const payload = {
    abbreviation: currentWord.value,
    full_name: clean(map['展开']),
    cn_term: cnTerm,
    my_meaning: cnTerm || clean(map['详解']).slice(0, 50) || '待补充',
    domain_detail: clean(map['详解']),
    api_meaning: dict.value?.found ? dict.value.api_meaning : '',
    phonetic_uk: dict.value?.found ? dict.value.phonetic_uk : '',
    phonetic_us: dict.value?.found ? dict.value.phonetic_us : '',
    examples,
  }
  favSaving.value = true
  try {
    await createWord(payload)
    favSaved.value = true
    toast(`已收藏「${currentWord.value}」`, 'success')
  } catch (e) {
    toast(e.message || '收藏失败', 'error')
  } finally {
    favSaving.value = false
  }
}
</script>
