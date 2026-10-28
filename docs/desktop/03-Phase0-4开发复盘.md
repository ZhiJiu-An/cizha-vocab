# 03 — Phase 0–4 桌面化开发复盘

> **为什么需要这份文档？**
> `Tauri-PyInstaller-实战与避坑指南.md` 是规划式的「怎么做」，`ARCHITECTURE.md` 是当前代码的「是什么」。
> 这份文档记录的是**这次实际开发历程**——每个阶段到底做了什么、为什么这样决策、中间踩了哪些坑、最后迭代到了什么形态。
>
> 读者画像：
> - **未来的自己**：过了半年忘了这次怎么做的，回来查这份
> - **下一位接接手项目的 AI / 开发者**：知道代码是怎么变成现在这样的
> - **想分享给别人**：讲清楚「从 Web 到桌面」到底要做多少事

---

## Phase 0：PyInstaller 可行性验证

### 目标
确认 Python 后端能不能打成一个独立二进制（用户机器上不需要装 Python）。

### 做了什么
- `build/pyinstaller/cizha-backend.spec` — PyInstaller 打包配置
- `backend/run.py` — PyInstaller 入口脚本（解析 `--host` / `--port`，`uvicorn.run`）
- `.gitignore` — 加 `build/cizha-backend/`、`dist/` 等忽略

### 关键决策
**onefile 起步**。那时候想着"单文件最干净"，忽略了启动解压慢的问题。

### 实测
- macOS arm64 产物 **37 MB**
- 启动到就绪约 **11 秒**（PyInstaller 解压 `_MEIPASS` + FastAPI 启动）
- `GET /api/health` → `{"name":"词札单词库",...}` ✅

### 踩的坑
- `.spec` 里 SPECPATH 是 `build/pyinstaller/`，`os.path.dirname(os.path.dirname(SPECPATH))` 两次才到项目根——一次 dirname 只到 `build/`
- `rm -rf build/` 被用来清中间产物，误删了 `.spec` 所在的 `build/pyinstaller/` 目录——后来改成只清 `build/cizha-backend/` + `dist/` + `_pybuild/`

### 遗留问题
onefile 每次启动要解压——这个**当时没当问题**，Phase 1 数据持久化后才发现慢不可接受。

---

## Phase 1：数据持久化 + 前端嵌入

### 目标
桌面 App 首次启动不能因为没有数据目录而崩；前端 Vue dist 要能被 App 内部的 FastAPI 托管。

### 做了什么
- `backend/app/paths.py`（**新增**）— 统一资源路径：
  - `is_packaged()` 判断 PyInstaller 环境（`sys.frozen` 或 `_MEIPASS`）
  - `get_data_dir()` — 源码模式 = `backend/data/`；PyInstaller 首次启动把 bundle data/ 复制到用户目录（macOS `~/Library/Application Support/cizha/`、Windows `%APPDATA%/cizha/`、Linux `$XDG_DATA_HOME/cizha/`）
  - `get_env_path()` — 源码模式找 `backend/.env`；PyInstaller 首次启动复制 bundle `.env.example`
- `backend/app/database.py` — `DATA_DIR = get_data_dir()`
- `backend/app/config.py` — `CONFIG_DIR = get_data_dir()`；移除 unused import `pathlib.Path`（ruff fix）
- `backend/app/main.py` — `_resolve_frontend_dist()` 区分源码和 PyInstaller 两种模式
- `.spec` datas 加了 `frontend/dist` + `.env.example`

### 关键决策
**数据和代码分离**。代码 bundle 放在 `_MEIPASS`（只读），数据放在用户目录（可写）。PyInstaller 首次启动时做"从 bundle 复制到用户目录"的迁移，之后就只写用户目录。

### 实测
- 产物 **39 MB**（加了前端 dist + SQLite 占位 + .env.example）
- 210 单测全过 ✅
- App 首次启动 → 用户目录自动创建 → `.db` / `.env` / `llm_config.json` 自动就位

