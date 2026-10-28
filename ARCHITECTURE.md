# ARCHITECTURE.md — 词札（cizha）技术架构与契约

| 项 | 内容 |
|---|---|
| 架构形态 | 桌面 App = Tauri 2（Rust 壳）+ Vue 3（前端）+ FastAPI/SQLite（Python sidecar） |
| 版本基线 | v0.2.1 |
| 文档状态 | 生效中（变更底线契约） |
| 配套文档 | [AGENTS.md](AGENTS.md) · [PRD.md](PRD.md) |

> 本文件回答「**怎么做**」，并把三层之间的边界写成**可执行的契约**。
> 任何跨层改动，先对照第 9 节「不变量」与第 11 节「变更影响清单」；破坏契约的改动必须同步改本文件。

---

## 1. 总体架构

```text
┌──────────────────────────────────────────────────────────────────┐
│ 词札.app（macOS Bundle）                                          │
│                                                                  │
│  ┌─────────────────────────────┐    HTTP 127.0.0.1:<系统分配>     │
│  │ Tauri 壳层（Rust）           │ ──────────────────────────────┐ │
│  │                             │                               │ │
│  │ · 窗口 / 托盘 / 全局快捷键    │   ① spawn + --port 0          │ │
│  │ · 单实例插件                 │      --ready-file             │ │
│  │ · 启动 / 看护 / 退出         │   ② ready 文件回传端口         │ │
│  │ · 日志重定向                 │   ③ GET /api/health 探测       │ │
│  │ · 信号接管（Unix）           │   ④ SIGTERM → 3s → SIGKILL     │ │
│  └───────────┬─────────────────┘                               │ │
│              │ WebView 加载                                     │ │
│              ▼                                                  │ │
│  ┌─────────────────────────────┐                               │ │
│  │ WebView（WKWebView）         │                               │ │
│  │ · loading.html（启动页，本地）│                               │ │
│  │ · Vue 3 前端（后端托管）      │                               │ │
│  └─────────────────────────────┘                               │ │
│                                                                 │ │
│  ┌─────────────────────────────────────────────────────────────┴─┐│
│  │ Python 后端（PyInstaller onedir sidecar）                      ││
│  │ FastAPI · SQLAlchemy 2 · SQLite · uvicorn                      ││
│  │ · /api/* 业务接口 · SSE 流式 · 静态资源与 SPA 兜底              ││
│  └────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────┘
```

**两个运行形态，同一份代码**：

| 形态 | 启动方式 | 前端来源 | 后端来源 |
|---|---|---|---|
| 源码 / 浏览器 | `run.py --port 8000` + `npm run dev` | Vite 5173（`/api` 代理到 8000） | `backend/app` |
| 单端口 | `npm run build` 后 `run.py --port 8000` | FastAPI 托管 `frontend/dist` | `backend/app` |
| 桌面 App | 壳层 spawn sidecar | FastAPI 托管打进包里的 dist | `Contents/Resources/backend/` |

---

## 2. 分层职责

