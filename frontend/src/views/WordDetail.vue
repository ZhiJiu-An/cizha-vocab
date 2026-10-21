<template>
  <div>
    <div class="page-title" style="display: flex; align-items: center; gap: 12px">
      <button class="btn btn-ghost btn-sm" @click="router.back()">← 返回</button>
      📄 词条详情
    </div>

    <div v-if="loading" class="empty">加载中…</div>

    <div v-else-if="word" class="detail-card">
      <div class="card-head" style="margin-bottom: 22px">
        <span class="card-abbr">
          {{ word.abbreviation }}
          <span v-if="word.cn_term" class="card-cn">{{ word.cn_term }}</span>
          <WordBadge :type="wordType" />
        </span>
        <Phonetics :uk="word.phonetic_uk" :us="word.phonetic_us" :word="word.abbreviation" />
      </div>

      <div v-if="word.full_name" class="detail-block">
        <div class="k">全称</div>
        <div class="v">{{ word.full_name }}</div>
      </div>

      <div class="detail-block">
        <div class="k">💡 我的理解</div>
        <div class="v">{{ word.my_meaning }}</div>
      </div>

      <div class="detail-block">
        <div class="k">📖 通用释义</div>
        <div class="v muted">{{ word.api_meaning || '—' }}</div>
      </div>

      <div v-if="word.domain_detail" class="detail-block">
        <div class="k">🤖 领域详解</div>
        <div class="v">{{ word.domain_detail }}</div>
      </div>

      <div v-if="examples.length" class="detail-block">
        <div class="k">例句</div>
        <div v-for="(ex, i) in examples" :key="i" class="v dict-example">
          · {{ ex.en }}
          <span v-if="ex.zh" class="zh">{{ ex.zh }}</span>
        </div>
      </div>

      <div class="detail-block">
        <div class="k">标签</div>
        <div class="v">
          <template v-if="parseTags(word.tags).length">
            <span
              v-for="t in parseTags(word.tags)"
              :key="t"
              class="card-tag"
              style="margin-right: 6px"
            >
              #{{ t }}
            </span>
          </template>
          <span v-else class="muted">—</span>
        </div>
      </div>

      <div v-if="word.note" class="detail-block">
        <div class="k">备注</div>
        <div class="v">{{ word.note }}</div>
      </div>

      <div class="detail-block">
        <div class="k">时间</div>
        <div class="v muted">
          创建于 {{ relativeTime(word.created_at) }} · 更新于 {{ relativeTime(word.updated_at) }}
        </div>
      </div>

      <!-- 复习状态与队列控制（v0.11）：这些字段自 v0.5 就存在，
           但此前详情页完全看不到，in_review 也没有任何入口能改 -->
      <div class="detail-block">
        <div class="k">🧠 记忆复习</div>
        <div class="v">
          <div class="rv-line">
            <span class="rv-k">当前档位</span>
            第 {{ word.review_stage + 1 }} 档 · 每 {{ stageDays(word.review_stage) }} 天
          </div>
          <div class="rv-line">
            <span class="rv-k">下次复习</span>
            <span :class="isOverdue ? 'queue-off' : ''">{{ nextReviewLabel(word.next_review_at) }}</span>
          </div>
          <div class="rv-line">
            <span class="rv-k">累计复习</span>
            {{ word.review_count }} 次<template v-if="word.last_reviewed_at">
              · 上次 {{ relativeTime(word.last_reviewed_at) }}</template>
          </div>
          <div class="rv-actions">
            <span :class="word.in_review ? 'queue-on' : 'queue-off'">
              {{ word.in_review ? '在复习队列中' : '已移出复习队列' }}
            </span>
            <button
              class="btn btn-outline btn-sm"
              :disabled="queueBusy"
              @click="toggleQueue"
            >
              {{ queueBusy ? '处理中…' : (word.in_review ? '⏸ 移出队列' : '▶ 加入队列') }}
            </button>
            <button
              class="btn btn-ghost btn-sm"
              :disabled="queueBusy"
              title="把档位与累计次数清零，当作新词重新开始"
              @click="resetProgress"
            >
              ↺ 重置进度
            </button>
          </div>
        </div>
      </div>

      <div
        style="
          display: flex;
          gap: 12px;
          margin-top: 24px;
          padding-top: 20px;
          border-top: 1px solid var(--border-2);
        "
      >
        <button class="btn btn-primary" @click="router.push(`/words/${word.id}/edit`)">
          ✏️ 编辑
        </button>
        <button class="btn btn-ghost" style="color: #dc2626" @click="showConfirm = true">
          🗑 删除
        </button>
      </div>
    </div>

    <div v-else class="empty">
      <div class="icon">🔍</div>
      <p>词条不存在</p>
    </div>

    <div v-if="showConfirm" class="modal-mask" @click.self="showConfirm = false">
      <div class="modal">
        <h3>删除词条</h3>
        <p>确定要删除「{{ word.abbreviation }}」吗？此操作不可恢复。</p>
        <div class="modal-actions">
          <button class="btn btn-ghost" @click="showConfirm = false">取消</button>
          <button class="btn btn-primary" style="background: #dc2626" @click="confirmDelete">
            删除
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Phonetics from '../components/Phonetics.vue'
import WordBadge from '../components/WordBadge.vue'
import { deleteWord, getWord, resetReviewProgress, restoreWords, updateWord } from '../api'
import { cardType, nextReviewLabel, parseTags, relativeTime, stageDays, toast } from '../utils'

