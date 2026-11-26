<template>
  <div
    class="shot-root"
    @mousedown.prevent="onDown"
    @mousemove="onMove"
    @mouseup="onUp"
    @contextmenu.prevent="cancel"
  >
    <div v-if="hasRect" class="shot-box" :style="boxStyle"></div>
    <div v-if="hasRect" class="shot-size" :style="sizeStyle">{{ sizeText }}</div>
    <div class="shot-tip">
      <span>拖动选择区域</span>
      <span>按 Esc 或鼠标右键取消</span>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { invoke } from '@tauri-apps/api/core'

// 同一份前端也会跑在浏览器里（npm run dev），非 Tauri 环境下 IPC 一律跳过
const isTauri = Boolean(window.__TAURI_INTERNALS__)

const start = ref(null)
const cur = ref(null)

const rect = computed(() => {
  if (!start.value || !cur.value) return { x: 0, y: 0, w: 0, h: 0 }
  return {
    x: Math.min(start.value.x, cur.value.x),
    y: Math.min(start.value.y, cur.value.y),
    w: Math.abs(cur.value.x - start.value.x),
    h: Math.abs(cur.value.y - start.value.y),
  }
})
const hasRect = computed(() => rect.value.w >= 2 && rect.value.h >= 2)
const boxStyle = computed(() => ({
  left: `${rect.value.x}px`,
  top: `${rect.value.y}px`,
  width: `${rect.value.w}px`,
  height: `${rect.value.h}px`,
}))
const sizeText = computed(() => `${Math.round(rect.value.w)} × ${Math.round(rect.value.h)}`)
const sizeStyle = computed(() => ({
  left: `${rect.value.x}px`,
  top: `${Math.max(rect.value.y - 26, 4)}px`,
}))

function pointOf(e) {
  return { x: e.clientX, y: e.clientY }
}

function onDown(e) {
  if (e.button !== 0) return
  start.value = pointOf(e)
  cur.value = pointOf(e)
}

function onMove(e) {
  if (!start.value) return
  cur.value = pointOf(e)
}

async function onUp(e) {
  if (!start.value) return
  cur.value = pointOf(e)
  // 误触 / 太小：留在选区层，让用户重来
  if (rect.value.w < 6 || rect.value.h < 6) {
    start.value = null
    cur.value = null
    return
  }
  if (!isTauri) return
  try {
    await invoke('finish_region_shot', {
      x: rect.value.x,
      y: rect.value.y,
      width: rect.value.w,
      height: rect.value.h,
    })
  } catch {
    start.value = null
    cur.value = null
  }
}

async function cancel() {
  if (!isTauri) return
  try {
    await invoke('cancel_region_shot')
  } catch {
    /* 窗口已关闭时忽略 */
  }
}

function onKeydown(e) {
  if (e.key !== 'Escape') return
  e.preventDefault()
  cancel()
}

onMounted(() => {
  // 选区窗口需要透明背景，否则整块 body 底色会挡住要截的内容
  document.documentElement.classList.add('shot-transparent')
  window.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  document.documentElement.classList.remove('shot-transparent')
  window.removeEventListener('keydown', onKeydown)
})
</script>

<style scoped>
.shot-root {
  position: fixed;
  inset: 0;
  cursor: crosshair;
  background: transparent;
  user-select: none;
}

.shot-box {
  position: absolute;
  border: 1px solid rgba(94, 234, 212, 0.95);
  /* 只描边，不压暗屏幕：浅色/深色背景都能看清 */
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.22);
  background: transparent;
  pointer-events: none;
}

.shot-tip {
  position: fixed;
  /* 左下角，但抬高到程序坞上方，避免被 Dock 盖住 */
  left: 20px;
  bottom: 96px;
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 7px 12px;
  border-radius: 7px;
  background: rgba(0, 0, 0, 0.62);
  color: #fff;
  font-size: 12px;
  line-height: 1.5;
  letter-spacing: 0.3px;
  white-space: nowrap;
  pointer-events: none;
}

.shot-size {
  position: absolute;
  padding: 1px 7px;
  border-radius: 5px;
  background: rgba(0, 0, 0, 0.65);
  color: #5eead4;
  font-size: 11px;
  pointer-events: none;
}
</style>
