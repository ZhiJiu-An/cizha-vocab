<template>
  <div>
    <section class="intro">
      <div>
        <div class="eyebrow">YOUR WORD COLLECTION</div>
        <h1>属于你的，语言花园。</h1>
        <p class="subtitle">收集每一次好奇，让词汇成为自己的表达。</p>
      </div>
      <button class="primary" @click="router.push('/new')">＋ 发现新单词</button>
    </section>

    <!-- 工具栏 -->
    <div class="toolbar">
      <input v-model="keyword" class="search" placeholder="🔍 搜索缩写、全称、中文定名、我的理解、领域详解、标签..." />
      <select v-model="sort">
        <option value="time_desc">最新优先</option>
        <option value="time_asc">最早优先</option>
        <option value="alpha_asc">字母 A → Z</option>
        <option value="alpha_desc">字母 Z → A</option>
      </select>
      <span class="count">共 {{ total }} 条</span>
      <button class="btn btn-outline" :class="{ 'mode-on': selectMode }" @click="toggleMode">
        {{ selectMode ? '退出多选' : '☑ 多选' }}
      </button>
      <template v-if="!selectMode">
        <button class="btn btn-outline" @click="triggerImport">📥 导入 CSV</button>
        <button
          class="btn btn-outline"
          title="仅导出词条与当前复习进度，不含逐次复习历史"
          @click="doExport"
        >📤 导出 CSV</button>
      </template>
      <input ref="fileInput" type="file" accept=".csv" style="display: none" @change="onImport" />
    </div>

    <!-- 标签筛选 -->
    <div v-if="allTags.length" class="tags">
      <button class="tag" :class="{ active: activeTag === '' }" @click="selectTag('')">全部</button>
      <button
        v-for="t in allTags"
        :key="t.name"
        class="tag"
        :class="{ active: activeTag === t.name }"
        @click="selectTag(t.name)"
      >
        #{{ t.name }} <span style="opacity: .65">{{ t.count }}</span>
      </button>
    </div>

    <!-- 卡片列表 -->
    <div v-if="loading" class="empty">加载中…</div>

    <div v-else-if="words.length" class="cards">
      <div
        v-for="w in displayWords"
        :key="w.id"
        class="card"
        :class="[w._type.cls, { selectable: selectMode, selected: selected.includes(w.id) }]"
        @click="onCardClick(w)"
      >
        <span v-if="selectMode" class="check" :class="{ on: selected.includes(w.id) }">✓</span>
        <div class="card-head">
          <span class="card-abbr">
            {{ w.abbreviation }}
            <WordBadge :type="w._type" />
          </span>

          <!-- 中文定名 chip 紧跟主词 -->
          <span v-if="w.cn_term" class="card-cn">{{ w.cn_term }}</span>

          <!-- 音标紧跟主词 -->
          <Phonetics :uk="w.phonetic_uk" :us="w.phonetic_us" :word="w.abbreviation" />

          <span v-if="w.full_name" class="card-full">{{ w.full_name }}</span>
          <span class="card-spacer"></span>
        </div>

        <div class="card-row">
          <span class="label label-mine">💡 我的理解</span>
          <span class="my-meaning">{{ w.my_meaning }}</span>
        </div>

        <div v-if="w.api_meaning" class="card-row">
          <span class="label label-api">📖 通用释义</span>
          <span class="api-meaning">{{ w.api_meaning }}</span>
        </div>

        <div class="card-foot">
          <div class="card-tags">
            <span v-for="t in parseTags(w.tags)" :key="t" class="card-tag">#{{ t }}</span>
          </div>
          <span class="card-time">{{ relativeTime(w.created_at) }}</span>
          <div v-if="!selectMode" class="card-actions">
            <button
              class="btn btn-ghost btn-sm"
              @click.stop="router.push(`/words/${w.id}/edit`)"
            >
              编辑
            </button>
            <button class="btn btn-danger-ghost" @click.stop="pendingDelete = w">删除</button>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="empty">
      <div class="icon">🗂️</div>
      <p>{{ keyword || activeTag ? '没有匹配的词条' : '还没有词条，点上方「发现新单词」开始记录' }}</p>
    </div>

    <!-- 分页（P1-4）：旧版只渲染前 200 条却把总数显示成全量，超出的词条看不见 -->
    <div v-if="!loading && words.length < total" style="text-align: center; margin: 22px 0 8px">
      <button class="btn btn-outline" :disabled="loadingMore" @click="loadWords({ append: true })">
        {{ loadingMore ? '加载中…' : `加载更多（已显示 ${words.length} / ${total}）` }}
      </button>
    </div>

    <!-- 悬浮详情窗：点卡片就地预览，不再跳转路由 -->
    <WordQuickView
      v-if="activeId"
      :word-id="activeId"
      @close="activeId = null"
      @delete="onQuickDelete"
    />

    <!-- 批量操作栏：多选模式固定在底部 -->
    <div v-if="selectMode" class="batch-bar">
      <span class="bb-count">已选 <b>{{ selected.length }}</b> 条</span>
      <button class="bb-link" @click="selectAll">{{ selected.length === words.length ? '清空' : '全选' }}</button>
      <span class="bb-spacer"></span>
      <button class="btn btn-outline" :disabled="!selected.length || batchBusy" @click="tagEditor = true">
        🏷️ 添加标签
      </button>
      <button class="btn btn-danger-ghost" :disabled="!selected.length || batchBusy" @click="batchConfirm = true">
        🗑 批量删除
      </button>
      <button class="btn btn-ghost" @click="toggleMode">取消</button>
    </div>

    <!-- 批量加标签弹窗 -->
    <div v-if="tagEditor" class="modal-mask" @click.self="tagEditor = false">
      <div class="modal">
        <h3>为 {{ selected.length }} 条词条添加标签</h3>
        <input
          v-model="tagInput"
          class="batch-tag-input"
          placeholder="输入标签，多个用逗号分隔，如：LLM, 论文"
          autofocus
          @keydown.enter="batchAddTags"
        />
        <div class="modal-actions">
          <button class="btn btn-ghost" @click="tagEditor = false">取消</button>
          <button class="btn btn-primary" :disabled="!tagInput.trim() || batchBusy" @click="batchAddTags">
            {{ batchBusy ? '处理中…' : '添加' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 批量删除确认 -->
    <div v-if="batchConfirm" class="modal-mask" @click.self="batchConfirm = false">
      <div class="modal">
        <h3>批量删除</h3>
        <p>确定要删除选中的 {{ selected.length }} 条词条吗？此操作不可恢复。</p>
        <div class="modal-actions">
          <button class="btn btn-ghost" @click="batchConfirm = false">取消</button>
          <button class="btn btn-primary" style="background: #dc2626" :disabled="batchBusy" @click="batchDelete">
            {{ batchBusy ? '删除中…' : '删除' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 删除确认 -->
    <div v-if="pendingDelete" class="modal-mask" @click.self="pendingDelete = null">
      <div class="modal">
        <h3>删除词条</h3>
        <p>确定要删除「{{ pendingDelete.abbreviation }}」吗？此操作不可恢复。</p>
        <div class="modal-actions">
          <button class="btn btn-ghost" @click="pendingDelete = null">取消</button>
          <button class="btn btn-primary" style="background: #dc2626" @click="confirmDelete">
            删除
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Phonetics from '../components/Phonetics.vue'
import WordBadge from '../components/WordBadge.vue'
import WordQuickView from '../components/WordQuickView.vue'
import {
  batchImport, bulkAddTags, bulkDeleteWords, deleteWord, exportCsvUrl,
  listTags, listWords, restoreWords,
} from '../api'
import { cardType, parseTags, relativeTime, toast } from '../utils'

const route = useRoute()
const router = useRouter()

const words = ref([])
const total = ref(0)
const allTags = ref([])
const keyword = ref(route.query.keyword || '')
const activeTag = ref(route.query.tag || '')
const sort = ref('time_desc')
const loading = ref(false)
const loadingMore = ref(false)
const pendingDelete = ref(null)
const activeId = ref(null) // 悬浮详情窗当前词条 id
const selectMode = ref(false)  // 多选模式
const selected = ref([])       // 已选词条 id 列表
const batchConfirm = ref(false) // 批量删除确认弹窗
const tagEditor = ref(false)    // 批量加标签弹窗
const tagInput = ref('')
const batchBusy = ref(false)    // 批量操作进行中（防重入）
const fileInput = ref(null)

const PAGE_SIZE = 60            // 每页条数（后端上限 500）
let listSeq = 0                 // 请求序号：丢弃过期的列表响应，避免旧页覆盖新页

// 每张卡片的类型只算一次（P2-5）：原来模板里 cardType(w) 被调了 3 次
const displayWords = computed(() =>
  words.value.map((w) => ({ ...w, _type: cardType(w) })),
)

// append=true 追加下一页；否则从头加载（搜索 / 筛选 / 排序变化时）
async function loadWords({ append = false } = {}) {
  const seq = ++listSeq
  if (append) loadingMore.value = true
  else loading.value = true
  try {
    const data = await listWords({
      keyword: keyword.value,
      tag: activeTag.value,
      sort: sort.value,
      skip: append ? words.value.length : 0,
      limit: PAGE_SIZE,
    })
    if (seq !== listSeq) return          // 已有更新的请求在跑
    words.value = append ? [...words.value, ...data.items] : data.items
    total.value = data.total
  } catch (e) {
    if (seq !== listSeq) return
    toast(e.message, 'error')
  } finally {
    if (seq === listSeq) {
      loading.value = false
      loadingMore.value = false
    }
  }
}

async function loadTags() {
  try {
    allTags.value = await listTags()
  } catch {
    /* 标签失败不阻塞列表 */
  }
}

function selectTag(name) {
  activeTag.value = name
  loadWords()
}

// 输入搜索做 300ms 防抖
let debounceTimer
watch(keyword, () => {
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => loadWords(), 300)
})
// 用箭头包一层：watch 回调会传 (newVal, oldVal)，直接传 loadWords 会被当成参数解构
watch(sort, () => loadWords())

// 从「标签」页带 ?tag=xxx 跳转过来时同步筛选
watch(
  () => route.query.tag,
  (val) => {
    const next = val || ''
    if (next !== activeTag.value) {
      activeTag.value = next
      loadWords()
    }
  },
)

// 悬浮窗里点删除：关掉悬浮窗，走列表统一的确认弹窗
function onQuickDelete(word) {
  activeId.value = null
  pendingDelete.value = word
}

/* ========= 多选与批量操作 ========= */
function toggleMode() {
  selectMode.value = !selectMode.value
  selected.value = []
  batchConfirm.value = false
  tagEditor.value = false
  tagInput.value = ''
}

function onCardClick(w) {
  if (!selectMode.value) {
    activeId.value = w.id
    return
  }
  const i = selected.value.indexOf(w.id)
  if (i > -1) selected.value.splice(i, 1)
  else selected.value.push(w.id)
}

function selectAll() {
  selected.value = selected.value.length === words.value.length
    ? []
    : words.value.map((w) => w.id)
}

// 去掉列表内部的辅助字段（_type 只用于渲染），得到可回灌的原始词条
function plain(item) {
  const { _type, ...rest } = item
  return rest
}

// 撤销删除：把删除前的快照原样回灌（复习进度、创建时间都保留）
async function undoDelete(snapshots) {
  try {
    const res = await restoreWords(snapshots)
    toast(
      res.skipped
        ? `已恢复 ${res.restored} 条（${res.skipped} 条同名词条已存在，已跳过）`
        : `已恢复 ${res.restored} 条`,
      'success',
    )
    await Promise.all([loadWords(), loadTags()])
  } catch (e) {
    toast(e.message || '撤销失败', 'error')
  }
}

// v0.11：走单请求 + 单事务（原来这里是 Promise.allSettled 循环发 N 个请求）
async function batchDelete() {
  batchConfirm.value = false
  batchBusy.value = true
  const ids = [...selected.value]
  const snapshots = displayWords.value.filter((w) => ids.includes(w.id)).map(plain)
  try {
    const res = await bulkDeleteWords(ids)
    toast(
      res.failed
        ? `已删除 ${res.succeeded} 条，${res.failed} 条未找到`
        : `已删除 ${res.succeeded} 条`,
      res.failed ? 'error' : 'success',
      res.succeeded ? { label: '撤销', handler: () => undoDelete(snapshots) } : null,
    )
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    batchBusy.value = false
    selectMode.value = false
    selected.value = []
    await Promise.all([loadWords(), loadTags()])
  }
}

// 追加式加标签：合并去重交给后端（normalize_tags），单请求 + 单事务
async function batchAddTags() {
  const newTags = tagInput.value.split(/[,，\s]+/).map((t) => t.trim()).filter(Boolean)
  if (!newTags.length) return
  tagEditor.value = false
  batchBusy.value = true
  const ids = [...selected.value]
  try {
    const res = await bulkAddTags(ids, newTags)
    toast(
      res.failed
        ? `已为 ${res.succeeded} 条添加标签，${res.failed} 条未找到`
        : `已为 ${res.succeeded} 条添加标签`,
      res.failed ? 'error' : 'success',
    )
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    batchBusy.value = false
    tagInput.value = ''
    selectMode.value = false
    selected.value = []
    await Promise.all([loadWords(), loadTags()])
  }
}

async function confirmDelete() {
  const target = pendingDelete.value
  pendingDelete.value = null
  const snapshot = plain(target)          // 删前留快照，用于撤销
  try {
    await deleteWord(target.id)
    toast('已删除', 'success', { label: '撤销', handler: () => undoDelete([snapshot]) })
    await Promise.all([loadWords(), loadTags()])
  } catch (e) {
    toast(e.message, 'error')
  }
}

function doExport() {
  window.location.href = exportCsvUrl({ keyword: keyword.value, tag: activeTag.value })
}

function triggerImport() {
  if (!fileInput.value) return
  fileInput.value.value = ''
  fileInput.value.click()
}

async function onImport(event) {
  const file = event.target.files?.[0]
  if (!file) return
  try {
    const created = await batchImport(file)
    toast(`成功导入 ${created.length} 条`, 'success')
    await Promise.all([loadWords(), loadTags()])
  } catch (e) {
    toast(e.message, 'error')
  }
}

onMounted(() => {
  loadWords()
  loadTags()
})
</script>

<style scoped>
/* ========= 多选模式 ========= */
.mode-on {
  border-color: var(--primary);
  color: var(--primary);
  background: #eef3ea;
}
.card.selectable { position: relative; cursor: default; }
.card.selected {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px rgba(52, 103, 79, .15);
}
.check {
  position: absolute;
  top: 10px;
  right: 12px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: 1.5px solid var(--border);
  background: #fff;
  color: transparent;
  font-size: 12px;
  line-height: 18px;
  text-align: center;
  transition: all .15s;
}
.check.on {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}

/* ========= 底部批量操作栏 ========= */
.batch-bar {
  position: sticky;
  bottom: 16px;
  z-index: 20;
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 18px;
  padding: 12px 18px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: 0 8px 24px rgba(51, 74, 38, .12);
}
.bb-count { font-size: 12px; color: var(--muted); }
.bb-count b { color: var(--primary); font-size: 14px; }
.bb-link {
  border: 0;
  background: none;
  font-size: 12px;
  color: var(--primary-2);
  cursor: pointer;
  padding: 4px 6px;
}
.bb-link:hover { text-decoration: underline; }
.bb-spacer { flex: 1; }

.batch-tag-input {
  width: 100%;
  font-family: inherit;
  font-size: 13px;
  color: var(--text);
  background: #fbfcf9;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  margin: 12px 0 18px;
  transition: border-color .2s, box-shadow .2s;
}
.batch-tag-input:focus {
  outline: none;
  border-color: var(--primary-2);
  box-shadow: 0 0 0 3px rgba(52, 103, 79, .12);
}
</style>