| 层 | 位置 | 只做这些 | 明确不做 |
|---|---|---|---|
| 壳层（Rust） | [src-tauri/src/main.rs](file:///Users/azj/Documents/Project/Python_Project/cizha/src-tauri/src/main.rs) | 进程生命周期、窗口、托盘、快捷键、信号、日志 | 不写业务逻辑、不解析业务数据 |
| 前端（Vue） | [frontend/src](file:///Users/azj/Documents/Project/Python_Project/cizha/frontend/src) | 页面、交互、请求封装、本地偏好 | 不直接起进程、不读写本地文件、不持有 API Key |
| 后端（FastAPI） | [backend/app](file:///Users/azj/Documents/Project/Python_Project/cizha/backend/app) | 业务规则、持久化、外部 API 代理、静态资源托管 | 不管窗口、不管进程、不管托盘 |

**依赖方向**：壳层 → 前端（通过 WebView URL）→ 后端（HTTP）。反向不成立。壳层不 import 前端代码，前端不知道壳层存在（仅依赖 `loading.html` 的全局函数约定）。

---

## 3. 启动与生命周期时序

```text
main()
 ├─ block_exit_signals()            # 必须先于任何线程
 ├─ Builder
 │   ├─ single-instance 插件（最先生效）
 │   ├─ global-shortcut 插件
 │   └─ setup()
 │        ├─ manage(AppState)
 │        ├─ spawn_signal_handler() # sigwait 专用线程
 │        ├─ 200ms 后 window.show() # 等 loading 首帧，避免白闪
 │        ├─ thread::spawn(启动线程) # 不阻塞 setup
 │        │    ├─ start_backend()    # 最多 2 次尝试
 │        │    │    ├─ spawn_backend(--host 127.0.0.1 --port 0 --ready-file X)
 │        │    │    │    ├─ stdout/stderr → backend.log
 │        │    │    │    └─ pre_exec: 清空信号屏蔽字
 │        │    │    └─ wait_for_backend()
 │        │    │         ├─ 读 ready 文件 → 端口
 │        │    │         ├─ GET /api/health = 200 → OK
 │        │    │         └─ 30s 超时 / 进程退出 → Err
 │        │    ├─ navigate(http://127.0.0.1:<port>/)
 │        │    └─ monitor_backend()  # 2s 轮询
 │        ├─ setup_tray()
 │        └─ setup_shortcuts()
 └─ .run(event)
      ├─ RunEvent::Exit   → mark_stopping + cleanup_backend
      ├─ macOS Reopen     → show window
      └─ 托盘 QUIT         → mark_stopping + cleanup_backend + exit
```

### 3.1 关键时序参数（改动必须同步本表）

| 参数 | 值 | 位置 | 含义 |
|---|---|---|---|
| 窗口显示延迟 | 200ms | `setup` | 等 loading 首帧 |
| 就绪总超时 | 30s | `READY_TIMEOUT` | 单次尝试等待上限 |
| 启动尝试次数 | 2 | `START_ATTEMPTS` | 失败自动重试 |
| 就绪轮询间隔 | 150ms | `wait_for_backend` | 读 ready + health |
| 健康检查超时 | connect 400ms / read 800ms | `backend_health_ok` | 避免长阻塞 |
| 看护轮询 | 2s | `monitor_backend` | 检测崩溃 |
| 恢复失败退避 | 20s | `monitor_backend` | 避免刷屏 |
| 优雅退出等待 | 3s（50ms 轮询） | `terminate_child` | SIGTERM → SIGKILL |
| 日志轮转阈值 | 5MB | `open_backend_log` | `.log` → `.log.1` |

### 3.2 三种任务入口的退出职责

| 入口 | 行为 |
|---|---|
| 托盘「退出」 | `mark_stopping` → `cleanup_backend` → `app.exit(0)` |
| `RunEvent::Exit`（Cmd+Q / 系统注销） | `mark_stopping` → `cleanup_backend` |
| Unix 信号（SIGTERM/SIGINT/SIGHUP） | 专用线程 `sigwait` → 同上 → `app.exit(0)` |
| 关闭窗口 | `prevent_close` + `hide()`（不退出） |

---

## 4. 契约 A：壳层 ↔ 后端（进程级）

这是**最容易出错**的一组契约，逐条都是硬约束。

### A1. 启动参数

```text
cizha-backend --host 127.0.0.1 --port 0 --ready-file <abs-path>
```

| 参数 | 约定 |
|---|---|
| `--host` | 固定 `127.0.0.1`，禁止 `0.0.0.0` |
| `--port` | 固定 `0`，由系统分配 |
| `--ready-file` | 壳层为每次启动生成唯一路径；启动前先删除残留 |
| `stdin` | `null` |
| `stdout/stderr` | 追加写入日志文件（禁止 pipe） |

ready 文件命名：`$TMPDIR/cizha-backend-<壳层PID>-<attempt>-<nanos>.port`（[ready_file_path](file:///Users/azj/Documents/Project/Python_Project/cizha/src-tauri/src/main.rs#L292-L301)）。

### A2. ready 文件格式

- 内容：**纯文本十进制端口号**，如 `52341`，无 JSON、无换行要求（读取侧 `trim()`）。
- 写入时机：uvicorn `server.started == true` 之后，取 `server.servers[0].sockets[0].getsockname()[1]`（[run.py](file:///Users/azj/Documents/Project/Python_Project/cizha/backend/run.py#L26-L32)）。
- 生命周期：壳层读取成功后删除；失败重试时用新路径。
- **不变量**：ready 文件存在且内容可解析 ⇒ 端口已处于监听状态。

### A3. 就绪判定

`GET /api/health` 返回首行 `HTTP/1.1 200` 即视为就绪（只读前 64 字节，只校验状态行）。业务字段不参与判定，**禁止**在壳层解析 JSON。

### A4. 信号契约

| 项 | 约定 |
|---|---|
| 壳层 | `main()` 最先 `pthread_sigmask(SIG_BLOCK, {SIGTERM,SIGINT,SIGHUP})` |
| 处理方式 | 专用线程 `sigwait`，不做异步信号回调（可安全持有 Mutex / 调 Tauri API） |
| 子进程 | spawn 时 `pre_exec` 执行 `sigemptyset` + `sigprocmask(SIG_SETMASK)` 清空屏蔽字 |
| 终止顺序 | SIGTERM → 轮询 `try_wait` 3s → `kill()` + `wait()` |
| 已回收保护 | `terminate_child` 首行 `try_wait()` 返回 `Some` 则直接 return，绝不二次发信号 |

### A5. 日志契约

- 路径：`app.path().app_log_dir()` → macOS 为 `~/Library/Logs/com.cizha.vocab/backend.log`。
- 模式：append；单文件 > 5MB 重命名为 `backend.log.1`（只保留一份轮转）。
- 每次启动写分隔行：`===== 启动后端（端口由系统分配）=====`。
- stderr 通过 `try_clone()` 复用同一文件句柄；clone 失败则 stderr 丢弃（不得因此阻塞启动）。
- 启动失败提示必须包含日志绝对路径。

### A6. 崩溃与恢复

- 判定：`backend_exited()` = `try_wait()` 返回 `Some` 或 state 中无 child。
- 恢复：导航回启动页 → `start_backend` → 导航到新端口；失败则展示错误 + 退避 20s。
- 抑制：`stopping` 置位后看护线程必须退出，避免退出过程中把后端拉起。

---

## 5. 契约 B：前端 ↔ 后端（HTTP API）

### B1. 基础约定

| 项 | 约定 |
|---|---|
| Base URL | 前端固定 `/api`（同源），不写死端口 |
| 开发代理 | Vite `server.proxy['/api'] → http://127.0.0.1:8000` |
| 默认超时 | 15s；图片取词 60s；模型连通测试 30s |
| 错误体 | FastAPI 默认 `{"detail": "..."}` |
| 前端错误处理 | axios 拦截器统一取 `detail` 抛 `Error`（[api/index.js](file:///Users/azj/Documents/Project/Python_Project/cizha/frontend/src/api/index.js#L9-L15)） |
| 请求方法白名单（CORS） | `GET/POST/PUT/DELETE/OPTIONS` |
| CORS 允许来源 | 默认 `localhost/127.0.0.1:5173` 与 `:4173`，可用 `CIZHA_ALLOWED_ORIGINS` 覆盖 |

### B2. 接口清单

| 方法 | 路径 | 用途 | 备注 |
|---|---|---|---|
| GET | `/api/health` | 服务信息 + 版本 | 壳层就绪探针的唯一依据 |
| GET | `/api/dictionary/{word}` | 有道词典查询 | 路径参数需 URL 编码 |
| GET | `/api/translate/{word}` | 大模型领域解读 | **SSE 流式**（`text/event-stream`） |
| GET | `/api/words` | 词条列表 | 支持搜索 / 标签 / 分页参数 |
| POST | `/api/words` | 新建词条 | |
| GET | `/api/words/{id}` | 详情 | |
| PUT | `/api/words/{id}` | 更新 | |
| DELETE | `/api/words/{id}` | 删除 | 同时清理复习日志 |
| GET | `/api/words/lookup?word=` | 本地精确查找 | 搜索页判断是否已收藏 |
| POST | `/api/words/bulk-delete` | 批量删除 | 单请求单事务 |
| POST | `/api/words/bulk-tag` | 批量加标签 | 单请求单事务 |
| POST | `/api/words/restore` | 撤销删除 | 回灌完整词条 |
| POST | `/api/words/batch` | CSV 导入 | multipart |
| GET | `/api/words/export` | CSV 导出 | 直接下载 |
| GET | `/api/tags` | 标签聚合 | |
| GET | `/api/review/overview` | 复习概览 | |
| GET | `/api/review/due` | 到期队列 | 支持标签筛选 / 错词优先 |
| GET | `/api/review/mistakes` | 错词本 | 按忘记次数降序 |
| POST | `/api/review/{id}/answer` | 提交自评 | `result` ∈ 记住/模糊/忘记 |
| POST | `/api/review/{id}/reset` | 重置排期 | |
| GET | `/api/stats/summary` | 学习统计 | |
| POST | `/api/ocr/extract` | 图片取词 | multipart，≤10MB |
| GET/POST | `/api/llm/models` | 模型列表 / 新增 | 新增前连通测试 |
| PUT/DELETE | `/api/llm/models/{id}` | 编辑 / 删除 | id 为整数 |
| POST | `/api/llm/models/test` | 仅测试连通 | 视觉模型需传图 |
| POST | `/api/llm/models/{id}/default` | 设为默认 | 每类最多一个默认 |

### B3. SPA 与静态资源规则

| 请求路径 | 行为 |
|---|---|
| `/api/*`（未匹配） | 返回 JSON 404 `{"detail": "接口不存在"}`，**不得**回落 index.html |
| `/assets/*` | 直接由 `StaticFiles` 提供（dist/assets 存在时挂载） |
| 其他真实存在的文件 | 返回文件（含目录逃逸保护：解析后必须仍在 dist 内） |
| 其他路径 | 回落 `index.html`（vue-router history 模式） |
| `dist` 不存在时 `/` | 返回兜底信息 JSON（含构建提示） |
| `dist` 不存在时其他路径 | 404 `{"detail": "前端未构建"}` |

实现见 [main.py serve_spa](file:///Users/azj/Documents/Project/Python_Project/cizha/backend/app/main.py#L172-L198) 与 `resolve_spa_path`。

### B4. 前端页面路由

| 路径 | 页面 |
|---|---|
| `/` | Search（词典搜索，默认首页） |
| `/words` | WordList |
| `/new` | WordForm（新建） |
| `/words/:id` | WordDetail |
| `/words/:id/edit` | WordForm（编辑） |
| `/tags` | TagList |
| `/review` | Review |
| `/stats` | Stats |
| `/settings` | Settings |
| `/settings/models` | ModelSettings |
| 其他 | 重定向到 `/` |

---

## 6. 契约 C：壳层 ↔ 启动页（WebView）

| 项 | 约定 |
|---|---|
| 窗口初始 URL | `loading.html`（`frontend/public/`，随 dist 一起打进包） |
| 窗口可见性 | 配置 `visible:false`，200ms 后 `show()` + `set_focus()` |
| 启动页错误钩子 | `window.showStartupError(message: string)`，由 Rust 通过 `eval` 调用 |
| 调用重试 | 连续 10 次、间隔 200ms（页面可能尚未加载完成） |
| 导航失败 | `window.navigate()` 出错时同样调用该钩子，禁止静默 |
| 迁移到前端 | 成功后 `navigate("http://127.0.0.1:<port>/")` |

**不变量**：`showStartupError` 是壳层与启动页之间唯一的接口。改函数名必须同时改 Rust 侧字符串。

---

## 7. 契约 D：打包与资源

### D1. 产物形态

- PyInstaller **onedir**：`dist/cizha-backend/` = `cizha-backend` + `_internal/`。
- spec 关键配置：`EXE(..., exclude_binaries=True)` + `COLLECT(...)`（[cizha-backend.spec](file:///Users/azj/Documents/Project/Python_Project/cizha/build/pyinstaller/cizha-backend.spec)）。
- 打进包的数据：`frontend/dist/`、`data/`（含占位 db）、`.env.example`。
- 理由：onefile 每次启动解压，实测 6 秒；onedir 冷启 ≈2 秒、热启 ≤0.5 秒。

### D2. 资源映射

```json
"bundle": {
  "resources": { "resources/backend": "backend" }
}
```

运行时实际路径：`词札.app/Contents/Resources/backend/cizha-backend`。
壳层查找顺序：`resource_dir/backend` → `CARGO_MANIFEST_DIR/resources/backend` → `../dist/cizha-backend` → `../_pybuild/dist/cizha-backend`。

### D3. manifest 契约

由 [prepare-sidecar.py](file:///Users/azj/Documents/Project/Python_Project/cizha/scripts/prepare-sidecar.py) 生成 `src-tauri/resources/backend-manifest.json`：

```properties
# 由 scripts/prepare-sidecar.py 生成，build.rs 会据此校验后端资源
source=<dist/cizha-backend 绝对路径>
exe=cizha-backend
exe_size=<字节>
file_count=<文件数（递归）>
total_size=<字节>
generated_at=<unix 秒>
```

### D4. 构建校验（build.rs）

release 构建时依次校验，任一失败即 `panic` 终止构建：

1. `src-tauri/resources/backend/` 存在。
2. `backend-manifest.json` 存在且 `exe_size` / `file_count` 可解析。
3. 实际可执行文件大小 == `exe_size`。
4. 实际递归文件数 == `file_count`。
5. 若 `source` 仍存在，其可执行文件大小 == `exe_size`（防止重新打包后忘记复制）。

dev 构建只警告，不阻断。

### D5. 打包顺序（不可颠倒）

```bash
npm run build                                   # 1. 前端
python -m PyInstaller build/pyinstaller/cizha-backend.spec \
    --workpath _pybuild --distpath dist --clean # 2. 后端
python3 scripts/prepare-sidecar.py              # 3. 复制 + manifest
cargo tauri build --bundles app[,dmg]           # 4. 壳层
```

### D6. 版本一致性

| 位置 | 字段 |
|---|---|
| `src-tauri/tauri.conf.json` | `version`（同时决定 bundle 版本） |
| `frontend/package.json` + lock | `version` |
| `backend/app/main.py` | `APP_VERSION`（`/api/health` 返回值） |
| `backend/app/paths.py` | 兜底同值 |

---

## 8. 数据与配置路径

| 数据 | 源码模式 | 打包模式 |
|---|---|---|
| SQLite | `backend/data/cizha.db` | `~/Library/Application Support/cizha/cizha.db` |
| 模型配置（明文 Key） | `backend/data/llm_config.json` | `~/Library/Application Support/cizha/llm_config.json` |
| `.env` | `backend/.env` | `~/Library/Application Support/cizha/.env`（首次从内置 `.env.example` 复制） |
| 后端日志 | 终端输出 | `~/Library/Logs/com.cizha.vocab/backend.log` |
| 用户偏好（昵称 / 口音 / 提醒） | 浏览器 localStorage | WebView localStorage |
| ready 文件 | `$TMPDIR/cizha-backend-*.port` | 同 |

配置优先级：`llm_config.json`（运行时）> `.env` > 内置默认。

环境变量：`LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` / `LLM_VISION_*` / `CIZHA_ALLOWED_ORIGINS` / `CIZHA_DB_PATH`。

---

## 9. 不变量（Invariants）

违反任意一条，视为架构破坏：

1. 后端只监听 `127.0.0.1`，端口由系统分配，绝不硬编码。
2. ready 文件存在 ⇒ 端口可连接；壳层不解析业务 JSON 判定就绪。
3. 同一时刻最多一个壳层、一个后端（单实例插件 + SQLite 单写者）。
4. 任何退出入口都先 `mark_stopping` 再 `cleanup_backend`。
5. `try_wait` 已回收的 child 不再发信号。
6. 后端 stdout/stderr 只进文件，不接 pipe。
7. `/api/*` 未匹配一律 JSON 404，不回落 index.html。
8. App 内后端版本 = `tauri.conf.json` 版本 = `/api/health` 版本。
9. release 构建必须有 manifest 且校验通过。
10. `frontend/dist` 是前端唯一产物来源，打包与单端口托管都读它。

---

## 10. 故障模式与恢复

| 故障 | 表现 | 恢复机制 | 用户可见反馈 |
|---|---|---|---|
| 后端启动失败（首次） | 无端口 / 进程退出 | 自动重试 1 次 | 启动页错误 + 日志路径 |
| 后端启动超时 | 30s 内无 health 200 | 杀进程后重试 | 启动页错误 + 日志路径 |
| 后端运行中崩溃 | `try_wait` 有值 | 回启动页 → 重启 → 新端口 | 启动页动画 → 自动恢复 |
| 恢复连续失败 | 重启失败 | 展示错误，退避 20s | 错误提示，不刷屏 |
| 导航失败 | `navigate` 返回 Err | `showStartupError` | 启动页错误 |
| 端口被其他进程占用 | 系统换端口 | `--port 0` 天然规避 | 无感 |
| 打包后端过期 | 功能与源码不一致 | release 构建 panic | 构建期即失败 |
| 用户 `kill -9` 后端 | 页面失联 | 2s 内检出并恢复 | 启动页 → 恢复 |
| 用户 `kill -TERM` 壳层 | 壳层退出 | sigwait 清理后端 | 无残留 |

---

## 11. 变更影响清单

改任何一处，按表检查下游：

| 改动 | 必须同步 |
|---|---|
| 新增/修改 `/api` 路由 | 前端 `api/index.js`、PRD 接口表、本节 B2 |
| 修改启动参数 / ready 文件格式 | `run.py`、`main.rs`、AGENTS 第 4 节、本节 A1/A2 |
| 修改窗口初始 URL / `showStartupError` | `loading.html`、`main.rs`、本节第 6 节 |
| 修改日志路径或轮转策略 | `main.rs`、PRD DR-06、安装指南、本节 A5 |
| 修改打包流程 | spec、`prepare-sidecar.py`、`build.rs`、CI、本节 D |
| 修改数据目录 | `paths.py`、README、PRD 第 8 节、本节第 8 节 |
| 升级版本号 | 四处版本、`/api/health`、CHANGELOG |
| 修改超时 / 重试参数 | 本节 3.1 表格、PRD NFR |
| 新增托盘 / 快捷键 | `capabilities/default.json`、`main.rs`、PRD DR-09 |
| 修改 CORS | `main.py`、本节 B1、`.env.example` |

---

## 12. 持续集成

### 12.1 `ci.yml`（推送 main / PR）

`ruff check` + 后端全量 unittest（内存 SQLite 隔离，不会写真实数据）。

### 12.2 `desktop_build.yml`（打 `v*` tag）

```text
build-binaries（矩阵：macos-latest / ubuntu-latest / windows-latest）
  └─ PyInstaller onedir → tar.gz  → artifact cizha-backend-<platform>

build-desktop-macos（macos-latest）
  └─ 前端构建 → PyInstaller → prepare-sidecar → tauri build app,dmg
     → dist/release/cizha-vocab-<tag>-macos-arm64.dmg → artifact cizha-desktop-macos

release
  └─ needs: [build-binaries, build-desktop-macos]
     汇总所有 cizha-vocab-* → softprops/action-gh-release
```

---

## 13. 已知限制

| 限制 | 影响 | 触发改善条件 |
|---|---|---|
| 未签名 / 未公证（ad-hoc） | 首次打开需右键「打开」或手动放行 | 取得 Developer ID |
| 无自动更新 | 用户手动下载新版 | 接入 Tauri updater |
| CI 流水线未实际跑通验证 | 打 tag 时可能暴露工具版本问题 | 首次正式发版 |
| 后端体积较大（Python 运行时） | App 约 95MB / dmg 约 47MB | 后续可裁剪依赖或换运行时 |
| 单实例依赖插件 | 插件被移除会双写 SQLite | 保持插件最先注册 |