### 踩的坑
- ruff 挂 `F401 pathlib.Path unused`——config.py 改完 paths.py import 后 Path 没被用到，直接删掉 import
- `sys._MEIPASS` 是 PyInstaller 注入的运行时变量，源码模式没有——`is_packaged()` 里用 `sys.frozen` 做主判断，`_MEIPASS` 做兜底

---

## Phase 2：多平台 CI 自动构建

### 目标
打一个 tag，CI 自动产出三个平台的后端二进制，自动创建 GitHub Release 挂附件。

### 做了什么
- `.github/workflows/desktop_build.yml`（**新增**）：
  - tag `v*` 触发
  - matrix 三平台：`macos-latest` arm64 / `ubuntu-latest` amd64 / `windows-latest` amd64
  - 每条 runner：Python 3.12 + PyInstaller 6.22.3 + Node 20 → `npm ci` + `npm run build` → PyInstaller → 重命名 → `upload-artifact`
  - release job：`download-artifact` → `softprops/action-gh-release@v2` 自动创建 Release + 挂附件 + `generate_release_notes`
- `CHANGELOG.md` — Unreleased 归档 Phase 0/1 桌面化特性

### 关键决策
**先 PyInstaller 不打 Tauri**。Phase 2 只做后端二进制的三平台 CI——因为 Tauri 需要 Rust 工具链，CI 上 Windows/Linux runner 装起来更复杂。先把后端二进制产稳了，Phase 3 再叠 Tauri。

### 踩的坑（**CI 独有的、本地打包不会遇到的**）
1. **`.spec` 路径错位**：CI step 设了 `working-directory: backend`，PyInstaller 从 `backend/` 起找 `.spec` → 找不到。修复：去掉 `working-directory`，用 `cd backend` + `../build/pyinstaller/...` 显式相对路径。（对应避坑指南 **坑 19**）
2. **Windows 产物名**：`.exe` 后缀要手动加——matrix 里判断 `platform == "windows-amd64"` 时重命名
3. **Windows runner PowerShell 语法**：统一 `shell: bash`（Windows 上 runner 自带 Git Bash）

### 实测
- 第一次打 `v0.2.1` tag → CI 三平台全绿 ✅
- Release 自动创建，三个附件：darwin-arm64 (20MB) / linux-amd64 (41MB) / windows-amd64.exe (21MB)
- **Linux 包更大是正常的**——PyInstaller 在 Linux 上会嵌入更多 glibc 动态链接库

---

## Phase 3：Tauri 壳层（第一次实现）

### 目标
给 PyInstaller 二进制穿上"桌面 App 的外衣"——双击图标启动、有窗口、系统托盘、全局快捷键。

### 做了什么
- `src-tauri/` — 完整 Tauri 2 项目（Rust）：
  - `Cargo.toml` — 依赖 `tauri 2` + `tauri-plugin-shell` + `tauri-plugin-global-shortcut` + `tauri-plugin-single-instance`
  - `tauri.conf.json` — 窗口配置、托盘图标路径、`externalBin`（sidecar 路径）、图标资源
  - `main.rs` — 核心逻辑（spawn sidecar → 等待后端 ready → 显示窗口 → 托盘 → 快捷键）
  - `scripts/prepare-sidecar.py` — 把 PyInstaller 产物按 triple 重命名放 `binaries/` 或 `resources/backend/`
  - `scripts/generate-icons.py` — 画图标 + 输出全套尺寸（32/128/128@2x/icns/ico）
  - `entitlements.plist`（macOS）
- `tauri.conf.json` 里的 `hardenedRuntime: true` + `entitlements` 路径

### 关键决策
- **用 `tauri-plugin-shell` spawn sidecar**（而不是 `std::process::Command`），因为 Tauri shell plugin 会把 sidecar 纳入 App Bundle 的 `Resources/` 查找路径
- **窗口先 `visible: false`，等后端 ready 再 `show()`**——后来发现这个让用户干等黑屏很久（Phase 4 改成先 show loading 页）
- **`find_free_port(18765)` 探测空端口再传给后端**——后来发现有竞态（Phase 4 用户改成 `--port 0` + ready 文件回传）

