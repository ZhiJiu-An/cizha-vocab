# Changelog

本项目的所有重要变更记录在此。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 修复

- 未知 API 路径在未构建前端时返回英文 `Not Found`，现统一返回 JSON 404 `接口不存在`（CI 环境依赖前端产物的问题）
- `setup.sh` 中全角括号紧贴变量名导致 `set -u` 报 `unbound variable`，安装中断

### 文档

- 版本徽章统一为 `v0.1.0` 并链接 Release 页
- 更新界面截图（词典 / 复习 / 统计 / 词库）
- 新增 CHANGELOG、CONTRIBUTING、SECURITY 与 Issue / PR 模板

## [0.1.0] - 2026-10-21

首个公开版本。

### 新增

- **词典搜索**：有道词典与大模型 SSE 流式翻译双栏对照；五段式领域输出（定名 / 全称 / 详解 / 例句 / 译文）
- **图片取词**：上传图片或 `Ctrl+V` 粘贴截图，由视觉模型识别并解释
- **发音**：音标点击播放
- **词库管理**：卡片浏览、标签筛选、批量操作、悬浮快速预览、CSV 导入导出、删除可撤销
- **间隔重复复习**：六档间隔（1 / 2 / 4 / 7 / 15 / 30 天）、3D 翻卡三档自评、错词本、到点学习提醒
- **学习统计**：总量 / 新增 / 复习概览，标签分布与年度趋势，纯 CSS 图表零依赖
- **模型配置**：文本 / 视觉模型分角色管理，保存前自动连通性测试，四套领域提示词预设并支持自定义
- **部署**：单端口托管前端产物（FastAPI 服务 `frontend/dist`），SQLite 本地存储，`setup` / `start` 脚本一键运行

### 安全

- `.env`、`backend/data/`（含用户配置与 API Key）不纳入版本控制
- 历史提交中的作者邮箱统一为 GitHub noreply 地址

[Unreleased]: https://github.com/ZhiJiu-An/cizha-vocab/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ZhiJiu-An/cizha-vocab/releases/tag/v0.1.0
