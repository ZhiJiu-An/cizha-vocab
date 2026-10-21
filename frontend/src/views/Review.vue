<template>
  <div class="review-wrap">
    <!-- ========== 阶段一：准备 ========== -->
    <template v-if="phase === 'ready'">
      <section class="intro">
        <div>
          <div class="eyebrow">MAKE IT STICK</div>
          <h1>温故，是为了更好的相遇。</h1>
          <p class="subtitle">留一点时间给记忆，它会慢慢回应你。</p>
        </div>
      </section>

      <!-- 概览三个数字卡片 -->
      <div class="overview-cards">
        <div class="ov-card due">
          <div class="ov-num">{{ overview.due_today }}</div>
          <div class="ov-label">今日到期</div>
        </div>
        <div class="ov-card done">
          <div class="ov-num">{{ overview.reviewed_today }}</div>
          <div class="ov-label">今日已复习</div>
        </div>
        <div class="ov-card total">
          <div class="ov-num">{{ overview.total_in_queue }}</div>
          <div class="ov-label">复习队列总数</div>
        </div>
      </div>

      <!-- 标签多选 -->
      <div v-if="tags.length" class="review-block">
        <div class="rb-label">按标签筛选（可多选，不选则为全部）</div>
        <div class="tags">
          <button
            v-for="t in tags"
            :key="t.name"
            class="tag"
            :class="{ active: selectedTags.includes(t.name) }"
            @click="toggleTag(t.name)"
          >{{ t.name }} ({{ t.count }})</button>
        </div>
      </div>

      <!-- 数量选择 -->
      <div class="review-block">
        <div class="rb-label">本组数量</div>
        <div class="tags">
          <button
            v-for="n in [10, 20, 50]"
            :key="n"
            class="tag"
            :class="{ active: count === n }"
            @click="count = n"
          >{{ n }} 个</button>
        </div>
      </div>

      <div class="review-actions">
        <button class="btn btn-primary btn-start" :disabled="overview.due_today === 0" @click="start">
          开始复习
        </button>
        <span v-if="overview.due_today === 0" class="hint">今日没有到期词条 🎉</span>
      </div>
    </template>

    <!-- ========== 阶段二：复习中 ========== -->
    <template v-else-if="phase === 'reviewing'">
      <div class="review-progress">
        <span class="rp-text">第 {{ currentIndex + 1 }} / {{ queue.length }} 个</span>
        <div class="rp-bar"><div class="rp-fill" :style="{ width: `${(currentIndex / queue.length) * 100}%` }"></div></div>
      </div>

      <!-- 3D 翻面卡片：点击翻面 -->
      <div class="flip-card" :class="{ flipped }" @click="flipped = !flipped">
        <div class="flip-inner">
          <!-- 正面：主词 + 音标 + 徽章 -->
          <div class="flip-face flip-front">
            <div class="ff-abbr">{{ currentWord.abbreviation }}</div>
            <div v-if="currentWord.full_name" class="ff-full">{{ currentWord.full_name }}</div>
            <Phonetics
              class="ff-phos"
              :uk="currentWord.phonetic_uk"
              :us="currentWord.phonetic_us"
              :word="currentWord.abbreviation"
              uk-label="英"
              us-label="美"
              always-show
            />
            <WordBadge :type="typeInfo" />
            <div class="flip-hint">点击卡片或按空格翻面</div>
          </div>

          <!-- 背面：中文定名 + 我的理解 + 领域详解 + 标签 -->
          <div class="flip-face flip-back" @click.stop>
            <div class="fb-body" @click="flipped = false">
              <div v-if="currentWord.cn_term" class="fb-cn">{{ currentWord.cn_term }}</div>
              <div class="fb-block">
                <span class="label-mine fb-label">我的理解</span>
                <span class="my-meaning">{{ currentWord.my_meaning }}</span>
              </div>
              <div v-if="currentWord.domain_detail" class="fb-block">
                <div class="fb-k">领域详解</div>
                <div class="fb-detail">{{ currentWord.domain_detail }}</div>
              </div>
              <div v-if="wordTags.length" class="card-tags fb-tags">
                <span v-for="t in wordTags" :key="t" class="card-tag">{{ t }}</span>
              </div>
            </div>
            <!-- 三档自评按钮 -->
            <div class="answer-btns">
              <button class="btn-ans forget" :disabled="submitting" @click="answer('forget')">忘记 <kbd>1</kbd></button>
              <button class="btn-ans fuzzy" :disabled="submitting" @click="answer('fuzzy')">模糊 <kbd>2</kbd></button>
              <button class="btn-ans remember" :disabled="submitting" @click="answer('remember')">记住 <kbd>3</kbd></button>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- ========== 阶段三：完成 ========== -->
    <template v-else>
      <div class="done-card">
        <div class="done-icon">🎉</div>
        <div class="done-title">本组复习完成</div>
        <div class="done-stats">
          <span class="ds remember">记住 {{ stats.remember }}</span>
          <span class="ds fuzzy">模糊 {{ stats.fuzzy }}</span>
          <span class="ds forget">忘记 {{ stats.forget }}</span>
        </div>
        <div class="done-actions">
          <button class="btn btn-primary" @click="restart">再来一组</button>
          <router-link to="/" class="btn btn-outline">返回词典</router-link>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import Phonetics from '../components/Phonetics.vue'