### 工具链踩坑
- **Rust 安装**：
  - `brew install rust` 会拉 llvm 巨无霸依赖，沙箱里 180s 超时
  - `rustup --profile minimal` 更快更小（~600 MB，2-5 分钟），推荐方案
- **Tauri CLI 编译**：`cargo install tauri-cli@^2` 第一次编译 3-5 分钟，Rust 依赖很多

### 编译踩坑（**Tauri 1 → 2 API 大改**）
1. `activate_ignoring_other_apps` 是 Builder 链式方法，不能在 `setup(|app| { ... })` 里调（对应避坑指南 **坑 20**）
2. 自定义 `MenuBuilder / Submenu` 需要 `Manager<R>` 泛型约束 + `&AppHandle` 参数，无参构造不行（对应避坑指南 **坑 23**）
3. 最终**放弃自定义菜单栏**，用 Tauri 自动提供的默认菜单栏（词札 / 文件 / 编辑 / 视图 / 窗口 / 帮助）

### 实测
- `cargo tauri dev` → 窗口自动弹出 + 后端自动启动 ✅
- `cargo tauri build --bundles app` → `.app 34 MB` + `.dmg 24 MB` ✅
- `xattr -cr .app && open .app` → 双击验证通过，health JSON 正常 ✅

### 遗留问题
- 窗口启动前黑屏 ~12s（PyInstaller 解压 + FastAPI 启动）
- 启动时用户切去别的 App，窗口不会自动跳到最前
- Gatekeeper 报 "has no resources but signature indicates they must be present"（adhoc + hardenedRuntime 组合问题）
- 自定义菜单栏没做（放弃了，但 `activate_ignoring_other_apps` 这个发现值得记）

---

## Phase 4：macOS 专属优化

### 目标
让词札在 macOS 上的启动体验和原生 App 一样——**一打开就看到东西、焦点在最前、用户不需要等黑屏**。

### 做了什么
- **启动体验优化**：
  - `visible: true` — 窗口立即显示
  - setup 里先 `show()` + eval `LOADING_HTML`（蓝色渐变 + C Logo + 弹跳圆点动画）
  - 后端 ready 后再 `navigate("http://127.0.0.1:{port}/")` 切到正式前端页面
  - 去掉硬编码的 1500ms sleep——端口 listen 成功就代表后端已 ready
- **焦点置顶**：
  - Builder 上加 `.activate_ignoring_other_apps(true)`
  - macOS 底层 `NSApp.activate(ignoringOtherApps: true)`——不管用户在哪个 App，词札都会强制跳到最前
- **Gatekeeper / entitlements**：
  - 简化 entitlements.plist（去掉 `app-sandbox = false` + `network.* = true` 的混合写法，只留 Hardened Runtime 相关）
  - 简化后 Gatekeeper 的 "has no resources" 报错消失——本地 `xattr -cr` 即可绕过
- **tauri.conf.json macOS 配置**：
  - `hardenedRuntime: true`
  - `entitlements: "entitlements.plist"`
  - `dmg` 布局（`appPosition` / `applicationFolderPosition` / `windowSize`）
  - `copyright`、`shortDescription`、`longDescription`

### 关键决策
**先 show loading 页再等后端** vs **先等后端再 show 窗口**：

| 方案 | 用户体验 | 缺点 |
|---|---|---|
| 先等后端再 show | 干等黑屏 ~12s | 用户以为卡死了 |
| 先 show loading 再等 | 立刻看到蓝色画面 + 加载动画 | loading 页如果画得太简陋也像没反应 |

选了后者，因为"有东西在动"比"什么都没有"让用户更安心。

