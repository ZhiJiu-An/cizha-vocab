import { defineConfig } from 'vitest/config'

// 只跑纯函数：不引 jsdom，待测代码不碰 DOM。
// 需要控制平台分支的用例用 vi.stubGlobal('navigator', ...) 代替。
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/__tests__/**/*.test.js'],
  },
})
