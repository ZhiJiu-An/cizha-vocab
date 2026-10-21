<template>
  <component :is="tag" v-if="alwaysShow || uk || showUs" :class="wrapperClass">
    <span v-if="uk" :class="itemClass">
      <span class="pho-tag uk">{{ ukLabel }}</span>{{ uk }}
      <button
        v-if="word"
        class="speak-btn"
        :class="{ playing: playing === 'uk' }"
        :title="`朗读（${showUs ? '英式' : accentName}）`"
        @click.stop="onSpeak('uk')"
      >{{ playing === 'uk' ? '⏳' : '🔊' }}</button>
    </span>
    <span v-if="showUs" :class="itemClass">
      <span class="pho-tag us">{{ usLabel }}</span>{{ us }}
      <button
        v-if="word"
        class="speak-btn"
        :class="{ playing: playing === 'us' }"
        title="朗读（美式）"
        @click.stop="onSpeak('us')"
      >{{ playing === 'us' ? '⏳' : '🔊' }}</button>
    </span>
  </component>
</template>

<script setup>
/**
 * 英美音标展示（P2-5）+ 发音按钮
 *
 * 原本在 Search / WordList / WordDetail / Review 四处各抄了一遍，
 * 且都隐含同一条规则：英美音标相同时只显示一次。抽出来避免改一处漏三处。
 *
 * 各处排版差异通过 props 传入，不去动既有 CSS：
 *   - 卡片：   wrapper-class="card-phos"   item-class="card-phonetic"
 *   - 词典栏： wrapper-class="dict-phos"   item-class="dict-phonetic"
 *   - 复习卡： wrapper-class="card-phos" + 标签改成「英/美」+ always-show
 *
 * 发音（P3-1）：传入 word 后每个音标块出现喇叭按钮，点击朗读。
 *   - 英美都显示时：点英标播英式、点美标播美式
 *   - 只显示一条（英美相同）时：按设置页「发音偏好」选口音
 */
import { computed, ref } from 'vue'
import { prefs } from '../utils/prefs'
import { speak } from '../utils/speak'
import { toast } from '../utils'

const props = defineProps({
  uk: { type: String, default: '' },
  us: { type: String, default: '' },
  ukLabel: { type: String, default: 'UK' },
  usLabel: { type: String, default: 'US' },
  wrapperClass: { type: String, default: 'card-phos' },
  itemClass: { type: String, default: 'card-phonetic' },
  tag: { type: String, default: 'div' },
  // 为 true 时即使两边都为空也渲染外层容器（复习卡的翻面布局需要占位）
  alwaysShow: { type: Boolean, default: false },
  // 用于发音的单词文本；为空则不显示喇叭按钮
  word: { type: String, default: '' },
})

const showUs = computed(() => !!props.us && props.us !== props.uk)
const accentName = computed(() => (prefs.accent === 'uk' ? '英式' : '美式'))

const playing = ref(null) // 'uk' | 'us' | null

async function onSpeak(block) {
  if (playing.value) return
  // 单条显示（英美相同）时按用户发音偏好选口音；两条都显示时按点击的块
  const accent = block === 'us' ? 'us' : showUs.value ? 'uk' : prefs.accent
  playing.value = block
  try {
    await speak(props.word, accent)
  } catch (e) {
    toast(e.message || '发音失败', 'error')
  } finally {
    playing.value = null
  }
}
</script>

<style scoped>
.speak-btn {
  border: 0;
  background: none;
  padding: 0 0 0 5px;
  font-size: 12px;
  cursor: pointer;
  opacity: .55;
  vertical-align: baseline;
  transition: opacity .15s, transform .15s;
}
.speak-btn:hover { opacity: 1; transform: scale(1.12); }
.speak-btn.playing { opacity: 1; cursor: wait; }
</style>
