<template>
  <div class="stats-wrap">
    <section class="intro">
      <div>
        <div class="eyebrow">YOUR GROWTH, IN WORDS</div>
        <h1>每一步，都算数。</h1>
        <p class="subtitle">回头看看，你已经走了很远。</p>
      </div>
    </section>

    <!-- ===== 概览数字卡 ×4 ===== -->
    <div class="overview-cards stats-cards">
      <div class="ov-card">
        <div class="ov-num">{{ s.totals.total_words }}</div>
        <div class="ov-label">累计词条</div>
      </div>
      <div class="ov-card accent-primary">
        <div class="ov-num">{{ s.totals.week_new }}</div>
        <!-- 代码算的是滚动 7 天窗口，不是自然周，标签必须与算法一致 -->
        <div class="ov-label">近 7 天新增</div>
      </div>
      <div class="ov-card accent-green">
        <div class="ov-num">{{ s.totals.total_reviews }}</div>
        <div class="ov-label">累计复习</div>
      </div>
      <div class="ov-card accent-yellow">
        <div class="ov-num">{{ s.totals.reviewed_today }}</div>
        <div class="ov-label">今日已复习</div>
      </div>
    </div>

    <!-- ===== 近 7 日趋势（纯 CSS 双系列柱状图）===== -->
    <div class="stat-block">
      <div class="sb-head">
        <div class="sb-title">
          近 {{ rangeDays }} 天趋势<template v-if="s.trend_granularity === 'week'">（按周聚合）</template>
        </div>
        <div class="trend-ranges">
          <button
            v-for="d in RANGES"
            :key="d"
            class="range-btn"
            :class="{ active: rangeDays === d }"
            @click="changeRange(d)"
          >{{ d }} 天</button>
        </div>
      </div>
      <div class="legend" style="margin-bottom: 10px">
        <span class="lg"><i class="dot new"></i>新增词条</span>
        <span class="lg"><i class="dot review"></i>复习次数</span>
      </div>
      <div class="trend-chart">
        <div v-for="(d, idx) in s.daily_trend" :key="d.date + idx" class="trend-col">
          <div class="trend-bars">
            <div class="bar new" :style="barStyle(d.new_words)" :title="`${d.date} 新增 ${d.new_words}`"></div>
            <div class="bar review" :style="barStyle(d.reviews)" :title="`${d.date} 复习 ${d.reviews}`"></div>
          </div>
          <div class="trend-date">{{ showDateLabel(idx) ? d.date : '' }}</div>
        </div>
      </div>
      <div v-if="s.totals.total_reviews === 0" class="stat-empty">
        暂无复习记录，去「🧠 复习」完成第一组打卡吧
      </div>
    </div>

    <!-- ===== 标签分布 Top 8 ===== -->
    <div class="stat-block">
      <div class="sb-title">标签分布</div>
      <template v-if="s.tag_distribution.length">
        <div v-for="t in s.tag_distribution" :key="t.name" class="hbar-row">
          <span class="hbar-name" :title="t.name">{{ t.name }}</span>
          <div class="hbar-track">
            <div class="hbar-fill" :style="{ width: hbarWidth(t.count, maxTag) }"></div>
          </div>
          <span class="hbar-num">{{ t.count }}</span>
        </div>
      </template>
      <div v-else class="stat-empty">还没有标签，新建词条时添加吧</div>
    </div>

    <!-- ===== 复习档位分布 ===== -->
    <div class="stat-block">
      <div class="sb-title">复习档位分布</div>
      <div v-for="st in s.stage_distribution" :key="st.stage" class="hbar-row">
        <span class="hbar-name stage-name">第 {{ st.stage + 1 }} 档 · {{ st.days }} 天</span>
        <div class="hbar-track">
          <div class="hbar-fill stage" :style="{ width: hbarWidth(st.count, maxStage) }"></div>
        </div>
        <span class="hbar-num">{{ st.count }}</span>
      </div>
      <div class="sb-hint">档位越高间隔越长：记住 → 升档（封顶第 6 档），模糊 → 不变，忘记 → 回第 1 档</div>
    </div>

    <!-- ===== 最常忘记的词（v0.11）===== -->
    <div class="stat-block" v-if="mistakes.length || mistakesTotal">
      <div class="sb-head">
        <div class="sb-title">最常忘记的词</div>
        <div class="sb-hint" style="margin: 0">共 {{ mistakesTotal }} 个错词</div>
      </div>
      <div v-for="m in mistakes" :key="m.id" class="hbar-row">
        <span class="hbar-name">
          <router-link :to="`/words/${m.id}`" :title="m.my_meaning">{{ m.abbreviation }}</router-link>
        </span>
        <div class="hbar-track">
          <div class="hbar-fill forget" :style="{ width: hbarWidth(m.forget_times, maxForget) }"></div>
        </div>
        <span class="hbar-num">忘 {{ m.forget_times }} / {{ m.total_reviews }} 次</span>
      </div>
      <div class="sb-hint">
        去「🧠 复习」选 <b>🎯 错词优先</b> 可以优先重练这些词
      </div>
    </div>
    <div class="stat-block" v-else>
      <div class="sb-title">最常忘记的词</div>
      <div class="stat-empty">还没有「忘记」记录，继续保持 🌱</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getStatsSummary, getMistakes } from '../api'
import { toast } from '../utils'

// 错词榜（v0.11）：复用 /api/review/mistakes，数据源自 ReviewLog.result
const mistakes = ref([])
const mistakesTotal = ref(0)
const MISTAKE_LIMIT = 10

// 趋势时间范围（v0.11）：7 天按天、30 天按天、90 天由后端按周聚合
const RANGES = [7, 30, 90]
const rangeDays = ref(7)

const s = ref({
  totals: { total_words: 0, week_new: 0, total_reviews: 0, reviewed_today: 0 },
  tag_distribution: [],
  daily_trend: [],
  stage_distribution: [],
})

// 各图表的最大值（兜底 1，避免除零）
const maxTrend = computed(() =>
  Math.max(...s.value.daily_trend.map((d) => Math.max(d.new_words, d.reviews)), 1))
const maxTag = computed(() =>
  Math.max(...s.value.tag_distribution.map((t) => t.count), 1))
const maxStage = computed(() =>
  Math.max(...s.value.stage_distribution.map((x) => x.count), 1))
const maxForget = computed(() =>
  Math.max(...mistakes.value.map((m) => m.forget_times), 1))

// 柱子多的时候只标注部分日期，避免标签重叠成一团墨
function showDateLabel(idx) {
  const n = s.value.daily_trend.length
  if (n <= 10) return true
  return idx === 0 || idx === n - 1 || idx % Math.ceil(n / 6) === 0
}

// 柱高按最大值百分比（相对趋势图柱区高度）
function barStyle(val) {
  return { height: `${Math.round((val / maxTrend.value) * 100)}%` }
}
// 横条宽度按最大值百分比
function hbarWidth(count, max) {
  return `${Math.round((count / max) * 100)}%`
}

async function loadSummary() {
  try {
    s.value = await getStatsSummary({ days: rangeDays.value })
  } catch (e) {
    toast(e.message, 'error')
  }
}

function changeRange(days) {
  if (rangeDays.value === days) return
  rangeDays.value = days
  loadSummary()
}

onMounted(async () => {
  try {
    const [, mistakeData] = await Promise.all([
      loadSummary(),
      getMistakes({ limit: MISTAKE_LIMIT }),
    ])
    mistakes.value = mistakeData.items || []
    mistakesTotal.value = mistakeData.total || 0
  } catch (e) {
    toast(e.message, 'error')
  }
})
</script>
