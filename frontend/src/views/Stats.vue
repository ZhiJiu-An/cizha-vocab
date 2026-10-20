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
        <div class="ov-label">本周新增</div>
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
        <div class="sb-title">近 7 日趋势</div>
        <div class="legend">
          <span class="lg"><i class="dot new"></i>新增词条</span>
          <span class="lg"><i class="dot review"></i>复习次数</span>
        </div>
      </div>
      <div class="trend-chart">
        <div v-for="d in s.daily_trend" :key="d.date" class="trend-col">
          <div class="trend-bars">
            <div class="bar new" :style="barStyle(d.new_words)" :title="`${d.date} 新增 ${d.new_words}`"></div>
            <div class="bar review" :style="barStyle(d.reviews)" :title="`${d.date} 复习 ${d.reviews}`"></div>
          </div>
          <div class="trend-date">{{ d.date }}</div>
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
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getStatsSummary } from '../api'
import { toast } from '../utils'

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

// 柱高按最大值百分比（相对趋势图柱区高度）
function barStyle(val) {
  return { height: `${Math.round((val / maxTrend.value) * 100)}%` }
}
// 横条宽度按最大值百分比
function hbarWidth(count, max) {
  return `${Math.round((count / max) * 100)}%`
}

onMounted(async () => {
  try {
    s.value = await getStatsSummary()
  } catch (e) {
    toast(e.message, 'error')
  }
})
</script>
