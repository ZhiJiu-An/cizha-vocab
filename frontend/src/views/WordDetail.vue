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
          <span class="badge" :class="cardType(word).badge">{{ cardType(word).text }}</span>
        </span>
        <div v-if="word.phonetic_uk || word.phonetic_us" class="card-phos">
          <span v-if="word.phonetic_uk" class="card-phonetic">
            <span class="pho-tag uk">UK</span>{{ word.phonetic_uk }}
          </span>
          <span v-if="word.phonetic_us && word.phonetic_us !== word.phonetic_uk" class="card-phonetic">
            <span class="pho-tag us">US</span>{{ word.phonetic_us }}
          </span>
        </div>
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

      <div v-if="word.examples && word.examples.length" class="detail-block">
        <div class="k">例句</div>
        <div v-for="(ex, i) in word.examples" :key="i" class="v dict-example">
          · {{ exampleText(ex).en }}
          <span v-if="exampleText(ex).zh" class="zh">{{ exampleText(ex).zh }}</span>
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
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { deleteWord, getWord } from '../api'
import { cardType, parseTags, relativeTime, toast } from '../utils'

const route = useRoute()
const router = useRouter()

const word = ref(null)
const loading = ref(true)
const showConfirm = ref(false)

// 例句兼容：v0.4 为 {en, zh} 对象，旧数据可能仍是纯字符串
function exampleText(ex) {
  if (ex && typeof ex === 'object') return { en: ex.en || '', zh: ex.zh || '' }
  return { en: String(ex ?? ''), zh: '' }
}

async function confirmDelete() {
  showConfirm.value = false
  try {
    await deleteWord(word.value.id)
    toast('已删除', 'success')
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
