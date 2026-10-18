<template>
  <div>
    <div class="page-title">🏷️ 标签</div>

    <div v-if="tags.length" class="tags" style="gap: 10px">
      <button
        v-for="t in tags"
        :key="t.name"
        class="tag"
        style="padding: 8px 16px; font-size: 13.5px"
        @click="go(t.name)"
      >
        #{{ t.name }} <span style="opacity: 0.65">{{ t.count }}</span>
      </button>
    </div>

    <div v-else class="empty">
      <div class="icon">🏷️</div>
      <p>还没有标签，新建词条时填「标签」即可生成</p>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { listTags } from '../api'
import { toast } from '../utils'

const router = useRouter()
const tags = ref([])

function go(name) {
  router.push({ path: '/words', query: { tag: name } })
}

onMounted(async () => {
  try {
    tags.value = await listTags()
  } catch (e) {
    toast(e.message, 'error')
  }
})
</script>