### 踩的坑
1. **entitlements 里 `app-sandbox = false` 和 `network.* = true` 冲突**——macOS entitlement 规则：plist 里出现任何 entitlement key 就被当作"参与 sandbox"处理，混合写会让系统行为不可预测（对应避坑指南 **坑 22**）
2. **`activate_ignoring_other_apps` 是 Builder 链式方法**，setup 闭包里调不了（对应避坑指南 **坑 20**）
3. **hardenedRuntime + adhoc 签名** = `Sealed Resources=none` → spctl 报错（对应避坑指南 **坑 21**）

### 实测
- `cargo tauri build` → `.app 34 MB` + `.dmg 24 MB` ✅
- `open .app` → 立刻看到蓝色 loading → 自动切到前端页面 → 焦点在最前 ✅
- health JSON 正常 ✅

---

## Phase 4 → 最终形态（用户后续迭代）

**Phase 4 之后**，main.rs 被大幅升级，AGENTS.md / ARCHITECTURE.md 也同步更新到了当前状态：

| 升级项 | Phase 4 时 | 最终形态 |
|---|---|---|
| 端口方案 | `find_free_port(18765)` 先探测再传 | `--port 0` + ready 文件回传（消除竞态） |
| 退出信号 | 没接 | `block_exit_signals()` + `spawn_signal_handler()`（sigwait 专用线程） |
| 崩溃恢复 | 没做 | `monitor_backend` 看护线程（2s 轮询，崩溃自动回启动页重启） |
| 日志 | 终端输出 | `backend.log`（5MB 轮转 + try_clone stderr） |
| 单实例 | 没装 | `tauri-plugin-single-instance`（第二次启动唤醒已有窗口） |
| 子进程信号继承 | 没清 | `pre_exec` 里 `sigemptyset` + `sigprocmask(SIG_SETMASK)` |
| ready 文件 | 没写 | `run.py` 启动后写入实际端口（`server.servers[0].sockets[0].getsockname()[1]`） |
| 启动页 | LOADING_HTML 常量 eval JS | `frontend/public/loading.html`（正式 HTML 文件 + `window.showStartupError` 契约） |
| 启动失败重试 | 没做 | `START_ATTEMPTS = 2`（失败自动重试一次） |
| Dock Reopen | 没做 | `RunEvent::Reopen` 处理（被 hide 后点 Dock 图标重新显示） |

**AGENTS.md 第 4 节「启动链路」和 ARCHITECTURE.md 第 3 节「时序图」完整描述了最终形态。**

---

## 关键决策路径（为什么是这样，而不是那样）

### onefile → onedir

```
Phase 0 起步时: "单文件最干净" → onefile 37MB
Phase 1 加数据后: 没觉得慢
Phase 4 加 Tauri 壳后: 每次启动 ~12s 黑屏 → 用户体验不可接受
用户迭代时: 改成 onedir → 冷启 ≈2s、热启 ≤0.5s
```

**教训**：PyInstaller onefile 的"解压慢"是你能容忍和不能容忍的分界线——项目越重（Tauri 壳 + 前端 dist + SQLite），onefile 越不可接受。**能 onedir 就别 onefile**。

### find_free_port → --port 0 + ready 文件

```
Phase 4: find_free_port(18765) 探测 18765 → 18766 → 传给后端 --port 18766
用户迭代: 系统分配 --port 0 → ready 文件回传实际端口 → 彻底消除竞态
```

**教训**："先探测空端口再交给后端 bind"——竞态条件：你探测到 18765 是空的，然后这之间另一个进程 bind 了 18765，后端就绑不上。**让系统分配端口 + 后端回传**是唯一无竞态方案。

### 先等后端再 show → 先 show loading 再等后端

```
初始设计: visible:false → 后端 ready → show() → 用户干等黑屏 ~12s
Phase 4: 先 show loading 页 → 后端 ready → navigate() → 用户立刻看到画面
```

