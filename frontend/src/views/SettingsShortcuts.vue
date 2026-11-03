<template>
  <div class="shortcuts-page">
    <section class="intro">
      <div>
        <div class="eyebrow">SHORTCUTS</div>
        <h1>手比脑子快。</h1>
        <p class="subtitle">
          点右侧键位后直接按下新组合，Esc 取消录制。全局快捷键只在桌面版生效。
        </p>
      </div>
    </section>

    <!-- ===== 全局快捷键（Rust 壳持有） ===== -->
    <section class="settings-group">
      <div class="group-head">
        <h3>全局快捷键</h3>
        <p>词札在后台时也能响应；修改后立即生效，并写入 shortcuts.json。</p>
      </div>
      <div v-if="!isTauri" class="desktop-tip">
        浏览器模式无法注册全局快捷键，请在桌面版词札中修改。
      </div>
      <div class="settings-card">
        <div v-for="item in globalShortcuts" :key="item.id" class="key-row">
          <div class="set-info">
            <b>{{ item.label }}</b>
            <small v-if="item.error" class="error-text">{{ item.error }}</small>
            <small v-else>{{ item.accelerator ? '点击右侧键位修改' : '当前未设置' }}</small>
          </div>
          <div class="key-actions">
            <button
              class="key-btn"
              :class="{ recording: recordingKey === `global:${item.id}` }"
              :disabled="!isTauri"
              @click="startRecord('global', item)"
            >
              <template v-if="recordingKey === `global:${item.id}`">按下新组合…</template>
              <template v-else-if="item.accelerator">
                <kbd v-for="token in acceleratorTokens(item.accelerator)" :key="token">{{ token }}</kbd>
              </template>
              <template v-else><span class="unset">未设置</span></template>
            </button>
            <button
              v-if="item.accelerator && isTauri"
              class="link-btn"
              title="禁用该快捷键"
              @click="applyGlobal(item.id, '')"
            >清除</button>
          </div>
        </div>
        <div v-if="!globalShortcuts.length" class="empty-row">桌面版启动后可在这里配置。</div>
      </div>
      <div class="group-foot">
        <span v-if="globalNotice" class="notice">{{ globalNotice }}</span>
        <button class="link-btn" :disabled="!isTauri" @click="resetGlobal">恢复全部默认</button>
      </div>
    </section>

    <!-- ===== 局内快捷键（prefs.json） ===== -->
    <section class="settings-group">
      <div class="group-head">
        <h3>局内快捷键</h3>
        <p>只在词札窗口内生效，随偏好一起保存；复习页的 1/2/3 仅在翻面后可用。</p>
      </div>
      <div class="settings-card">
        <div v-for="action in IN_APP_ACTIONS" :key="action.id" class="key-row">
          <div class="set-info">
            <b>{{ action.label }}</b>
            <small>{{ action.group }}{{ action.allowBare ? ' · 可单键' : '' }}</small>
          </div>
          <div class="key-actions">
            <span v-if="inAppError[action.id]" class="error-text">{{ inAppError[action.id] }}</span>
            <button
              class="key-btn"
              :class="{ recording: recordingKey === `inapp:${action.id}` }"
              @click="startRecord('inapp', action)"
            >
              <template v-if="recordingKey === `inapp:${action.id}`">按下新组合…</template>
              <template v-else>
                <kbd v-for="token in comboTokens(currentInApp[action.id])" :key="token">{{ token }}</kbd>
              </template>
            </button>
            <button
              v-if="currentInApp[action.id] !== action.default"
              class="link-btn"
              @click="resetInApp(action)"
            >默认</button>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import { prefs } from '../utils/prefs'
import { toast } from '../utils'
import {
  IN_APP_ACTIONS,
  acceleratorFromEvent,
  acceleratorTokens,
  comboFromEvent,
  comboText,
  comboTokens,
  effectiveInAppShortcuts,
  validateInAppCombo,
} from '../utils/shortcuts'

const isTauri = '__TAURI_INTERNALS__' in window
const recordingKey = ref('')
const globalShortcuts = ref([])
const globalNotice = ref('')
const inAppError = reactive({})
const currentInApp = computed(() => effectiveInAppShortcuts(prefs.shortcuts.in_app))

let recordingTarget = null

function startRecord(scope, item) {
  if (scope === 'global' && !isTauri) return
  inAppError[item.id] = ''
  globalNotice.value = ''
  recordingTarget = { scope, id: item.id, allowBare: Boolean(item.allowBare) }
  recordingKey.value = `${scope}:${item.id}`
}

function stopRecord() {
  recordingTarget = null
  recordingKey.value = ''
}

function actionLabel(id) {
  return IN_APP_ACTIONS.find((action) => action.id === id)?.label || id
}

async function loadGlobal() {
  if (!isTauri) return
  try {
    globalShortcuts.value = await invoke('get_global_shortcuts')
  } catch (error) {
    globalNotice.value = String(error)
  }
}

function updateGlobal(info) {
  const index = globalShortcuts.value.findIndex((item) => item.id === info.id)
  if (index >= 0) globalShortcuts.value[index] = info
}

