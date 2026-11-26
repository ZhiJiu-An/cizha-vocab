# Changelog

本项目的所有重要变更记录在此。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 新增

- **截图选区层增加壳层兜底关闭**
  - 选区层显示时再次按 `⌥S` 立即关闭，不再发起新的截图
  - 选区层保持不抢焦点，Esc 由壳层临时接管；取消后迟到的拖拽提交会被忽略
  - 无操作 60 秒后由壳层自动关闭，避免页面脚本失效时全屏置顶窗口卡住桌面
  - 兜底关闭原因写入 `screen.log`

- **截图取词改为「文字进输入框」**
  - `⌥S` 截图识别后不再在快查浮窗展示图片，识别出的原文直接填入输入框、可编辑，再按普通查询流程给出领域翻译

- **主窗口支持切换领域提示词**
  - 搜索框右侧新增领域下拉（默认 / 大模型 / 软件工程 / 医学 / 金融），切换后用同一模型的不同提示词重新翻译
  - 选择持久化到 `prefs.json` 的 `translate_preset`；新增 `GET /api/llm/presets`，翻译接口支持 `?preset=`

- **设置页改为分类页签**
  - `/settings` 变成壳层页签（通用 / 模型 / 快捷键），子路由 `general`、`models`、`shortcuts`；旧的 `/settings/models` 深链保持可用
  - 通用页承接昵称、发音偏好、学习提醒；模型页保留原配置能力并迁入「配置小抄」

- **局内快捷键可自定义**
  - 新增动作表（聚焦搜索 / 新建 / 页面切换 / 保存 / 复习翻面与自评 / 关闭快查），默认值沿用原行为
  - 设置页可直接录键，校验系统保留组合与同表冲突；配置随偏好写入 `prefs.json` 的 `shortcuts.in_app`
  - App.vue / WordForm / Review / QuickTranslate 统一按配置匹配，不再写死组合键

- **全局快捷键可查看与改绑**
  - Rust 侧新增 `get_global_shortcuts` / `set_global_shortcut` / `reset_global_shortcuts`
  - 绑定结果落盘 `app_config_dir()/shortcuts.json`，启动时读取并注册；空组合表示禁用
  - 改绑失败自动回滚旧键，错误回传设置页；被其他应用占用不影响应用启动

- **快查浮窗同时展示词典与大模型**
  - 浮窗内新增「词典释义」段：词典命中时给出音标、通用释义与双语例句（原文证据），未收录时整段不占位
  - 内容按「词典在上、大模型翻译在下」两段排列，整体可滚动

### 变更

- 前端引入 vitest，为快捷键解析 / 流式翻译切分 / 时间文案等纯函数补单元测试，并接入 CI
  - 新增 `cd frontend && npm run test`；只测纯函数，不引入组件与 DOM 测试框架，构建产物不含测试代码
- 数据库连接改为 WAL 日志模式并设置 5 秒忙等待超时，后端重启的窗口期不再出现 `database is locked`
  - 备份 / 迁移库文件时需一并复制 `cizha.db-wal` / `cizha.db-shm`，或先退出 App（正常退出会自动合并回主库）
- 启动时的数据回填（补齐复习日期 + 标签归一）改为首次启动执行一次，执行记录写入新增的 `schema_meta` 表
  - 二次启动不再对 `words` 做全表扫描；新增列与索引的结构补齐仍每次幂等执行，老库随时可以自愈
  - 代价：若日后手工把标签改成未归一形态，不会再被启动迁移自动修复（接口侧仍会归一）
- CSV 批量导入改为整批判重 + 一次批量写入，5000 行文件的数据库语句数从「每行一条」降到个位数
  - 跳过已存在词条（大小写不敏感）、同一文件内重复只取第一条、旧版 10 / 11 列 CSV 兼容，行为均不变
- 快查浮窗的领域翻译改用主窗口同一套逻辑：尊重 `prefs.json` 的 `translate_preset`（此前固定走默认领域），整句仍自动走通用译文
- 快查浮窗默认出现在主屏右上角，尺寸改为 520×620 并固定不可缩放
- 设置页三个页签居中排列
- 后端 `PUT /api/prefs` 新增 `shortcuts.in_app` 字段，旧客户端缺字段时自动补默认值；对未知类型与超长键值做清洗
- 后端测试由 210 项增至 219 项

### 修复

- **截图时不再把后台的词札主窗口顶到前台**
  - 根因：点击透明选区层会让它取得焦点，macOS 随即激活词札，并把该应用所有可见窗口一起抬到前台
  - 选区层打开前若主窗口可见但词札不在前台，先隐藏主窗口；截图结束或取消后保持隐藏，需要时从托盘 / Dock 召回

