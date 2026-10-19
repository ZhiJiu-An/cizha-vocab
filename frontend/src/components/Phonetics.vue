<template>
  <component :is="tag" v-if="alwaysShow || uk || showUs" :class="wrapperClass">
    <span v-if="uk" :class="itemClass">
      <span class="pho-tag uk">{{ ukLabel }}</span>{{ uk }}
    </span>
    <span v-if="showUs" :class="itemClass">
      <span class="pho-tag us">{{ usLabel }}</span>{{ us }}
    </span>
  </component>
</template>

<script setup>
/**
 * 英美音标展示（P2-5）
 *
 * 原本在 Search / WordList / WordDetail / Review 四处各抄了一遍，
 * 且都隐含同一条规则：英美音标相同时只显示一次。抽出来避免改一处漏三处。
 *
 * 各处排版差异通过 props 传入，不去动既有 CSS：
 *   - 卡片：   wrapper-class="card-phos"   item-class="card-phonetic"
 *   - 词典栏： wrapper-class="dict-phos"   item-class="dict-phonetic"
 *   - 复习卡： wrapper-class="card-phos" + 标签改成「英/美」+ always-show
 */
import { computed } from 'vue'

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
})

const showUs = computed(() => !!props.us && props.us !== props.uk)
</script>
