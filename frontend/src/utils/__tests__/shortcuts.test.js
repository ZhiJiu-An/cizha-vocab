import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  acceleratorFromEvent,
  acceleratorText,
  comboFromEvent,
  comboText,
  defaultInAppShortcuts,
  effectiveInAppShortcuts,
  IN_APP_ACTIONS,
  isMac,
  matchesCombo,
  normalizeCombo,
  validateInAppCombo,
} from '../shortcuts'

/** 固定平台分支：待测函数只读 navigator.platform */
function usePlatform(platform) {
  vi.stubGlobal('navigator', { platform })
}

function keyEvent(fields) {
  // 只带 keyFromEvent / 修饰键判断真正会读的字段，避免依赖真实 KeyboardEvent
  return { key: '', code: '', metaKey: false, ctrlKey: false, altKey: false, shiftKey: false, ...fields }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('isMac', () => {
  it('按 navigator.platform 判断', () => {
    usePlatform('MacIntel')
    expect(isMac()).toBe(true)
    usePlatform('Win32')
    expect(isMac()).toBe(false)
  })
})

describe('normalizeCombo', () => {
  it('归一化大小写与别名', () => {
    expect(normalizeCombo('cmd+shift+k')).toBe('Mod+Shift+K')
    expect(normalizeCombo('CONTROL+alt+1')).toBe('Ctrl+Alt+1')
    expect(normalizeCombo('option+meta+esc')).toBe('Mod+Alt+Esc')
  })

  it('修饰键按固定顺序排列', () => {
    expect(normalizeCombo('shift+alt+ctrl+cmd+k')).toBe('Mod+Ctrl+Alt+Shift+K')
  })

  it('同一修饰键重复只保留一次', () => {
    expect(normalizeCombo('mod+cmd+k')).toBe('Mod+K')
  })

  it('非法输入返回空串', () => {
    expect(normalizeCombo('')).toBe('')
    expect(normalizeCombo('   ')).toBe('')
    expect(normalizeCombo(null)).toBe('')
    expect(normalizeCombo(42)).toBe('')
  })
})

describe('comboFromEvent', () => {
  it('macOS 下 ⌘ 记作 Mod，⌃ 记作 Ctrl', () => {
    usePlatform('MacIntel')
    expect(comboFromEvent(keyEvent({ code: 'KeyK', key: 'k', metaKey: true }))).toBe('Mod+K')
    expect(comboFromEvent(keyEvent({ code: 'KeyK', key: 'k', metaKey: true, ctrlKey: true })))
      .toBe('Mod+Ctrl+K')
  })

  it('非 macOS 下 Ctrl 记作 Mod，⌘ 不参与', () => {
    usePlatform('Win32')
    expect(comboFromEvent(keyEvent({ code: 'KeyK', key: 'k', ctrlKey: true }))).toBe('Mod+K')
    expect(comboFromEvent(keyEvent({ code: 'KeyK', key: 'k', metaKey: true }))).toBe('')
  })

  it('没有修饰键时默认拒绝录制', () => {
    usePlatform('MacIntel')
    expect(comboFromEvent(keyEvent({ code: 'Space', key: ' ' }))).toBe('')
  })

  it('allowBare 下只放行功能键与数字', () => {
    usePlatform('MacIntel')
    expect(comboFromEvent(keyEvent({ code: 'Space', key: ' ' }), { allowBare: true })).toBe('Space')
    expect(comboFromEvent(keyEvent({ code: 'Digit1', key: '1' }), { allowBare: true })).toBe('1')
    expect(comboFromEvent(keyEvent({ code: 'KeyA', key: 'a' }), { allowBare: true })).toBe('')
  })
})

describe('matchesCombo', () => {
  it('修饰键必须完全一致', () => {
    usePlatform('MacIntel')
    const e = keyEvent({ code: 'KeyK', key: 'k', metaKey: true })
    expect(matchesCombo(e, 'Mod+K')).toBe(true)
    expect(matchesCombo({ ...e, shiftKey: true }, 'Mod+K')).toBe(false)
    expect(matchesCombo(keyEvent({ code: 'KeyK', key: 'k' }), 'Mod+K')).toBe(false)
  })

  it('Esc / Space 等裸键可匹配', () => {
    usePlatform('MacIntel')
    expect(matchesCombo(keyEvent({ key: 'Escape' }), 'Esc')).toBe(true)
    expect(matchesCombo(keyEvent({ code: 'Space', key: ' ' }), 'Space')).toBe(true)
  })

  it('非 macOS 下 Ctrl 才能充当 Mod', () => {
    usePlatform('Win32')
    expect(matchesCombo(keyEvent({ code: 'KeyK', key: 'k', ctrlKey: true }), 'Mod+K')).toBe(true)
    expect(matchesCombo(keyEvent({ code: 'KeyK', key: 'k', metaKey: true }), 'Mod+K')).toBe(false)
  })

  it('空组合永不命中', () => {
    usePlatform('MacIntel')
    expect(matchesCombo(keyEvent({ code: 'KeyK', key: 'k', metaKey: true }), '')).toBe(false)
  })
})

describe('comboText / acceleratorText', () => {
  it('macOS 用符号、无分隔符', () => {
    usePlatform('MacIntel')
    expect(comboText('Mod+Shift+K')).toBe('⌘⇧K')
    expect(comboText('Space')).toBe('空格')
    expect(acceleratorText('CmdOrCtrl+Shift+KeyC')).toBe('⌘⇧C')
    expect(acceleratorText('ArrowUp')).toBe('↑')
  })

  it('其它平台用文字与 + 分隔', () => {
    usePlatform('Win32')
    expect(comboText('Mod+Shift+K')).toBe('Ctrl+Shift+K')
    expect(acceleratorText('CmdOrCtrl+Shift+KeyC')).toBe('Ctrl+Shift+C')
  })
})

describe('acceleratorFromEvent', () => {
  it('至少一个修饰键才生成 accelerator', () => {
    usePlatform('MacIntel')
    expect(acceleratorFromEvent(keyEvent({ code: 'KeyC', metaKey: true })))
      .toBe('CmdOrCtrl+KeyC')
    expect(acceleratorFromEvent(keyEvent({ code: 'KeyC' }))).toBe('')
  })

  it('不安全的键码直接拒绝', () => {
    usePlatform('MacIntel')
    expect(acceleratorFromEvent(keyEvent({ code: 'Compose', metaKey: true }))).toBe('')
  })
})

describe('validateInAppCombo', () => {
  it('空组合与裸字母被拦下', () => {
    expect(validateInAppCombo('', { id: 'focus_search' })).toBe('请按下一个组合键')
    expect(validateInAppCombo('K', { id: 'focus_search' })).toBe('至少需要一个修饰键（⌘ / ⌥ / ⇧）')
    expect(validateInAppCombo('A', { id: 'close_quick' })).toBe('字母键需要配合修饰键')
  })

  it('系统 / 编辑器保留键被拦下', () => {
    expect(validateInAppCombo('Mod+Q', { id: 'focus_search' }))
      .toBe('这个组合被系统或编辑器占用了，换一个')
    expect(validateInAppCombo('Mod+C', { id: 'save_word' }))
      .toBe('这个组合被系统或编辑器占用了，换一个')
  })

  it('与其它动作重复时报冲突', () => {
    expect(validateInAppCombo('Mod+K', { id: 'new_word', map: {} }))
      .toBe('与「聚焦搜索」冲突')
  })

  it('允许裸键的动作在无冲突时通过', () => {
    const map = { review_forget: 'Mod+9', review_fuzzy: 'Mod+8', review_remember: 'Mod+7' }
    expect(validateInAppCombo('1', { id: 'review_remember', map })).toBe('')
  })
})

describe('默认表与覆盖合并', () => {
  it('默认表覆盖全部动作', () => {
    const defaults = defaultInAppShortcuts()
    expect(Object.keys(defaults).sort()).toEqual(IN_APP_ACTIONS.map((a) => a.id).sort())
    expect(defaults.focus_search).toBe('Mod+K')
  })

  it('旧偏好缺项时自动补齐默认值', () => {
    const merged = effectiveInAppShortcuts({ focus_search: 'Mod+P' })
    expect(merged.focus_search).toBe('Mod+P')
    expect(merged.save_word).toBe('Mod+S')
  })
})