- **截图取词只截到桌面 / 反复申请屏幕录制权限**
  - 截图改为应用内原生实现：`⌥S` 创建全屏透明选区层（`/shot`），前端上报选区后用 `CGWindowListCreateImage` 取图、ImageIO 编码 PNG，**不再调用 `/usr/sbin/screencapture`**——子进程每次调用都会重新触发系统授权弹窗
  - 截图前用 `CGPreflightScreenCaptureAccess` 预检；未授权时在快查浮窗给出明确指引，并新增「打开屏幕录制设置」按钮（`open_screen_recording_settings`）
  - 每次启动最多主动申请一次授权，避免每次按 `⌥S` 都被系统弹窗打断；授权后需重启 App 生效
- **macOS 产物启用 ad-hoc 自签**：`bundle.macOS.signingIdentity: "-"`，并关闭 hardened runtime（实测 ad-hoc + hardened runtime + entitlements 会 `EBADEXEC` 无法启动）。此前实际只有 linker 签名（无 `_CodeSignature`），TCC 无法稳定保存屏幕录制等授权，导致「允许后仍反复申请」
- 前端由后端 `http://127.0.0.1:<端口>` 托管，Tauri 视其为 **remote 来源**：补齐 `capabilities/default.json` 的 `remote.urls`，并新增 `permissions/app.toml` 登记 `cizha-ipc` 允许的自定义命令
  - 修复快捷键设置页全局快捷键不显示（`Command get_global_shortcuts not allowed by ACL`）
  - 修复快查浮窗 `listen` / `quick_get_pending` 被拒导致输入与截图取词均无结果

## [0.2.3] - 2026-11-03

### 新增

- **桌面全局快捷键 + 快查浮窗**
  - `⌥A` 输入翻译：按需创建置顶小窗 `/quick`，输入单词回车即流式展示「中文定名 / 缩写展开 / 领域详解」，`Esc` 收起
  - `⌥S` 截图取词：调用系统 `/usr/sbin/screencapture -i -x -o` 框选区域 → data URL → 复用 `/api/ocr/extract`；首次使用需在「系统设置 → 隐私与安全 → 屏幕录制」授权
  - 浮窗内点击术语或「在主窗口查看完整结果」→ 主窗口跳到 `/?q=xxx`，复用完整双栏结果
  - 后端崩溃重启换端口时，已创建的浮窗同步导航到新端口
  - 应用内快捷键：`⌘K` 聚焦顶栏搜索、`⌘1~⌘5` 切换页面、`⌘N` 新建词条、`⌘S` 保存、`Esc` 关闭悬浮详情 / 快查浮窗
  - 新增依赖：`@tauri-apps/api`（前端）、`base64`（截图编码）

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

- **设置重启后全部变回默认值**（昵称 / 发音口音 / 学习提醒）
  - 根因：桌面版后端以 `--port 0` 随机端口启动，WebView 的 localStorage 按 `scheme://host:port` 的 origin 隔离，每次重启都等于换了一个存储空间
  - 偏好改为落盘 `<data_dir>/prefs.json`：新增 `GET/PUT /api/prefs`，原子写（临时文件 + `os.replace`），文件损坏或字段非法时回退默认值
  - 前端启动时先 `loadPrefs()` 回填再挂载，变更防抖写回后端；localStorage 仅作同步缓存
  - 「今日已提醒」一并纳入偏好持久化，重启后不会重复弹出学习提醒
  - 后续快捷键设置可复用同一套偏好通道，不再受端口变化影响

- **复习页「错词优先」点击无响应**
  - 移除该选项与相关逻辑，复习队列统一按到期时间排序
  - 统计页「最常忘记的词」说明文案同步修正

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


## [0.2.2] - 2026-11-02

### 安全

- **打包产物不再携带开发者数据**：PyInstaller 配置移除 `backend/data/`，`prepare-sidecar.py` 在复制后额外清洗 `.env`、`llm_config.json` 与 `*.db`，避免真实 API Key 和个人词库随 App 分发
- **下架含真实数据的安装包**：v0.2.1 的 `cizha_0.2.1_aarch64.dmg` 内含开发者真实 API Key 与个人词库，已从 Release 删除并重新发布本版本
- **公开仓库历史清理**：内部开发文档（`AGENTS.md`、`ARCHITECTURE.md`、`PRD.md`、`.trae/`、`docs/desktop/`）与其中的本机绝对路径已从 Git 历史中移除

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

[0.2.3]: https://github.com/ZhiJiu-An/cizha-vocab/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/ZhiJiu-An/cizha-vocab/compare/v0.2.1...v0.2.2
[0.1.1]: https://github.com/ZhiJiu-An/cizha-vocab/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/ZhiJiu-An/cizha-vocab/releases/tag/v0.1.0
