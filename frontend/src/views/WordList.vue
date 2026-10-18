<template>
  <div>
    <div class="page-title">📚 词库</div>

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
      <button class="btn btn-outline" @click="triggerImport">📥 导入 CSV</button>
      <button class="btn btn-outline" @click="doExport">📤 导出 CSV</button>
      <button class="btn btn-primary" @click="router.push('/new')">➕ 新建</button>
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
        v-for="w in words"
        :key="w.id"
        class="card"
        :class="cardType(w).cls"
        @click="router.push(`/words/${w.id}`)"
      >
        <div class="card-head">
          <span class="card-abbr">
            {{ w.abbreviation }}
            <span class="badge" :class="cardType(w).badge">{{ cardType(w).text }}</span>
          </span>

          <!-- 中文定名 chip 紧跟主词 -->
          <span v-if="w.cn_term" class="card-cn">{{ w.cn_term }}</span>

          <!-- 音标紧跟主词 -->
          <div v-if="w.phonetic_uk || w.phonetic_us" class="card-phos">
            <span v-if="w.phonetic_uk" class="card-phonetic">
              <span class="pho-tag uk">UK</span>{{ w.phonetic_uk }}
            </span>
            <span v-if="w.phonetic_us && w.phonetic_us !== w.phonetic_uk" class="card-phonetic">
              <span class="pho-tag us">US</span>{{ w.phonetic_us }}
            </span>
          </div>

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
          <div class="card-actions">
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
      <p>{{ keyword || activeTag ? '没有匹配的词条' : '还没有词条，点右上角「新建」开始记录' }}</p>
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
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { batchImport, deleteWord, exportCsvUrl, listTags, listWords } from '../api'
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
const pendingDelete = ref(null)
const fileInput = ref(null)

async function loadWords() {
  loading.value = true
  try {
    const data = await listWords({
      keyword: keyword.value,
      tag: activeTag.value,
      sort: sort.value,
    })
    words.value = data.items
    total.value = data.total
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    loading.value = false
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
  debounceTimer = setTimeout(loadWords, 300)
})
watch(sort, loadWords)

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

async function confirmDelete() {
  const target = pendingDelete.value
  pendingDelete.value = null
  try {
    await deleteWord(target.id)
    toast('已删除', 'success')
    await Promise.all([loadWords(), loadTags()])
  } catch (e) {
    toast(e.message, 'error')
  }
}

function doExport() {
  window.location.href = exportCsvUrl({ keyword: keyword.value, tag: activeTag.value })
}

function triggerImport() {
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