const route = useRoute()
const router = useRouter()

const word = ref(null)
const loading = ref(true)
const showConfirm = ref(false)
const queueBusy = ref(false)

// 例句兼容：v0.4 为 {en, zh} 对象，旧数据可能仍是纯字符串。
// 一次性归一成数组后模板直接用，避免每条例句渲染时重复调用（P2-5）
const examples = computed(() => (word.value?.examples || []).map(exampleText))
const wordType = computed(() => cardType(word.value || {}))

// 下次复习日期已过（或就是今天）时高亮，提示「该复习了」
const isOverdue = computed(() => {
  const iso = word.value?.next_review_at
  if (!iso) return false
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return false
  const startOf = (x) => { const y = new Date(x); y.setHours(0, 0, 0, 0); return y }
  return startOf(d) <= startOf(new Date())
})

function exampleText(ex) {
  if (ex && typeof ex === 'object') return { en: ex.en || '', zh: ex.zh || '' }
  return { en: String(ex ?? ''), zh: '' }
}

// 移出 / 加入复习队列（v0.11）
async function toggleQueue() {
  if (!word.value || queueBusy.value) return
  const next = word.value.in_review ? 0 : 1
  queueBusy.value = true
  try {
    const updated = await updateWord(word.value.id, { in_review: next })
    word.value = updated
    toast(next ? '已加入复习队列' : '已移出复习队列', 'success')
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    queueBusy.value = false
  }
}

// 重置复习进度（v0.11）：误点「记住」把档位推进去后的补救路径
async function resetProgress() {
  if (!word.value || queueBusy.value) return
  if (!confirm('把「' + word.value.abbreviation + '」的复习进度清零，当作新词重新开始？')) return
  queueBusy.value = true
  try {
    await resetReviewProgress(word.value.id)
    word.value = await getWord(word.value.id)   // 重新拉一次，四个复习字段一起刷新
    toast('复习进度已重置', 'success')
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    queueBusy.value = false
  }
}

async function confirmDelete() {
  showConfirm.value = false
  const snapshot = { ...word.value }      // 删前留快照，用于撤销
  try {
    await deleteWord(snapshot.id)
    toast('已删除', 'success', {
      label: '撤销',
      handler: async () => {
        const res = await restoreWords([snapshot])
        toast(
          res.restored
            ? `已恢复「${snapshot.abbreviation}」`
            : '恢复失败：同名词条已存在',
          res.restored ? 'success' : 'error',
        )
      },
    })
    router.push('/words')
  } catch (e) {
    toast(e.message, 'error')
  }
}

onMounted(async () => {
  try {
    word.value = await getWord(Number(route.params.id))
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    loading.value = false
  }
})
</script>
