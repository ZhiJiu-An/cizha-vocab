<template>
  <div>
    <!-- ===== 搜索区 ===== -->
    <div class="search-hero">
      <div class="title">查单词 · 记术语</div>
      <div class="search-box">
        <input
          v-model="keyword"
          placeholder="输入单词、短语或领域缩写，如 token / chain of thought / RAG ..."
          autofocus
          @keydown.enter="doSearch"
          @paste="onPaste"
        >
        <button class="ocr-btn" :disabled="ocrLoading" @click="pickImage">
          {{ ocrLoading ? '识别中…' : '📷 图片取词' }}
        </button>
        <button @click="doSearch">搜索</button>
        <!-- 隐藏的文件选择器：图片取词用 -->
        <input ref="fileInput" type="file" accept="image/*" class="ocr-file" @change="onFileChange">
      </div>
      <div class="quick-words">
        <span v-for="w in quickWords" :key="w" @click="quickSearch(w)">{{ w }}</span>
      </div>

      <!-- ===== 图片取词候选（上传/粘贴截图后出现，点击填入搜索框并自动查询）===== -->
      <div v-if="ocrLoading || ocrError || ocrOriginal || ocrWords.length" class="ocr-panel">
        <div v-if="ocrLoading" class="ocr-hint">📷 正在识别图片中的文字…</div>
        <div v-else-if="ocrError" class="ocr-hint err">⚠️ {{ ocrError }}</div>
        <template v-else>
          <!-- 原文已自动填入搜索框；这里展示译文 -->
          <div v-if="ocrTranslation" class="ocr-translation">
            <span class="tr-label">译文</span>
            <span class="tr-text">{{ ocrTranslation }}</span>
          </div>
          <div v-if="ocrWords.length" class="ocr-hint">
            识别到 {{ ocrWords.length }} 个术语，点击查询 👇
          </div>
          <div class="ocr-chips">
            <template v-for="w in ocrWords" :key="w.word">
              <!-- 多词短语：整句可点 + 拆出的子词可单独查询 -->
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
              <!-- 单词：普通 chip -->
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
      <div class="icon">🔍</div>
      <p>左边是词典的通用释义，右边是大模型的领域解读<br>查到之后一键收藏进你的词库</p>
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

const quickWords = ['token', 'RAG', 'attention', 'chain of thought']

const keyword = ref('')
const searched = ref(false)      // 是否已发起过搜索
const currentWord = ref('')      // 当前搜索词（收藏时作为 abbreviation）

/* ========= 左栏：词典 ========= */
const dictLoading = ref(false)
const dict = ref(null)           // DictionaryResult
const dictError = ref('')

/* ========= 右栏：大模型流式翻译 ========= */
const llmSections = ref([])      // 解析出的分段 [{key, text}]
const llmStreaming = ref(false)
const llmError = ref('')
const streamDone = ref(false)    // 流正常结束（出现收藏栏）
let abortCtrl = null             // 中断上一次未完成的 SSE

/* 请求序号（P1-2 / P1-3）
   快速连搜 / 点「重新生成」时，旧请求的响应（以及它的 catch / finally）会晚于新请求
   落地，把新请求刚写好的状态覆盖掉 —— 典型症状是流式光标莫名消失、或被上一轮的
   错误信息顶掉。做法：每发起一次就自增序号，异步落地时序号不再是「当前」就整段丢弃。 */
let dictSeq = 0
let llmSeq = 0

/* ========= 收藏 ========= */
const favSaving = ref(false)
const favSaved = ref(false)

/* ========= 图片取词（v0.7）========= */
const fileInput = ref(null)
const ocrLoading = ref(false)
const ocrError = ref('')
const ocrOriginal = ref('')      // 图片原文
const ocrTranslation = ref('')   // 原文翻译
const ocrWords = ref([])         // [{word, zh, in_library}]

function pickImage() {
  fileInput.value?.click()
}

function onFileChange(e) {
  const file = e.target.files?.[0]
  if (file) runOcr(file)
  e.target.value = ''            // 清空以便重复选择同一张图
}

// 截图工具截完即在剪贴板，Ctrl+V 直接识别（主入口）
function onPaste(e) {
  const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith('image/'))
  if (!item) return              // 非图片粘贴不拦截，不影响正常粘贴文字
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
    // 原文自动填入搜索框，用户可直接查整句
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

// 点击候选术语：填入搜索框并立即发起双栏查询
function pickWord(w) {
  keyword.value = w.word
  doSearch()
}

// 短语判断：含空格即为多词短语
function isPhrase(word) {
  return /\s/.test((word || '').trim())
}

// 拆分短语为可单独查询的子词：仅按空格切，不拆连字符（如 retrieval-augmented 保留为一体）
function splitPhrase(word) {
  return (word || '').trim().split(/\s+/).filter(Boolean)
}

