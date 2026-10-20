<template>
  <div class="settings-page">
    <h2 class="page-title">⚙️ 模型设置</h2>
    <p class="page-sub">切换大模型，无需重启服务。保存前会自动做连通性测试。</p>

    <!-- 文本模型：翻译、领域详解 -->
    <ModelConfigCard
      kind="text"
      title="文本模型"
      subtitle="用于单词翻译与领域详解的生成。"
    />

    <!-- 视觉模型：图片取词 -->
    <ModelConfigCard
      kind="vision"
      title="视觉模型（图片取词）"
      subtitle="用于识别截图里的术语。模型名必填；Base URL 与 API Key 留空则与文本模型共用，切换后立即生效。"
      class="vision-card"
    />

    <!-- 配置小抄 -->
    <div class="settings-card info">
      <h3>配置小抄</h3>
      <ul>
        <li>地址填到 <code>/v1</code> 这一层，不要带 <code>/chat/completions</code>。</li>
        <li>DeepSeek 官方 API 没有视觉模型，视觉模型需另配一家（如阿里百炼 <code>qwen3-vl-plus</code>、智谱 <code>glm-4v</code>）。</li>
        <li>两套配置独立保存于 <code>backend/data/llm_config.json</code>，优先于 <code>backend/.env</code>；点「恢复 .env 默认」只清除当前这张卡片。</li>
        <li>「连通测试会消耗少量 token」：每次点保存或测试都会真实调用一次模型。</li>
      </ul>
    </div>
  </div>
</template>

<script setup>
import ModelConfigCard from '../components/ModelConfigCard.vue'
</script>

<style scoped>
.settings-page { max-width: 640px; margin: 0 auto; padding: 24px 16px; }
.page-title { font-size: 22px; font-weight: 700; color: var(--text); margin-bottom: 6px; }
.page-sub { color: var(--text-light); font-size: 13px; margin-bottom: 20px; }

/* 视觉模型卡片用左边框颜色区分，避免两张卡片长得一模一样 */
.vision-card {
  border-left: 3px solid #7c3aed;
}

.settings-card {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
  box-shadow: var(--shadow-sm);
  margin-bottom: 16px;
}
.settings-card.info { background: var(--bg-soft); }
.settings-card.info h3 { font-size: 15px; margin-bottom: 8px; }
.settings-card.info ul { font-size: 13px; color: var(--text-light); padding-left: 20px; line-height: 1.8; }
.settings-card.info code { background: #e8e8e8; padding: 1px 5px; border-radius: 3px; font-size: 12px; }
</style>
