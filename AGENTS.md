# AGENTS.md — 词札（cizha）AI 协作手册

> **这是 AI 进入本仓库的唯一入口。**
> 动手改代码前，按顺序读：本文件 → [ARCHITECTURE.md](ARCHITECTURE.md)（怎么做、边界在哪）→ [PRD.md](PRD.md)（做什么、验收标准是什么）。
>
> 本文件只写「事实 + 约束 + 禁止事项」，不写愿景。与代码冲突时，以代码为准，并回头修正本文件。

---

## 1. 项目一句话

词札是一款**本地优先**的术语 / 单词记录桌面应用：Tauri 2（Rust 壳）+ Vue 3（Web 前端）+ FastAPI + SQLite（Python 后端，PyInstaller 打包成 onedir sidecar 随 App 分发）。

核心链路：`查词 → 双源对照 → 收藏 → 间隔复习 → 统计`。

---

## 2. 目录与职责

```text
cizha/
├── backend/                    # FastAPI 后端
│   ├── app/
│   │   ├── main.py             # 入口：CORS、幂等迁移、路由注册、SPA 兜底、APP_VERSION
│   │   ├── paths.py            # 源码 / PyInstaller 两种模式的路径解析（数据、.env、版本兜底）
│   │   ├── database.py         # SQLAlchemy engine / Session / Base
│   │   ├── models.py           # Word / ReviewLog
│   │   ├── schemas.py          # Pydantic 模型
│   │   ├── config.py           # 运行时模型配置（llm_config.json）
│   │   └── routes/             # words(+tags) / dictionary / translate / review / stats / ocr / llm_config
│   ├── tests/                  # unittest，210 个用例，内存 SQLite 隔离
│   ├── run.py                  # uvicorn 启动入口；桌面模式支持 --ready-file
│   └── data/                   # 运行时数据（gitignore）
├── frontend/                   # Vue 3 + Vite
│   ├── public/loading.html     # 桌面启动页（窗口初始 URL），暴露 window.showStartupError
│   └── src/
│       ├── router/index.js     # 页面路由 + 404 重定向
│       ├── api/index.js        # axios 封装，baseURL = /api
│       ├── views/              # Search / WordList / WordForm / WordDetail / TagList / Review / Stats / Settings / ModelSettings
│       └── components/         # Phonetics / WordBadge / WordQuickView
├── src-tauri/                  # Tauri 桌面壳（Rust）
│   ├── src/main.rs             # 全部生命周期逻辑：启动、看护、退出、日志、托盘、快捷键、单实例
│   ├── tauri.conf.json         # 窗口 / 托盘 / 打包 / 资源映射 / macOS 配置
│   ├── build.rs                # release 构建校验后端资源与 manifest
│   ├── capabilities/default.json
│   └── resources/backend/      # prepare-sidecar.py 复制进来的后端产物（gitignore）
├── build/pyinstaller/
│   └── cizha-backend.spec      # onedir 打包配置（EXE exclude_binaries + COLLECT）
├── scripts/prepare-sidecar.py  # 复制后端产物 + 生成 backend-manifest.json
├── .github/workflows/
│   ├── ci.yml                  # ruff + 后端全量测试
│   └── desktop_build.yml       # 打 tag → 各平台后端包 + macOS .app/.dmg → Release
├── PRD.md / ARCHITECTURE.md / CHANGELOG.md / README.md
└── setup.sh / start.sh / setup.bat / start.bat
```

---

## 3. 常用命令

> `cargo` 不在默认 PATH，用 `~/.cargo/bin/cargo`；`npm` 可用。

### 3.1 源码开发（浏览器）

```bash
# 后端（终端 1）
cd backend
./venv/bin/python run.py --reload --port 8000
# 等价于 uvicorn app.main:app --reload --port 8000 --reload-exclude "data/*"

# 前端（终端 2）
cd frontend
npm run dev          # http://localhost:5173，/api 已代理到 127.0.0.1:8000
```

### 3.2 单端口（后端托管前端）

```bash
cd frontend && npm run build     # 产出 frontend/dist
cd ../backend && ./venv/bin/python run.py --port 8000
# 打开 http://127.0.0.1:8000
```

### 3.3 后端质量门禁

```bash
cd backend
./venv/bin/python -m unittest discover -s tests -t . -v
ruff check app tests
```

### 3.4 桌面开发 / 打包

