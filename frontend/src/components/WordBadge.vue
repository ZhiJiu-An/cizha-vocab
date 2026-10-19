<template>
  <span class="badge" :class="type.badge">{{ type.text }}</span>
</template>

<script setup>
/**
 * 词条类型徽章（P2-5）
 *
 * 原本 WordList / WordDetail / Review 各自写了一遍「缩写·有通用释义 / 缩写·纯术语 /
 * 普通单词」的渲染。类型由 utils.cardType() 统一推导，组件只负责展示，
 * 这样调用方每张卡片只需算一次类型。
 */
defineProps({
  type: { type: Object, required: true },   // { cls, badge, text }
})
</script>