**教训**："让用户看你正在工作"比"让用户等出结果"重要得多。哪怕只是一个蓝色渐变 + 三个跳跳动的小圆点，也比黑屏好。

### adhoc 签名 + 关掉 Hardened Runtime 保持简单

```
Phase 4: 开 hardenedRuntime: true + entitlements.plist
Phase 4.1: Gatekeeper 报 "no resources but signature indicates they must be present"
Phase 4.2: 简化 entitlements（去掉 sandbox 混合写法）→ spctl 还是报错
最终决策: hardenedRuntime: true 保留（签名 notarization 必需），但 adhoc 签名下
          Sealed Resources=none 是常态，用户 xattr -cr 绕过即可
```

**教训**：Hardened Runtime 是"签名 notarization 的前置条件"，但**不是"本地开发必需"**。本地开发可以关掉让一切变简单；准备发布时再开。当前项目选了"提前开"——留着以后签名时少改一项。

---

## 工具链速查（踩过的坑，按类别）

| 类别 | 坑 | 避坑指南 |
|---|---|---|
| **Rust 安装** | brew 拉 llvm 超时 180s | 用 `rustup --profile minimal`，2-5 分钟搞定，~600 MB |
| **Tauri CLI** | 第一次编译 3-5 分钟 | 正常现象，后续增量编译秒级 |
| **PyInstaller** | `SPECPATH.dirname()` 两次才到项目根 | `os.path.dirname(os.path.dirname(SPECPATH))` |
| **PyInstaller** | 误删 `.spec` 目录 | `rm -rf build/cizha-backend/` 只清中间产物 |
| **CI** | `working-directory` 导致 `.spec` 路径错位 | 不用 `working-directory`，显式 `cd` + 相对路径 |
| **Tauri 2 API** | `activate_ignoring_other_apps` 是 Builder 方法不是运行时 | 放 `.setup()` 之前 |
| **Tauri 2 API** | 自定义 MenuBuilder 需要 `AppHandle` 参数 | 直接用默认菜单栏 |
| **macOS Gatekeeper** | "has no resources" 报错 | adhoc + hardenedRuntime = Sealed Resources=none，正常 |
| **entitlements** | `app-sandbox=false` + `network=true` 混合写 | 要么全关要么全开，不要混合 |
| **Hardened Runtime** | 本地开发可以关掉让一切变简单 | 准备签名时再开 |

---

## 最终架构（一句话）

```
词札.app (macOS Bundle)
├── Tauri 2（Rust 壳）
│   ├── 启动: block_exit_signals → single-instance → global-shortcut → setup
│   │   ├─ 200ms 延迟 show loading 页（避免白闪）
│   │   ├─ 后台: start_backend(--port 0 --ready-file) → wait_for_backend(读文件 + /api/health)
│   │   ├─ 成功 → navigate → monitor_backend（2s 看护）
│   │   └─ 失败 → retry 1 次 → showStartupError
│   ├── 托盘（右键打开/隐藏/退出，左键切换）
│   ├── 全局快捷键 Cmd+Shift+C
│   ├── 信号接管（sigwait 专用线程处理 SIGTERM/SIGINT/SIGHUP）
│   └── 退出统一入口（mark_stopping → cleanup_backend → SIGTERM 3s → SIGKILL）
├── WebView（WKWebView，系统自带）
│   ├── loading.html（启动页，前端/public/）
│   └── Vue 3（后端托管的 dist/）
└── PyInstaller onedir sidecar
    └── cizha-backend --host 127.0.0.1 --port 0 --ready-file <path>
        ├── FastAPI + SQLAlchemy + SQLite + uvicorn
        ├── stdout/stderr → ~/Library/Logs/.../backend.log
        └── 启动成功写 ready 文件 → /api/health 返回 JSON
```

**数据**：`~/Library/Application Support/cizha/`（源码模式 = `backend/data/`）
**日志**：`~/Library/Logs/com.cizha.vocab/backend.log`
**安装包**：`.app 34 MB` / `.dmg 24 MB`