import WordBadge from '../components/WordBadge.vue'
import { getReviewOverview, getDueWords, submitReviewAnswer, listTags } from '../api'
import { toast, parseTags, cardType } from '../utils'

const phase = ref('ready')           // ready / reviewing / done
const overview = ref({ due_today: 0, reviewed_today: 0, total_in_queue: 0 })
const tags = ref([])
const selectedTags = ref([])
const count = ref(20)

const queue = ref([])                // 本组词条队列
const currentIndex = ref(0)
const flipped = ref(false)
const submitting = ref(false)         // 防重入：双击「记住」/ 连按快捷键只提交一次
const stats = ref({ remember: 0, fuzzy: 0, forget: 0 })

const currentWord = computed(() => queue.value[currentIndex.value] || {})
const typeInfo = computed(() => cardType(currentWord.value))
const wordTags = computed(() => parseTags(currentWord.value.tags))

// 英美音标的「相同只显示一次」规则已收进 Phonetics 组件（P2-5），这里不再重复判断

async function loadReady() {
  try {
    const [ov, tg] = await Promise.all([getReviewOverview(), listTags()])
    overview.value = ov
    tags.value = tg
  } catch (e) {
    toast(e.message, 'error')
  }
}

function toggleTag(name) {
  const i = selectedTags.value.indexOf(name)
  if (i > -1) selectedTags.value.splice(i, 1)
  else selectedTags.value.push(name)
}

// 拉取到期词条：多标签时逐标签请求后合并去重（后端 /due 只支持单标签）
async function fetchDue() {
  if (!selectedTags.value.length) {
    const res = await getDueWords({ limit: count.value })
    return res.items
  }
  const results = await Promise.all(
    selectedTags.value.map((t) => getDueWords({ tag: t, limit: count.value })),
  )
  const seen = new Map()
  for (const r of results) {
    for (const w of r.items) if (!seen.has(w.id)) seen.set(w.id, w)
  }
  // 按到期时间升序（最久没复习的排前面），截取本组数量
  return [...seen.values()]
    .sort((a, b) => new Date(a.next_review_at) - new Date(b.next_review_at))
    .slice(0, count.value)
}

async function start() {
  try {
    const items = await fetchDue()
    if (!items.length) {
      toast('当前筛选下没有到期词条', 'info')
      return
    }
    queue.value = items
    currentIndex.value = 0
    stats.value = { remember: 0, fuzzy: 0, forget: 0 }
    flipped.value = false
    phase.value = 'reviewing'
  } catch (e) {
    toast(e.message, 'error')
  }
}

async function answer(result) {
  if (submitting.value) return      // 防重入：上一笔还没回来就忽略后续点击
  const word = currentWord.value
  if (!word.id) return
  submitting.value = true
  try {
    await submitReviewAnswer(word.id, result)
    stats.value[result] += 1
    if (currentIndex.value + 1 >= queue.value.length) {
      phase.value = 'done'
    } else {
      currentIndex.value += 1
      flipped.value = false
    }
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    submitting.value = false
  }
}

function restart() {
  phase.value = 'ready'
  selectedTags.value = []
  loadReady()
}

// 快捷键：空格翻面，1/2/3 自评（仅翻面后）
function onKeydown(e) {
  if (phase.value !== 'reviewing') return
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return
  if (e.code === 'Space') {
    e.preventDefault()
    flipped.value = !flipped.value
  } else if (flipped.value && ['Digit1', 'Digit2', 'Digit3'].includes(e.code)) {
    answer({ Digit1: 'forget', Digit2: 'fuzzy', Digit3: 'remember' }[e.code])
  }
}

onMounted(() => {
  loadReady()
  window.addEventListener('keydown', onKeydown)
})
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>