async function applyGlobal(id, accelerator) {
  try {
    const info = await invoke('set_global_shortcut', { id, accelerator })
    updateGlobal(info)
    globalNotice.value = ''
    toast(accelerator ? `已绑定 ${info.label}` : `已清除 ${info.label}`, 'success')
  } catch (error) {
    globalNotice.value = String(error)
    toast(String(error), 'error')
    await loadGlobal()
  } finally {
    stopRecord()
  }
}

async function resetGlobal() {
  if (!isTauri) return
  if (!window.confirm('把所有全局快捷键恢复为默认组合？')) return
  try {
    globalShortcuts.value = await invoke('reset_global_shortcuts')
    globalNotice.value = ''
    toast('全局快捷键已恢复默认', 'success')
  } catch (error) {
    globalNotice.value = String(error)
    toast(String(error), 'error')
  }
}

function resetInApp(action) {
  delete prefs.shortcuts.in_app[action.id]
  inAppError[action.id] = ''
  toast(`「${action.label}」已恢复默认`, 'success')
}

function onRecordKeydown(e) {
  if (!recordingTarget) return
  e.preventDefault()
  e.stopPropagation()

  if (e.key === 'Escape') {
    stopRecord()
    return
  }

  const { scope, id, allowBare } = recordingTarget
  if (scope === 'global') {
    const accelerator = acceleratorFromEvent(e)
    // 只按下修饰键时继续等待，不打断录制
    if (accelerator) applyGlobal(id, accelerator)
    return
  }

  const combo = comboFromEvent(e, { allowBare })
  if (!combo) {
    if (!e.metaKey && !e.ctrlKey && !e.altKey && !e.shiftKey) {
      inAppError[id] = '至少需要一个修饰键（⌘ / ⌥ / ⇧）'
    }
    return
  }
  const error = validateInAppCombo(combo, { id, map: prefs.shortcuts.in_app })
  if (error) {
    inAppError[id] = error
    return
  }
  inAppError[id] = ''
  prefs.shortcuts.in_app = { ...prefs.shortcuts.in_app, [id]: combo }
  stopRecord()
  toast(`「${actionLabel(id)}」已改为 ${comboText(combo)}`, 'success')
}

onMounted(() => {
  loadGlobal()
  window.addEventListener('keydown', onRecordKeydown, true)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onRecordKeydown, true)
})
</script>

<style scoped>
.shortcuts-page { max-width: 760px; padding-bottom: 32px; }

.shortcuts-page .intro { margin-bottom: 26px; }
.shortcuts-page .subtitle { margin-top: 6px; }

.settings-group { margin-bottom: 26px; }
.group-head { margin-bottom: 10px; }
.group-head h3 { font-size: 14px; font-weight: 600; color: var(--text); }
.group-head p { font-size: 11px; color: var(--muted); margin-top: 4px; }

.desktop-tip {
  margin-bottom: 10px;
  padding: 10px 14px;
  border-radius: 8px;
  background: #fdf6e3;
  border: 1px solid #f0e2bd;
  font-size: 12px;
  color: #8a6d3b;
}

.settings-card {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 4px 20px;
  box-shadow: var(--shadow-sm);
}

.key-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 0;
  border-bottom: 1px solid var(--border);
}
.key-row:last-child { border-bottom: 0; }

.set-info b { display: block; font-size: 13px; font-weight: 500; color: var(--text); }
.set-info small { display: block; font-size: 11px; color: var(--muted); margin-top: 4px; }
.set-info .error-text { color: #b4472f; }

.key-actions { display: flex; align-items: center; gap: 10px; flex: 0 0 auto; }

.key-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-width: 116px;
  justify-content: center;
  font-family: inherit;
  font-size: 12px;
  color: var(--text);
  background: #fbfcf9;
  border: 1px solid var(--border);
  border-radius: 7px;
  padding: 8px 12px;
  cursor: pointer;
  transition: border-color .2s, box-shadow .2s, background .2s;
}
.key-btn:hover { border-color: var(--primary-2); }
.key-btn:disabled { cursor: not-allowed; opacity: .55; }
.key-btn.recording {
  color: var(--primary);
  border-color: var(--primary-2);
  background: var(--bg-soft);
  box-shadow: 0 0 0 3px rgba(52, 103, 79, .12);
}
.key-btn .unset { color: var(--muted); }

.key-btn kbd {
  font-family: inherit;
  font-size: 12px;
  line-height: 1;
  padding: 3px 6px;
  border-radius: 4px;
  background: #eef2ea;
  border: 1px solid var(--border);
  color: var(--text);
}

.link-btn {
  font-family: inherit;
  font-size: 11px;
  color: var(--muted);
  background: none;
  border: 0;
  padding: 2px 0;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 3px;
}
.link-btn:hover { color: var(--primary); }
.link-btn:disabled { cursor: not-allowed; opacity: .5; }

.group-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 8px;
}
.notice { font-size: 11px; color: #b4472f; }
.empty-row { padding: 16px 0; font-size: 12px; color: var(--muted); }
</style>