```bash
# 桌面开发（项目根目录没有 package.json，tauri CLI 走 cargo）
cd src-tauri && ~/.cargo/bin/cargo tauri dev

# 完整打包（顺序不可颠倒）
cd frontend && npm run build && cd ..
cd backend && ./venv/bin/python -m PyInstaller ../build/pyinstaller/cizha-backend.spec \
    --noconfirm --workpath ../_pybuild --distpath ../dist --clean && cd ..
python3 scripts/prepare-sidecar.py          # 必须！否则 build.rs 在 release 下 panic
cd src-tauri && ~/.cargo/bin/cargo tauri build --bundles app
# 需要 dmg 时：cargo tauri build --bundles app,dmg
```

### 3.5 快速验证桌面行为

```bash
# 单实例：应只有一个壳层进程 + 一个后端进程
open -a "/Applications/词札.app"
open -a "/Applications/词札.app"
pgrep -fl cizha-backend | wc -l

# SIGTERM 优雅退出：后端应打印关机日志且无残留
kill -TERM <壳层 PID>; sleep 4; pgrep -fl cizha-backend

# 崩溃恢复：强杀后端后 2 秒内应回到启动页并重启到新端口
kill -9 <后端 PID>

# 日志
tail -f ~/Library/Logs/com.cizha.vocab/backend.log
```

---

## 4. 启动链路（7 步，顺序与语义是契约）

