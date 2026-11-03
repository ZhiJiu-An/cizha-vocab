<template>
  <div class="settings-shell">
    <nav class="settings-tabs" aria-label="设置分类">
      <router-link to="/settings/general">通用</router-link>
      <router-link to="/settings/models">模型</router-link>
      <router-link to="/settings/shortcuts">快捷键</router-link>
    </nav>
    <router-view />
  </div>
</template>

<script setup>
// 设置页只负责页签与子路由；各页内容见 SettingsGeneral / ModelSettings / SettingsShortcuts
</script>

<style scoped>
.settings-shell { max-width: 1120px; margin: 0 auto; }

.settings-tabs {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  margin-bottom: 24px;
  background: var(--bg-soft);
  border: 1px solid var(--border);
  border-radius: 10px;
}
.settings-tabs a {
  padding: 8px 18px;
  border-radius: 7px;
  font-size: 12px;
  color: var(--muted);
  text-decoration: none;
  transition: background .2s, color .2s, box-shadow .2s;
}
.settings-tabs a:hover { color: var(--primary); }
.settings-tabs a.router-link-active {
  background: var(--card-bg);
  color: var(--primary);
  font-weight: 600;
  box-shadow: var(--shadow-sm);
}
</style>
