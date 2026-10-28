# Changelog

本项目的所有重要变更记录在此。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 新增

- **Tauri 2 桌面壳层（Phase 3-4 ✅）**
  - `src-tauri/`：完整 Tauri 2 桌面项目（壳层 + sidecar + 托盘 + 全局快捷键）
  - `src-tauri/src/main.rs`：
    - spawn PyInstaller onedir 后端 → 探测可用端口 → 后台轮询 `/api/health` 就绪 → WebView 加载前端（不阻塞 UI）
    - 启动页改为 `frontend/public/loading.html`，避免 eval 注入被丢弃/覆盖导致的白屏、卡 loading
    - 启动失败自动换端口重试一次；仍失败时在启动页显示具体原因，而不是无限等待或直接闪退
    - 系统托盘（右键菜单：打开 / 隐藏 / 退出；左键切换窗口可见性）
    - 全局快捷键 Cmd+Shift+C（唤起/隐藏窗口）
    - CloseRequested → 隐藏到托盘（不退出），退出时 kill 后端进程（不再残留后台服务）
  - `src-tauri/capabilities/default.json`：global-shortcut 权限
  - `src-tauri/icons/`：自动生成全套图标（icon.png / 32x32 / 128x128 / icon.ico / icon.icns）
  - `scripts/prepare-sidecar.py`：把 PyInstaller onedir 产物复制到 `src-tauri/resources/backend/`
  - `scripts/generate-icons.py`：PIL 画图标 + iconutil 生成 icns
  - `cargo tauri build` 产物：词札.app (95 MB) + 词札_0.2.1_aarch64.dmg (42 MB)

- **多平台 PyInstaller CI（Phase 2 ✅）**
  - `.github/workflows/desktop_build.yml`：tag `v*` 时自动并发打 macOS arm64 / Linux amd64 / Windows amd64 三份 PyInstaller onedir 产物，打包为 tar.gz 挂 Release 附件

### 修复

- **桌面版启动慢 / 卡 loading / 偶发启动失败**
  - PyInstaller 由 onefile 改为 onedir：启动不再每次解压 ~39MB，实测就绪时间从 ~6 秒降到 0.6~2 秒
  - 启动页由 `eval(document.write(...))` 改为静态 `loading.html`：不会出现 eval 丢失导致的白屏，也不会晚于跳转覆盖前端
  - 等待后端就绪从「端口被占用」改为真实 HTTP `/api/health` 探测，超时 30 秒并自动重试一次
  - 退出时（Cmd+Q / 托盘退出）统一 kill 后端子进程，修复多次启动后残留僵尸后端的问题

- **桌面壳层遗留问题（单实例 / 异常退出 / 日志）**
  - 接入 `tauri-plugin-single-instance`：重复启动只唤起已有窗口，不再出现第二个托盘图标、第二个后端，也避免两个进程同时读写同一个 SQLite
  - 接管 SIGTERM / SIGINT / SIGHUP：注销、`kill`、Ctrl+C 不再留下孤儿后端；清理顺序改为先 SIGTERM 优雅关闭、3 秒未退出再强杀，并在 `pre_exec` 里重置子进程信号掩码（否则后端继承屏蔽字后收不到 SIGTERM）
  - 后端 stdout/stderr 写入 `~/Library/Logs/com.cizha.vocab/backend.log`（超过 5MB 轮转 `.log.1`），启动失败提示直接给出日志路径，不再「丢弃输出 + 提示看系统日志」

- **桌面壳层遗留问题（P2：崩溃恢复 / 端口竞态 / 打包校验）**
  - 启动成功后看护后端：进程崩溃会自动回到启动页并重启（失败时显示原因，20 秒后再试）
  - 页面导航失败不再静默：错误会写回启动页，不会永远停在 loading
  - 端口改为 `--port 0` 由系统分配，后端就绪后把实际端口写进 ready 文件回传，彻底消除「先探测空端口再 bind」的竞态
  - `prepare-sidecar.py` 额外生成 `backend-manifest.json`；`build.rs` 在 release 构建时校验 exe 大小与文件数，缺资源或后端产物过期会直接报错，避免把旧后端打进 App

- **发布工程（签名 / 公证暂缓）**
  - CI 新增 macOS App 构建任务：打 `v*` tag 时自动产出 `.dmg` 并挂到 Release（未签名，首次打开仍需右键「打开」）
  - 版本号统一为 0.2.1（Tauri / Cargo / 前端 / 后端 `APP_VERSION` / 有道 UA）
  - 主窗口改为 `visible: false`，等 loading 页画出首帧后再显示，消除启动瞬间的白底闪烁
  - `.gitignore` 补上 `build/cizha-backend/`（手动指定 `--workpath build` 时的 PyInstaller 中间目录）

- **桌面 App 后端引擎（Phase 0-1 ✅）**
  - `backend/app/paths.py`：统一资源路径，首次启动把 SQLite / llm_config.json / .env 复制到用户目录（macOS `~/Library/Application Support/cizha/`、Windows `%APPDATA%/cizha/`、Linux `$XDG_DATA_HOME/cizha/`）
  - `backend/run.py`：PyInstaller 入口脚本，替代 `uvicorn app.main:app` 命令行方式
  - `build/pyinstaller/cizha-backend.spec`：打包配置，`collect_all app` 确保 FastAPI 路由隐式 import 全收

## [0.1.1] - 2026-10-22

### 修复

- 未知 API 路径在未构建前端时返回英文 `Not Found`，现统一返回 JSON 404 `接口不存在`（CI 环境依赖前端产物的问题）
- `setup.sh` 中全角括号紧贴变量名导致 `set -u` 报 `unbound variable`，安装中断

### 变更

- 版本号统一为 `0.1.1`：`/api/health`、前端 `package.json`、词典请求 User-Agent
- 新增 CI 冒烟任务：`bash -n` + shellcheck、真实执行 `setup.sh`、`start.sh` 启动后校验健康接口 / 中文 404 / SPA 托管

### 文档

- 版本徽章链接到 Release 页，便于直接查看最新版本
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

[Unreleased]: https://github.com/ZhiJiu-An/cizha-vocab/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/ZhiJiu-An/cizha-vocab/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/ZhiJiu-An/cizha-vocab/releases/tag/v0.1.0