// 点击短语中的子词：直接查询该词
function searchWord(text) {
  keyword.value = text
  doSearch()
}

// 五段标记 → 板块映射（「无」的板块不显示）
const SECTION_META = {
  '定名': { label: '中文定名', tagCls: 'tag-term', textCls: 'llm-term' },
  '展开': { label: '缩写展开', tagCls: 'tag-abbr', textCls: '' },
  '详解': { label: '领域详解', tagCls: 'tag-domain', textCls: 'domain' },
}

// 把累积文本按【定名】【展开】【详解】【例句】【译文】切段
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

// 去掉段尾的半截标记（流式中途可能只收到「【定」）
function trimIncomplete(text) {
  return (text || '').replace(/【[^】]*$/, '').trim()
}

// 分段数组 → {定名, 展开, 详解, 例句, 译文}
const sectionMap = computed(() => {
  const map = {}
  for (const s of llmSections.value) map[s.key] = trimIncomplete(s.text)
  return map
})

// 可见板块（「无」/ 空内容不显示；例句与译文合并为一个板块）
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

function quickSearch(w) {
  keyword.value = w
  doSearch()
}

function doSearch() {
  const kw = keyword.value.trim()
  if (!kw) return
  currentWord.value = kw
  searched.value = true
  favSaved.value = false
  fetchDict(kw)
  streamTranslate(kw)
}

/* ---------- 左栏：查词典 ---------- */
async function fetchDict(word) {
  const seq = ++dictSeq
  dictLoading.value = true
  dict.value = null
  dictError.value = ''
  try {
    const data = await lookupDictionary(word)
    if (seq !== dictSeq) return          // 已被更新的查询取代（P1-3）
    dict.value = data
  } catch (e) {
    if (seq !== dictSeq) return
    dictError.value = e.message || '词典查询失败'
  } finally {
    if (seq === dictSeq) dictLoading.value = false
  }
}

/* ---------- 右栏：SSE 流式翻译（fetch + ReadableStream 逐行读） ---------- */
async function streamTranslate(word) {
  abortCtrl?.abort()             // 打断上一次未完成的流
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
    if (!resp.ok) {              // 400 未配置 / 其他 HTTP 错误
      const data = await resp.json().catch(() => ({}))
      throw new Error(data.detail || `翻译请求失败 (${resp.status})`)
    }
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      if (seq !== llmSeq) return   // 已被新请求取代，停止写入（P1-2）
      buf += decoder.decode(value, { stream: true })
      const events = buf.split('\n\n')
      buf = events.pop()         // 最后一段可能不完整，留给下一轮
      for (const ev of events) {
        const line = ev.trim()
        if (!line.startsWith('data:')) continue
        const payload = line.slice(5).trim()
        if (payload === '[DONE]') continue
        let obj
        try { obj = JSON.parse(payload) } catch { continue }
        if (obj.error) throw new Error(obj.error)   // 后端兜底转来的错误事件
        const delta = obj.choices?.[0]?.delta?.content || ''
        if (delta) {
          raw += delta
          llmSections.value = parseSections(raw)
        }
      }
    }
    if (seq === llmSeq) streamDone.value = true
  } catch (e) {
    // 被新搜索打断（AbortError）或已过期：静默丢弃
    if (e.name === 'AbortError' || seq !== llmSeq) return
    llmError.value = e.message || '翻译失败'
  } finally {
    // 只有「当前」请求才能收尾。旧请求在这里无条件置 false 会掐掉新请求的流式光标（P1-2）
    if (seq === llmSeq) llmStreaming.value = false
  }
}

/* ---------- 重新生成（只重跑大模型，左栏词典不动） ---------- */
function doRegen() {
  favSaved.value = false
  streamTranslate(currentWord.value)
}

/* ---------- 收藏入词库（映射规则见 MVP.md §8） ---------- */
function clean(text) {
  return !text || text === '无' ? '' : text
}

async function doFav() {
  const map = sectionMap.value
  // 例句：词典双语在前，LLM 领域例句在后
  const examples = dict.value?.found ? [...dict.value.examples] : []
  const en = clean(map['例句'])
  if (en) examples.push({ en, zh: clean(map['译文']) })

  const cnTerm = clean(map['定名'])
  const payload = {
    abbreviation: currentWord.value,
    full_name: clean(map['展开']),
    cn_term: cnTerm,
    // 定名预填我的理解（可后续在详情页修改）；无译名时用详解截取兜底（必填字段）
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
    toast(e.message || '收藏失败', 'error')   // 词条已存在时后端返回明确提示
  } finally {
    favSaving.value = false
  }
}
</script>
