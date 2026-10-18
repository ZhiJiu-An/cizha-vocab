<template>
  <div>
    <div class="page-title">{{ isEdit ? '✏️ 编辑词条' : '✏️ 新建术语 / 单词' }}</div>

    <div class="form-card">
      <div class="section-title">基本信息</div>

      <div class="form-row">
        <label>缩写 / 主词 <span class="req">*</span></label>
        <input
          v-model="form.abbreviation"
          placeholder="如 RAG / token"
          @keyup.enter="onAutofill"
        />
      </div>

      <div class="form-row">
        <label>全称（缩写术语填，普通单词可留空）</label>
        <input v-model="form.full_name" placeholder="如 Retrieval-Augmented Generation" />
      </div>

      <div class="input-group">
        <div class="form-row">
          <label>🇬🇧 英式音标</label>
          <input v-model="form.phonetic_uk" placeholder="/ˈtəʊkən/" />
        </div>
        <div class="form-row">
          <label>🇺🇸 美式音标</label>
          <input v-model="form.phonetic_us" placeholder="/ˈtoʊkən/" />
        </div>
      </div>

      <!-- 自动补全区 -->
      <div class="auto-fill-box">
        <div :class="hint.cls" style="margin-bottom: 10px">{{ hint.text }}</div>
        <button class="btn btn-outline" :disabled="looking" @click="onAutofill">
          {{ looking ? '查询中…' : '🔍 自动补全' }}
        </button>
      </div>

      <div class="section-title">释义（最重要）</div>

      <div class="form-row">
        <label>💡 我的理解 <span class="req">*</span> — 这是你真正想记住的</label>
        <textarea
          v-model="form.my_meaning"
          placeholder="用自己的话解释这个词在你领域里的意思..."
        ></textarea>
      </div>

      <div class="form-row">
        <label>📖 通用释义（词典返回，可改可删）</label>
        <textarea v-model="form.api_meaning" placeholder="点「自动补全」后自动填入..."></textarea>
      </div>

      <div class="section-title">其他</div>

      <div class="form-row">
        <label>例句（每行一条）</label>
        <textarea v-model="form.examplesText" placeholder="每条例句占一行"></textarea>
      </div>

      <div class="form-row">
        <label>标签（逗号分隔）</label>
        <input v-model="form.tags" placeholder="大模型, RAG, 论文" />
      </div>

      <div class="form-row">
        <label>备注</label>
        <textarea v-model="form.note" placeholder="其他想记录的..."></textarea>
      </div>

      <div style="display: flex; gap: 12px; margin-top: 24px">
        <button
          class="btn btn-primary"
          style="padding: 10px 28px"
          :disabled="saving"
          @click="save"
        >
          {{ saving ? '保存中…' : '💾 保存' }}
        </button>
        <button class="btn btn-ghost" @click="reset">🔄 清空</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { createWord, getWord, lookupDictionary, updateWord } from '../api'
import { toast } from '../utils'

const route = useRoute()
const router = useRouter()

const editId = computed(() => (route.params.id ? Number(route.params.id) : null))
const isEdit = computed(() => editId.value !== null)

const EMPTY = {
  abbreviation: '',
  full_name: '',
  phonetic_uk: '',
  phonetic_us: '',
  my_meaning: '',
  api_meaning: '',
  examplesText: '',
  tags: '',
  note: '',
}

const form = reactive({ ...EMPTY })

const looking = ref(false)
const saving = ref(false)
const hint = ref({ text: '✨ 点「自动补全」可调词典 API 回填音标、通用释义、例句', cls: 'hint' })

/* ===== 词典自动补全 ===== */
async function onAutofill() {
  const word = form.abbreviation.trim()
  if (!word) {
    toast('请先填写缩写 / 主词', 'error')
    return
  }
  looking.value = true
  hint.value = { text: '🔍 正在查询词典…', cls: 'hint' }
  try {
    const r = await lookupDictionary(word)
    if (!r.found) {
      hint.value = { text: `⚠️ ${r.message}`, cls: 'hint warn' }
      return
    }
    if (r.phonetic_uk) form.phonetic_uk = r.phonetic_uk
    if (r.phonetic_us) form.phonetic_us = r.phonetic_us
    if (r.api_meaning) form.api_meaning = r.api_meaning
    if (r.examples?.length) form.examplesText = r.examples.join('\n')
    hint.value = { text: '✨ 已回填音标、通用释义、例句，可继续编辑', cls: 'hint ok' }
  } catch (e) {
    hint.value = { text: `⚠️ ${e.message}`, cls: 'hint warn' }
    toast(e.message, 'error')
  } finally {
    looking.value = false
  }
}

/* ===== 保存 ===== */
async function save() {
  if (!form.abbreviation.trim()) {
    toast('缩写 / 主词必填', 'error')
    return
  }
  if (!form.my_meaning.trim()) {
    toast('「我的理解」必填', 'error')
    return
  }

  saving.value = true
  const payload = {
    abbreviation: form.abbreviation.trim(),
    full_name: form.full_name.trim(),
    phonetic_uk: form.phonetic_uk.trim(),
    phonetic_us: form.phonetic_us.trim(),
    my_meaning: form.my_meaning.trim(),
    api_meaning: form.api_meaning.trim(),
    examples: form.examplesText
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean),
    tags: form.tags.trim(),
    note: form.note.trim(),
  }

  try {
    if (isEdit.value) {
      await updateWord(editId.value, payload)
      toast('已保存修改', 'success')
    } else {
      await createWord(payload)
      toast('已保存', 'success')
    }
    router.push('/words')
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    saving.value = false
  }
}

function reset() {
  Object.assign(form, EMPTY)
  hint.value = { text: '✨ 点「自动补全」可调词典 API 回填音标、通用释义、例句', cls: 'hint' }
}

/* ===== 编辑时载入原数据 ===== */
onMounted(async () => {
  if (!isEdit.value) return
  try {
    const w = await getWord(editId.value)
    Object.assign(form, {
      abbreviation: w.abbreviation || '',
      full_name: w.full_name || '',
      phonetic_uk: w.phonetic_uk || '',
      phonetic_us: w.phonetic_us || '',
      my_meaning: w.my_meaning || '',
      api_meaning: w.api_meaning || '',
      examplesText: (w.examples || []).join('\n'),
      tags: w.tags || '',
      note: w.note || '',
    })
  } catch (e) {
    toast(e.message, 'error')
    router.push('/words')
  }
})
</script>