代码位置：[main.rs](file:///Users/azj/Documents/Project/Python_Project/cizha/src-tauri/src/main.rs)

1. `main()` 第一行 `#[cfg(unix)] block_exit_signals()` —— 在**任何线程创建之前**屏蔽 SIGTERM/SIGINT/SIGHUP。
2. Tauri Builder **最先生册** `tauri-plugin-single-instance`：第二次启动把参数交给已有实例并唤醒窗口，然后自杀。
3. 窗口在配置中 `visible:false`，初始 URL = `loading.html`；`setup` 里 200ms 后 `show()` + `set_focus()`（避免首帧白底）。
4. 后台线程调用 `start_backend`：`--host 127.0.0.1 --port 0 --ready-file <每次唯一路径>`，spawn 后把 `Child` 存进 `AppState.backend`。
5. `wait_for_backend`：轮询读取 ready 文件拿到实际端口 → `GET /api/health` 返回 `HTTP/1.1 200` 即视为就绪；最长 30s，整体最多 2 次尝试。
6. `navigate` 到 `http://127.0.0.1:{port}/`；导航失败必须把错误写回启动页（`window.showStartupError`），不得静默。
7. 启动成功后 `monitor_backend`：每 2s 检查子进程；崩溃则导航回启动页 → 重启 → 导航到新端口；重启失败显示错误并等待 20s 再试。

**退出路径**（三处，行为必须一致）：RunEvent::Exit / 托盘「退出」/ Unix 信号线程 —— 先 `mark_stopping`，再 `cleanup_backend`，最后退出。

---

## 5. 红线约束（违反会导致隐蔽故障，禁止「优化」）

### 5.1 端口与进程

- **禁止**硬编码端口、禁止「先探测空闲端口再交给后端 bind」。唯一方案：`--port 0` + ready 文件回传。
- 后端**只能**监听 `127.0.0.1`，不得改 `0.0.0.0`。
- **禁止**用 `Stdio::piped()` 接后端 stdout/stderr：缓冲区写满会把后端卡死。输出必须落到日志文件。
- **禁止**在后端已被 `try_wait` 回收后再 `kill`（PID 可能被复用）。`terminate_child` 的第一行判断不可删除。
- Unix 下子进程会继承父进程信号屏蔽字：spawn 时**必须**在 `pre_exec` 里 `sigemptyset` + `sigprocmask(SIG_SETMASK)`，否则后端收不到 SIGTERM、只能等 3 秒被 SIGKILL。

### 5.2 生命周期

- 关闭窗口 = 隐藏到托盘（`api.prevent_close()`），不是退出。
- 任何新增退出入口都必须调用 `mark_stopping` + `cleanup_backend`；否则看护线程会把后端重新拉起来。
- 单实例插件必须最先注册。删掉它会同时出现两个托盘图标和两个后端争抢同一个 SQLite。

### 5.3 版本号（三处必须同步）

| 位置 | 字段 |
|---|---|
| [tauri.conf.json](file:///Users/azj/Documents/Project/Python_Project/cizha/src-tauri/tauri.conf.json) | `"version"` |
| [frontend/package.json](file:///Users/azj/Documents/Project/Python_Project/cizha/frontend/package.json) | `"version"` |
| [backend/app/main.py](file:///Users/azj/Documents/Project/Python_Project/cizha/backend/app/main.py) | `APP_VERSION` |

`backend/app/paths.py` 里有一个同值兜底常量，`frontend/package-lock.json` 也要跟着 `npm version <v> --no-git-tag-version` 更新。发布前用 `/api/health` 实际确认返回的版本。

### 5.4 打包

- 后端**必须** onedir，禁止 onefile（onefile 每次启动解压，实测 6 秒才就绪）。
- 改完后端代码后**必须**重跑 `python3 scripts/prepare-sidecar.py`，否则 App 里仍是旧后端；`build.rs` 在 release 下会直接 panic 阻断。
- `src-tauri/resources/backend/` 与 `backend-manifest.json` 是生成物，**禁止提交**。
- 未配置签名身份时走 ad-hoc 签名；**签名与公证当前明确暂缓**，不要擅自加 `signingIdentity` 或公证步骤。

### 5.5 前后端接口

- 所有业务接口必须以 `/api` 开头。`main.py` 的 `is_api_path()` 决定是否回落 `index.html`；不在 `/api` 下的新接口会被 SPA 兜底吞掉。
- 错误统一用 `{"detail": "..."}`（FastAPI 默认），前端 `api/index.js` 的拦截器依赖它。
- 前端路由使用 `createWebHistory()`，新增页面无需改后端；未知路径由 `/:pathMatch(.*)*` 重定向到 `/`。
- `loading.html` 暴露的 `window.showStartupError(message)` 是 Rust 侧唯一可依赖的启动页契约，改名必须同时改 Rust。

### 5.6 数据与密钥

- 禁止提交 `backend/data/`、`.env`、`llm_config.json`（内含明文 API Key）。
- 源码模式数据在 `backend/data/`；打包模式在 `~/Library/Application Support/cizha/`。不要写死其中一种。

---

## 6. 常见坑

| 现象 | 真实原因 | 处理 |
|---|---|---|
| `open -a` 后看到的还是旧端口 / 旧行为 | LaunchServices 复用了旧实例，单实例插件直接把新进程退了 | 先 `pkill -f cizha-backend` 并 `kill` 旧壳层，再启动 |
| App 启动一直转圈 | 后端没起来 / dist 没打进包 / ready 文件没写 | 看 `~/Library/Logs/com.cizha.vocab/backend.log` |
| 打包成功但功能是旧的 | 只重打了后端，没跑 `prepare-sidecar.py` | 重跑脚本；release 构建时 `build.rs` 会拦 |
| `cargo tauri build --bundles dmg` 报 `bundle_dmg.sh` 权限错误 | 工具沙箱禁止写 `/Volumes` | 先只打 `app`，再用 `ditto` + `hdiutil` 手工生成 dmg |
| 后端日志没有「优雅关闭」 | 子进程继承了 SIGTERM 屏蔽字 | 检查 `pre_exec` 的 `sigprocmask` 是否还在 |
| 前端页面整片空白 | 访问了未知路由且兜底路由被删 | 恢复 `/:pathMatch(.*)*` → `/` |
| 直接执行 `dist/cizha-backend/cizha-backend` 报 `not a directory` | `dist/` 路径下的已知现象 | 用 `resources/backend` 副本验证，不影响 App 运行 |

---

## 7. 改动后必须验证（Definition of Done）

- [ ] `ruff check app tests` 通过
- [ ] 后端全量测试通过（当前 210 项）
- [ ] `cd frontend && npm run build` 通过
- [ ] 涉及桌面壳：单实例 / SIGTERM / 崩溃恢复 / 日志 / 无残留进程 五项实测
- [ ] 涉及版本：三处版本号一致，`/api/health` 返回正确版本
- [ ] 涉及打包：先 `prepare-sidecar.py`，再 release 构建通过
- [ ] 涉及用户可见行为：同步更新 `CHANGELOG.md` 的 Unreleased 段
- [ ] 涉及架构/契约：同步更新本文件与 `ARCHITECTURE.md`，否则视为文档失效

---

## 8. 文档地图

| 文件 | 作用 | 谁该读 |
|---|---|---|
| `AGENTS.md`（本文件） | AI 入口：事实、约束、禁止事项 | 所有 AI / 新贡献者 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 三层架构与四组契约，变更的底线 | 改跨层代码前必读 |
| [PRD.md](PRD.md) | 做什么、验收标准 | 判断「该不该做 / 做完算不算完成」 |
| [CHANGELOG.md](CHANGELOG.md) | 版本变更记录 | 发布与回溯 |
| [README.md](README.md) | 面向用户的安装与使用 | 写用户文档时 |
| `docs/desktop/` | 桌面化方案与安装指南 | 打包 / 发布相关 |

---

## 9. 提交与协作

- 分支：`feat/xxx`、`fix/xxx`
- 提交前缀：`feat:` / `fix:` / `docs:` / `style:` / `refactor:` / `chore:`
- 一次提交只做一件事；跨层改动（Rust + 前端 + 后端）必须在说明里写清三边如何对齐。
