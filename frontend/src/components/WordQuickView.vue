<template>
  <div class="modal-mask" @click.self="emit('close')">
    <div class="modal quick-view">
      <div v-if="loading" class="qv-empty">加载中…</div>

      <template v-else-if="word">
        <div class="card-head" style="margin-bottom: 18px">
          <span class="card-abbr">
            {{ word.abbreviation }}
            <span v-if="word.cn_term" class="card-cn">{{ word.cn_term }}</span>
            <WordBadge :type="wordType" />
          </span>
          <Phonetics :uk="word.phonetic_uk" :us="word.phonetic_us" :word="word.abbreviation" />
          <span class="card-spacer"></span>
          <button class="qv-close" title="关闭" @click="emit('close')">✕</button>
        </div>

        <div class="qv-body">
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
                >#{{ t }}</span>
              </template>
              <span v-else class="muted">—</span>
            </div>
          </div>

          <div v-if="word.note" class="detail-block">
            <div class="k">备注</div>
            <div class="v">{{ word.note }}</div>
          </div>

          <!-- 复习状态（v0.11）：字段自 v0.5 就有，此前悬浮窗看不到 -->
          <div class="detail-block">
            <div class="k">🧠 记忆复习</div>
            <div class="v">
              <div class="rv-line">
                <span class="rv-k">当前档位</span>
                第 {{ word.review_stage + 1 }} 档 · 每 {{ stageDays(word.review_stage) }} 天
              </div>
              <div class="rv-line">
                <span class="rv-k">下次复习</span>{{ nextReviewLabel(word.next_review_at) }}
              </div>
              <div class="rv-line">
                <span class="rv-k">累计复习</span>{{ word.review_count }} 次
                <span v-if="!word.in_review" class="queue-off">· 已移出复习队列</span>
              </div>
            </div>
          </div>

          <div class="detail-block">
            <div class="k">时间</div>
            <div class="v muted">
              创建于 {{ relativeTime(word.created_at) }} · 更新于 {{ relativeTime(word.updated_at) }}
            </div>
          </div>
        </div>

        <div class="qv-actions">
          <button class="btn btn-primary" @click="router.push(`/words/${word.id}/edit`)">✏️ 编辑</button>
          <button class="btn btn-ghost" style="color: #dc2626" @click="emit('delete', word)">🗑 删除</button>
        </div>
      </template>

      <div v-else class="qv-empty">词条不存在</div>
    </div>
  </div>
</template>

<script setup>
/**
 * 词库悬浮详情窗（P3-2）：点卡片就地预览，不再跳转 /words/:id。
 * 编辑仍跳编辑页；删除抛给列表页走统一的确认弹窗。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import Phonetics from './Phonetics.vue'
import WordBadge from './WordBadge.vue'
import { getWord } from '../api'
import { cardType, nextReviewLabel, parseTags, relativeTime, stageDays, toast } from '../utils'

const props = defineProps({
  wordId: { type: Number, required: true },
})
const emit = defineEmits(['close', 'delete'])

const router = useRouter()
const word = ref(null)
const loading = ref(true)

// 例句兼容：v0.4 为 {en, zh} 对象，旧数据可能仍是纯字符串
const examples = computed(() => (word.value?.examples || []).map(exampleText))
const wordType = computed(() => cardType(word.value || {}))

function exampleText(ex) {
  if (ex && typeof ex === 'object') return { en: ex.en || '', zh: ex.zh || '' }
  return { en: String(ex ?? ''), zh: '' }
}

onMounted(async () => {
  try {
    word.value = await getWord(props.wordId)
  } catch (e) {
    toast(e.message, 'error')
    emit('close')
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.quick-view {
  max-width: 640px;
  max-height: 82vh;
  display: flex;
  flex-direction: column;
  padding: 24px 28px;
}
.qv-body { overflow-y: auto; flex: 1; min-height: 0; }
.qv-empty { text-align: center; color: var(--muted); padding: 40px 0; }
.qv-close {
  border: 0;
  background: none;
  font-size: 14px;
  color: var(--muted);
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 6px;
  transition: background .15s, color .15s;
}
.qv-close:hover { background: var(--border-2); color: var(--text); }
.qv-actions {
  display: flex;
  gap: 12px;
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid var(--border-2);
}
</style>
