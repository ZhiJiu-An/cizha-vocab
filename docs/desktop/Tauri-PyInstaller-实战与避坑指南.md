# Tauri + PyInstaller 桌面应用实战与避坑指南

> 个人学习笔记 · 以「词札（cizha）」项目为样本
> 目标：把一次「Web 项目 → Mac 桌面 App」的完整实践，整理成你以后能独立复用的操作手册。
> 阅读方式：第 1 章建立心智模型，第 2 章跟着做，第 3 章当排错字典，第 4 章规划下一步。

---

## 一、项目全景概述

### 1.1 为什么选 Tauri + PyInstaller

先回答一个更根本的问题：**为什么不是 Electron，为什么不是把 Python 重写成 Rust？**

| 方案 | 体积 | 现有代码复用 | 系统能力 | 结论 |
|---|---|---|---|---|
| Electron + Python sidecar | 150MB+ | 前端 100% | 强 | 能用，但太重 |
| **Tauri + PyInstaller sidecar** | **40~100MB** | **前端 100%、后端 100%** | **强** | **本项目选择** |
| 纯 Tauri，Rust 重写后端 | 10MB | 0% | 强 | 重写 210 个测试的成本不划算 |
| pywebview | 40~80MB | 100% | 弱（托盘/快捷键要自己拼） | 应急可用，长期不足 |

三个关键理由：

1. **复用系统 WebView**：macOS 用 WKWebView、Windows 用 WebView2。Tauri 不自带浏览器内核，所以安装包比 Electron 小一个数量级。
2. **前端零改动**：Vue 3 打包出的 `dist/` 原样塞进 App，Tauri 只负责开一个窗口去加载它。
3. **Python 后端不用重写**：FastAPI 里已经有业务规则、复习算法、数据库迁移和测试。把这些重写成 Rust，风险和收益完全不成比例。

> **Sidecar 是什么？**
> 一句话：**跟在主程序身边、由主程序负责启动和关闭的「副驾驶」进程**。
> 在这里，Tauri（Rust）是主程序，PyInstaller 打出来的 `cizha-backend` 是 sidecar。

### 1.2 每个角色到底在干什么

用一家餐厅来类比：

| 角色 | 餐厅里的身份 | 在项目里具体负责 |
|---|---|---|
| **Tauri 壳层（Rust）** | 店长 + 门锁 + 水电工 | 开窗关窗、托盘图标、全局快捷键、启动/看护/杀死后端、接管退出信号、写日志 |
| **WebView + Vue** | 店面 / 菜单 / 点餐界面 | 所有用户能看到和点击的东西，通过 HTTP 找后厨要数据 |
| **FastAPI（Python）** | 后厨 | 查词、收藏、复习、统计、访问词典和大模型 |
| **SQLite** | 仓库 | 存词条、复习排期、复习日志 |
| **PyInstaller** | 把后厨连锅带灶装进集装箱 | 把 Python 解释器 + 依赖 + 代码打成一个可执行目录 |
| **ready 文件** | 后厨的对讲机：「3 号桌，出餐了」 | 后端启动成功后把实际端口写给店长 |
| **`/api/health`** | 试菜员 | 店长确认后厨真的能出餐，而不只是灯亮了 |

一个容易混淆的点：**这里的「前端 / 后端」不是指 Web 开发里的浏览器和服务器**。桌面 App 里，两者都在你电脑上：

- 前端跑在 App 内嵌的 WebView 里；
- 后端跑在本机 `127.0.0.1` 的某个随机端口上；
- 两者之间是**本机 HTTP**，不经过互联网。

### 1.3 整体架构怎么运转

```text
双击 词札.app
   │
   ▼
Rust 店长上班（main）
   ├─ 先屏蔽退出信号（防止后厨变孤儿）
   ├─ 检查是不是已经有一家店在营业（单实例）
   ├─ 开出店面，先挂「加载中」的牌子（loading.html）
   └─ 打电话叫后厨上班（spawn cizha-backend --port 0 --ready-file X）
          │
          ▼
      后厨开门，系统随便分配一个桌号（端口）
      后厨用对讲机报桌号（写 ready 文件）
          │
          ▼
      店长派人试菜（GET /api/health 返回 200）
          │
          ▼
      店长把「加载中」换成正式菜单（navigate 到 http://127.0.0.1:<port>/）
          │
          ▼
      店长每 2 秒巡一次场；后厨倒下就重新叫一遍（崩溃自恢复）
          │
          ▼
      客人说「打烊」（Cmd+Q / 托盘退出 / kill）
          → 店长先请后厨收尾（SIGTERM）
          → 3 秒还不走就强制清场（SIGKILL）
          → 店长关灯走人
```

**三层依赖方向是单向的**：

```text
Rust 壳层  ──(加载 URL)──▶  Vue 前端  ──(HTTP /api)──▶  Python 后端
     ▲                                                      │
     └──────────────(进程管理，不碰业务)──────────────────────┘
```

记住三条边界，后面所有坑都能归结到「有人越界了」：

1. **Rust 不管业务**：它不知道什么是单词、复习档位、标签。
2. **前端不管进程**：它不知道后端在哪、怎么启动，只知道请求 `/api`。
3. **后端不管窗口**：它不知道有没有托盘，只负责监听端口和响应 HTTP。

### 1.4 三个「环境」要分清

这是初学者最容易混的地方：

| 环境 | 谁在跑 | 前端从哪来 | 后端从哪来 |
|---|---|---|---|
| **开发环境** | Vite 5173 + uvicorn 8000 | Vite 开发服务器（带热更新） | 源码 `backend/app` |
| **单端口预览** | 只有 uvicorn | FastAPI 托管 `frontend/dist` | 源码 `backend/app` |
| **桌面 App** | Tauri + sidecar | App 内后端托管打包进去的 dist | `Contents/Resources/backend/` |

> 你在开发环境改了代码，不等于 App 里生效。**桌面包里的东西是「快照」**，必须重新打包才会更新。这一条会引出后面最阴险的坑之一。

---

## 二、核心实现步骤（手把手）

> 下面每个阶段都给出：**目标 → 做什么 → 关键代码 → 怎么验证成功**。
> 建议严格按顺序做，每一步验证通过再进下一步。

### 阶段 0：技术选型与环境确认

**目标**：确认这台机器具备构建条件，避免做到一半卡在环境上。

**需要三套工具链**：

```bash
# 1. Python（后端 + PyInstaller）
python3 --version        # 建议 3.10 ~ 3.12

# 2. Node（前端构建）
node --version           # 建议 20+
npm --version

# 3. Rust（Tauri 壳层）
~/.cargo/bin/cargo --version
~/.cargo/bin/rustc --version

# 4. Tauri CLI（两种安装方式二选一）
~/.cargo/bin/cargo tauri --version
# 或 npm install -g @tauri-apps/cli@^2
```

**验证成功标志**：四条命令都能输出版本号。

**两个容易忽略的点**：

- `cargo` 通常不在默认 PATH 里，写脚本时用 `~/.cargo/bin/cargo` 更稳。
- Rust 第一次编译 Tauri 会编译几百个 crate，**5~15 分钟属正常**，不要以为卡死了。

---

### 阶段 1：先让 Web 项目「单端口」跑起来

**目标**：在引入任何桌面技术之前，先证明「一个后端进程就能提供完整页面」。这是后面所有工作的地基。

**做什么**：

1. 构建前端到 `frontend/dist`。
2. 让 FastAPI 托管 dist，并处理 SPA 路由兜底。

```bash
cd frontend
npm run build          # 产物：frontend/dist/index.html + assets/
```

后端关键逻辑（简化版，实际见 `backend/app/main.py`）：

```python
# 1) 静态资源：/assets/* 直接读 dist/assets
app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

# 2) SPA 兜底：非 /api 的路径，文件存在就返回文件，否则返回 index.html
@app.get("/{full_path:path}")
def serve_spa(full_path: str):
    # 关键：/api/* 未匹配必须返回 JSON 404，绝不能回落 index.html
    # 否则前端会拿到一坨 HTML，报「Unexpected token < in JSON」
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="接口不存在")

    target = (dist / full_path).resolve()
    if target.is_file() and target.is_relative_to(dist):   # 防目录逃逸
        return FileResponse(target)

    index = dist / "index.html"
    if index.is_file():
        return FileResponse(index)      # 适配 vue-router history 模式

    raise HTTPException(status_code=404, detail="前端未构建")
```

**怎么验证**：

```bash
cd backend
./venv/bin/python run.py --port 8000

# 终端 1：首页应返回 index.html
curl -s http://127.0.0.1:8000/ | head -5

# 终端 2：健康检查应返回 JSON 和版本号
curl -s http://127.0.0.1:8000/api/health

# 终端 3：不存在的接口必须是 JSON 404，不能是 HTML
curl -s http://127.0.0.1:8000/api/not-exist
# 期望：{"detail":"接口不存在"}
```

**成功标志**：浏览器打开 `http://127.0.0.1:8000` 能正常点进任意页面，刷新子路由不 404。

---

### 阶段 2：用 PyInstaller 把后端打成「可移动后厨」

**目标**：把 Python 解释器、依赖、代码、前端 dist 打成一个不依赖本机 Python 的目录。

**先做两个决定**：

| 决定 | 选择 | 原因 |
|---|---|---|
| onefile 还是 onedir | **onedir** | onefile 每次启动要解压几十 MB，实测 6 秒才就绪；onedir 冷启约 2 秒、热启 0.5 秒内 |
| 数据放哪 | **用户目录** | App 包内是只读的，SQLite 不能写进去 |

**`build/pyinstaller/cizha-backend.spec` 核心片段（带注释）**：

```python
# SPECPATH = build/pyinstaller/，往上两级是项目根
project_root = os.path.dirname(os.path.dirname(SPECPATH))
backend_root = os.path.join(project_root, "backend")

# 要一起带进包里的「资源」：数据库占位、前端 dist、.env 模板
def _data_dirs():
    return [
        (os.path.join(backend_root, "data"), "data"),
        (os.path.join(project_root, "frontend", "dist"), "frontend/dist"),
        (os.path.join(backend_root, ".env.example"), "."),
    ]

a = Analysis(
    [os.path.join(backend_root, "run.py")],   # 入口脚本
    pathex=[backend_root],                    # 让 import app.* 能找到
    datas=_data_dirs(),
    collect_all=["app"],                      # 关键：把 app 包整个收进来
)

# exclude_binaries=True 表示「可执行文件里不塞依赖」
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="cizha-backend", console=True)

# COLLECT 把 exe + 依赖一起收进一个目录 → onedir 产物
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name="cizha-backend")
```

> **`collect_all=["app"]` 是个大坑点**：如果你的代码里有「字符串动态 import」，PyInstaller 静态分析不到，运行时就会 `ModuleNotFoundError`。显式收集整个包最稳。

**运行时路径要区分「源码」和「打包」两种模式**：

```python
def is_packaged() -> bool:
    # PyInstaller 运行时会注入 sys.frozen / sys._MEIPASS
    return getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS")

def get_data_dir() -> Path:
    if not is_packaged():
        return Path(__file__).parent.parent / "data"        # 源码：backend/data
    user_dir = Path.home() / "Library" / "Application Support" / "cizha"  # 打包：用户目录
    # 首次启动把包里自带的 data 复制过去（只复制不存在的文件）
    ...
    return user_dir
```

**打包命令**：

```bash
cd backend
./venv/bin/python -m PyInstaller ../build/pyinstaller/cizha-backend.spec \
    --noconfirm \
    --workpath ../_pybuild \
    --distpath ../dist \
    --clean
```

**怎么验证**：

```bash
# 1) 产物结构应是「可执行文件 + _internal 目录」
ls dist/cizha-backend/

# 2) 直接运行，必须能起服务
./dist/cizha-backend/cizha-backend --host 127.0.0.1 --port 8123 &
curl -s http://127.0.0.1:8123/api/health

# 3) 验证数据落在用户目录，而不是 App 包内
ls ~/Library/Application\ Support/cizha/

# 4) 关掉它
kill %1
```

**成功标志**：第 2 步返回 JSON；第 3 步能看到 `cizha.db`。

---

### 阶段 3：最小可用的 Tauri 壳层

**目标**：先做到「双击能开窗、能看到前端页面」，暂时不追求优雅退出和崩溃恢复。

**`src-tauri/tauri.conf.json` 关键配置（注释仅为讲解，JSON 实际不支持注释）**：

```jsonc
{
  "productName": "词札",
  "identifier": "com.cizha.vocab",          // 决定日志目录、App 身份，发布后不要改
  "build": {
    "frontendDist": "../frontend/dist"      // Tauri 要知道前端产物在哪
  },
  "app": {
    "windows": [{
      "label": "main",
      "url": "loading.html",                // 先加载启动页，而不是直接加载首页
      "visible": false,                     // 先隐藏，避免 WebView 首帧白底闪一下
      "width": 1280, "height": 800,
      "minWidth": 960, "minHeight": 640
    }],
    "trayIcon": {
      "iconPath": "icons/icon.png",
      "iconAsTemplate": true                // macOS 菜单栏图标随亮暗主题自动变色
    }
  },
  "bundle": {
    "targets": ["app", "dmg"],
    "resources": {
      "resources/backend": "backend"        // 左边是仓库路径，右边是 App 内路径
    },
    "macOS": {
      "minimumSystemVersion": "12.0"
    }
  }
}
```

**Rust 侧最小启动逻辑（`src-tauri/src/main.rs` 简化）**：

```rust
.setup(|app| {
    let window = app.get_webview_window("main").unwrap();

    // 先让启动页画出来，再显示窗口，避免白屏
    let w = window.clone();
    thread::spawn(move || {
        thread::sleep(Duration::from_millis(200));
        let _ = w.show();
        let _ = w.set_focus();
    });

    // 后台启动后端，成功后把页面导航过去
    let app_handle = app.handle().clone();
    let win = window.clone();
    thread::spawn(move || {
        match start_backend(&app_handle) {
            Ok(port) => {
                let url = Url::parse(&format!("http://127.0.0.1:{port}/")).unwrap();
                let _ = app_handle.run_on_main_thread(move || { let _ = win.navigate(url); });
            }
            Err(e) => show_error_on_main(&app_handle, &window, &e),
        }
    });

    Ok(())
})
```

**怎么验证**：

```bash
cd src-tauri
~/.cargo/bin/cargo tauri dev
```

**成功标志**：

1. 窗口先显示「加载中」，1~2 秒后变成正式页面；
2. 页面上能正常查词、翻页；
3. `pgrep -fl cizha-backend` 能看到一个后端进程。

> 注意：`tauri dev` 会启动一个带调试能力的壳层，但**不会**走完整的资源打包流程。它能跑不代表 dmg 能跑，阶段 5 必须单独验证。

---

### 阶段 4：生命周期加固（真正决定「像不像桌面软件」）

这一阶段是本次实践的核心。**最小可用只花 1 天，做扎实要多花 3 倍时间**，但只有做完这些，它才不是「套壳网页」。

#### 4.1 端口不要自己猜：`--port 0` + ready 文件

**错误做法**（很多人第一版会这么写）：

```text
先扫描找到 18765 空闲 → 把 18765 传给后端 → 后端 bind 时发现被占了 → 启动失败
```

这叫**竞态**：你检查的瞬间它是空的，不代表你用的瞬间它还是空的。

**正确做法**：把「选端口」和「用端口」合成一个原子动作，交给操作系统。

```python
# backend/run.py：uvicorn 真正开始监听后，把实际端口写给壳层
def _write_ready_port(server, ready_file: str) -> None:
    while not server.started:          # 等到监听成功
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]   # 系统分配的真实端口
    Path(ready_file).write_text(str(port), encoding="utf-8")

server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0))
threading.Thread(target=_write_ready_port, args=(server, ready_file), daemon=True).start()
server.run()
```

```rust
// 壳层：每次启动用唯一 ready 文件，先删残留，再等它出现
cmd.args(["--host", "127.0.0.1", "--port", "0"])
   .arg("--ready-file").arg(&ready_file);
```

**验证**：

```bash
# 连续启动多次，端口应该不同，且都能访问
for i in 1 2 3; do
  TMP=$(mktemp -u /tmp/cizha-XXXX.port)
  ./dist/cizha-backend/cizha-backend --port 0 --ready-file "$TMP" &
  sleep 2
  PORT=$(cat "$TMP")
  curl -s "http://127.0.0.1:$PORT/api/health"
  kill %1
done
```

#### 4.2 就绪判定不能只看「进程活着」

进程活着 ≠ HTTP 可用。正确的判定是两层：

```rust
// 1) 从 ready 文件读端口
let port = std::fs::read_to_string(&ready_file)?.trim().parse()?;

// 2) 真的发一次 GET /api/health，看到 "HTTP/1.1 200" 才算就绪
let request = format!("GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n");
```

并且要设**总超时**和**重试次数**，否则用户会无限转圈：

```rust
const READY_TIMEOUT: Duration = Duration::from_secs(30);
const START_ATTEMPTS: u8 = 2;
```

#### 4.3 退出必须清理后端（否则变孤儿进程）

> **孤儿进程是什么？**
> 一句话：**启动它的程序已经退出了，它还在后台继续跑**。表现是「App 关了，但端口还被占着、CPU 还在烧」。

只挂 `RunEvent::Exit` 不够，因为 `kill -TERM`、系统注销不走它。所以要**直接接管 Unix 信号**：

```rust
fn main() {
    // 关键顺序：必须在创建任何线程之前屏蔽
    #[cfg(unix)]
    block_exit_signals();

    // ...
}

#[cfg(unix)]
fn block_exit_signals() {
    unsafe {
        let mut set = std::mem::zeroed();
        libc::sigemptyset(&mut set);
        libc::sigaddset(&mut set, libc::SIGTERM);
        libc::sigaddset(&mut set, libc::SIGINT);
        libc::sigaddset(&mut set, libc::SIGHUP);
        // 之后创建的所有线程都会继承这个屏蔽字
        libc::pthread_sigmask(libc::SIG_BLOCK, &set, std::ptr::null_mut());
    }
}

#[cfg(unix)]
fn spawn_signal_handler(app: AppHandle) {
    thread::spawn(move || {
        // 用 sigwait「等」信号，而不是注册回调函数：
        // 因为回调里不能安全地拿锁、也不能随便调 Tauri API
        let mut sig = 0;
        unsafe { libc::sigwait(&set, &mut sig) };
        mark_stopping(&app);      // 先告诉看护线程「别再拉后端了」
        cleanup_backend(&app);    // 再杀后端
        app.exit(0);
    });
}
```

**优雅终止顺序**（这段是很多教程不会讲的细节）：

```rust
fn terminate_child(child: &mut Child) {
    // 1) 已经被 wait 回收过 → 绝不能再次 kill：PID 可能已被系统复用给别的进程
    if matches!(child.try_wait(), Ok(Some(_))) {
        return;
    }

    // 2) 先 SIGTERM，让 uvicorn / SQLite 正常收尾
    unsafe { libc::kill(child.id() as i32, libc::SIGTERM) };

    // 3) 最多等 3 秒
    let deadline = Instant::now() + Duration::from_secs(3);
    loop {
        match child.try_wait() {
            Ok(Some(_)) => return,       // 正常退出
            Ok(None) => {}
            Err(_) => break,
        }
        if Instant::now() >= deadline { break; }
        thread::sleep(Duration::from_millis(50));
    }

    // 4) 还不走就 SIGKILL
    let _ = child.kill();
    let _ = child.wait();
}
```

**验证**（四种退出方式都要试）：

```bash
# 1. 托盘退出
# 2. Cmd+Q
# 3. kill -TERM 壳层 PID
kill -TERM <壳层PID>; sleep 4; pgrep -fl cizha-backend   # 应该没有输出

# 4. 关闭窗口：应该只是隐藏，进程仍在（这是预期行为）
```

#### 4.4 日志必须有地方去

**不要**这样接后端输出：

```rust
// 错误示例：pipe 不读，缓冲区写满后后端会阻塞
cmd.stdout(Stdio::piped());
// 错误示例：直接丢弃，出问题永远查不到原因
cmd.stdout(Stdio::null());
```

正确做法是重定向到文件：

```rust
match open_backend_log(app) {
    Some(mut log) => {
        writeln!(log, "\n===== 启动后端 =====");       // 每次启动留分隔行
        let err_log = log.try_clone().unwrap();          // stderr 复用同一文件
        cmd.stdout(Stdio::from(log));
        cmd.stderr(Stdio::from(err_log));
    }
    None => { cmd.stdout(Stdio::null()); cmd.stderr(Stdio::null()); }
}
```

日志路径用 Tauri 提供的标准目录：

```rust
// macOS 实际为 ~/Library/Logs/com.cizha.vocab/backend.log
let dir = app.path().app_log_dir()?;
```

再加一个简单的轮转，避免日志无限增长：

```rust
if metadata.len() > 5 * 1024 * 1024 {
    std::fs::rename(&path, path.with_extension("log.1"))?;   // 只保留一份旧日志
}
```

**验证**：

```bash
tail -f ~/Library/Logs/com.cizha.vocab/backend.log
# 应能看到 uvicorn 启动日志；优雅退出时应有 "Shutting down" / "Application shutdown complete"
```

#### 4.5 单实例：防止「两个店长 + 两个后厨」

没有单实例保护时，用户双击两次就会出现：

- 两个托盘图标；
- 两个后端进程同时读写同一个 SQLite（可能锁库、数据错乱）；
- 两个窗口，用户不知道哪个是真的。

Tauri 官方插件解决：

```rust
tauri::Builder::default()
    // 必须放在最前面：第二次启动时，新进程把参数转给旧实例然后自己退出
    .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
        toggle_window(app, true);       // 旧实例把窗口叫到前台
    }))
```

**验证**：

```bash
open -a "/Applications/词札.app"
open -a "/Applications/词札.app"

pgrep -fl "词札" | wc -l          # 只应有 1 个壳层
pgrep -fl cizha-backend | wc -l   # 只应有 1 个后端
```

#### 4.6 看护：后端崩了要能自己爬起来

```rust
// 每 2 秒检查一次
loop {
    thread::sleep(Duration::from_secs(2));

    if is_stopping(&app) { break; }          // 正在退出就别再重启
    if !backend_exited(&app) { continue; }   // 还活着，继续巡

    // 崩了：先回启动页，避免用户盯着一个失联页面
    navigate(&app, &window, loading_url.clone());

    match start_backend(&app) {
        Ok(port) => navigate(&app, &window, Url::parse(&format!("http://127.0.0.1:{port}/"))?),
        Err(e) => {
            show_error_on_main(&app, &window, &e);
            thread::sleep(Duration::from_secs(20));   // 失败退避，避免刷屏
        }
    }
}
```

**验证**：

```bash
# 记下后端 PID 后强杀
kill -9 <后端PID>
# 2 秒内窗口应回到「加载中」，随后自动恢复；日志里应出现一次新的启动记录
```

#### 4.7 启动失败要让用户看见

最容易犯的错：`navigate` 失败只写 `eprintln!`，用户看到的是永远转圈的启动页。

正确做法是给启动页约定一个错误入口：

```html
<!-- frontend/public/loading.html -->
<script>
  window.showStartupError = function (message) {
    document.body.classList.add('error');
    document.getElementById('title').textContent = '词札启动失败';
    document.getElementById('msg').textContent = message;
  };
</script>
```

```rust
// Rust 侧：页面可能还没加载完，所以重试若干次
for attempt in 0..10 {
    let _ = app.run_on_main_thread(move || {
        let _ = window.eval(format!("window.showStartupError({msg});"));
    });
    thread::sleep(Duration::from_millis(200));
}
```

**验证**：临时把后端可执行文件改名，重启 App，应看到「启动失败 + 日志路径」，而不是白屏或无限加载。

---

### 阶段 5：把后端塞进 App，并保证「不是旧版本」

**目标**：`cargo tauri build` 出来的 `.app` 里，后端必须和当前代码一致。

**第 1 步：复制资源 + 生成清单**

```bash
# 先有 onedir 产物 dist/cizha-backend/
python3 scripts/prepare-sidecar.py
# 结果：
#   src-tauri/resources/backend/            （后端整个目录）
#   src-tauri/resources/backend-manifest.json
```

清单长这样（刻意用 key=value，Rust 里不引 JSON 库也能读）：

```properties
source=/Users/you/cizha/dist/cizha-backend
exe=cizha-backend
exe_size=12345678
file_count=321
total_size=98765432
generated_at=1760000000
```

**第 2 步：构建时校验（`build.rs`）**

为什么需要这一步？因为「改了后端 → 忘了重跑 prepare-sidecar」是**不会报错**的，App 会安静地带着旧后端发布。这种 bug 最难查：源码是对的，测试是过的，用户装上的版本是错的。

```rust
// release 构建时才严格校验（dev 下只警告，避免打断开发）
if profile != "release" { return; }

// 1. 后端目录必须存在
if !backend_dir.is_dir() {
    panic!("请先运行 prepare-sidecar.py 准备后端资源");
}

// 2. manifest 必须存在（缺了就 panic，不允许「猜」）
let manifest = fs::read_to_string(&manifest_path)
    .expect("缺少 backend-manifest.json，请重跑 prepare-sidecar.py");

// 3. 实际 exe 大小 == manifest 里的 exe_size
// 4. 实际文件数 == manifest 里的 file_count
// 5. 如果 dist/ 还在，dist 里的 exe 大小也必须一致
//    → 防止「重新打包了后端，但没重新复制」
```

**第 3 步：资源映射与构建**

```jsonc
"bundle": {
  "resources": { "resources/backend": "backend" }
}
```

```bash
cd src-tauri
~/.cargo/bin/cargo tauri build --bundles app
# 产物：src-tauri/target/release/bundle/macos/词札.app
```

**怎么验证**：

```bash
APP="src-tauri/target/release/bundle/macos/词札.app"

# 1. 资源真的进去了
ls "$APP/Contents/Resources/backend/" | head

# 2. Info.plist 版本正确
/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$APP/Contents/Info.plist"

# 3. 启动 App，确认后端版本（应与 tauri.conf.json / package.json 一致）
open "$APP"
curl -s http://127.0.0.1:<端口>/api/health

# 4. 确认签名状态（未签名/adhoc 时这里会显示）
codesign -dv --verbose=2 "$APP" 2>&1 | head -20
```

**成功标志**：`Contents/Resources/backend/cizha-backend` 存在；`/api/health` 返回的版本与配置一致。

> **为什么不用 `--bundles app,dmg` 一步到位？**
> 正常情况下可以。但本次环境的命令沙箱禁止 `bundle_dmg.sh` 写 `/Volumes`，所以先打 `app`，再手工做 dmg（见阶段 6）。这是环境限制，不是技术限制。

---

### 阶段 6：生成 dmg 与自动化发布

**手工 dmg（沙箱环境可用）**：

```bash
APP="src-tauri/target/release/bundle/macos/词札.app"
STAGE=/tmp/dmg-stage
rm -rf "$STAGE" && mkdir -p "$STAGE"

# 1. 复制 App
ditto "$APP" "$STAGE/词札.app"

# 2. 加 /Applications 快捷方式（用户拖进去就能装）
ln -s /Applications "$STAGE/Applications"

# 3. 生成压缩 dmg
hdiutil create -volname "词札" -srcfolder "$STAGE" \
  -ov -format UDZO "词札_0.2.1_aarch64.dmg"
```

**验证**：

```bash
hdiutil verify "词札_0.2.1_aarch64.dmg"
open "词札_0.2.1_aarch64.dmg"      # 挂载后应看到 App + Applications 快捷方式
```

**CI 自动化（GitHub Actions）的关键顺序**：

```yaml
- run: cd frontend && npm ci && npm run build       # 1. 前端
- run: cd backend && python -m PyInstaller ../build/pyinstaller/cizha-backend.spec
                                                     # 2. 后端
- run: python3 scripts/prepare-sidecar.py           # 3. 复制 + manifest
- run: cargo tauri build --bundles app,dmg          # 4. 壳层
```

**验证**：打一个 `v*` tag，确认 Release 附件里有 dmg，下载后能打开。

---

### 阶段 7：自测清单（发布前逐项打勾）

```bash
# 后端
cd backend && ./venv/bin/python -m unittest discover -s tests -t . -v
ruff check app tests

# 前端
cd frontend && npm run build

# 桌面（对着 App 做，不是 dev）
open -a "词札.app" && open -a "词札.app"      # 单实例
kill -9 $(pgrep -f cizha-backend)              # 2 秒内自动恢复
kill -TERM $(pgrep -f "词札")                  # 无残留
tail -n 50 ~/Library/Logs/com.cizha.vocab/backend.log
```

---

## 三、踩坑实录与避坑指南

> 下面每一条都是本次真实遇到或真实验证过的。按「问题现象 → 根本原因 → 解决方案」记录，建议当排错字典用。

### 坑 1：改了代码、重启了 App，行为完全没变

**问题现象**：明明改了 Rust 和后端，重新 `open -a` 之后端口还是旧的、日志还是旧内容。

**根本原因**：macOS 的 LaunchServices 不会为同一个 bundle 启动第二个实例，它把「打开」请求交给了**已经在运行的那个旧进程**；而单实例插件又让新进程直接退出。你看到的自始至终是旧进程。

**解决方案**：

```bash
# 先确认旧进程，再按 PID 精确杀掉（不要只杀一个）
pgrep -fl "词札"
pgrep -fl cizha-backend
kill -TERM <壳层PID>

# 等 1~2 秒确认没有残留，再启动
open -a "/Applications/词札.app"
```

**预防**：每次验证「新构建」前，先跑一遍 `pgrep -fl cizha`；养成「先清理再启动」的习惯。

---

### 坑 2：App 退出了，后端还在后台跑（孤儿进程）

**问题现象**：`Cmd+Q` 或 `kill` 掉 App 后，`pgrep cizha-backend` 还能看到进程，端口仍被占用。

**根本原因**：只监听了 `RunEvent::Exit`，而 `kill -TERM`、系统注销不会走这个事件；或者退出流程里漏了 `cleanup_backend`。

**解决方案**：

1. 用 `sigwait` 专用线程接管 SIGTERM/SIGINT/SIGHUP；
2. 三个退出入口（托盘 / RunEvent::Exit / 信号线程）统一走 `mark_stopping → cleanup_backend`；
3. 先 SIGTERM 等 3 秒，再 SIGKILL。

**预防**：把「退出清理」写成一个函数，所有退出入口只能调它，不允许各写一套。

---

### 坑 3：后端收不到 SIGTERM，日志里没有优雅关闭

**问题现象**：退出时后端直接消失，日志停在半截；或者必须等 3 秒被 SIGKILL。日志里看不到 `Shutting down`。

**根本原因**：父进程在 `main()` 里屏蔽了 SIGTERM，**子进程会继承父进程的信号屏蔽字**。后端从出生起就听不见 SIGTERM。

**解决方案**：spawn 时用 `pre_exec` 清空子进程的屏蔽字：

```rust
#[cfg(unix)]
{
    use std::os::unix::process::CommandExt;
    unsafe {
        cmd.pre_exec(|| {
            let mut empty = std::mem::zeroed();
            libc::sigemptyset(&mut empty);
            libc::sigprocmask(libc::SIG_SETMASK, &empty, std::ptr::null_mut());
            Ok(())
        });
    }
}
```

**预防**：凡是「父进程改过信号掩码」的项目，子进程一定要显式恢复；这是 Unix 进程模型的常见陷阱。

---

### 坑 4：端口偶发启动失败（明明探测到空闲）

**问题现象**：`find_free_port()` 返回 18765，交给后端 bind 时却报 `Address already in use`；重试几次又好了。

**根本原因**：**检查和使用之间存在时间窗**（TOCTOU）。你释放探测 socket 到后端 bind 之间，别的进程可能抢走了这个端口。

**解决方案**：不再猜端口。传 `--port 0` 让系统分配，后端启动后把真实端口写进 ready 文件。

**预防**：任何「先找资源再用资源」的逻辑都要怀疑是否有竞态；能让系统原子分配的，就不要自己选。

---

### 坑 5：打包出来的 App 功能是旧的

**问题现象**：源码里已经修好的 bug，安装包里依然存在；测试全绿，用户装上的版本却是错的。

**根本原因**：重新跑了 PyInstaller，但**忘了重跑 `prepare-sidecar.py`**，`src-tauri/resources/backend/` 里还是上一次的副本；而 Tauri 打包读的是这个副本。

**解决方案**：

1. 立刻重跑 `python3 scripts/prepare-sidecar.py`；
2. 让 `build.rs` 在 release 构建时比对 `exe_size` / `file_count`，不一致直接 panic；
3. 在清单里记录 `source`，如果 dist 里的后端变大了，也能发现「复制件过期」。

**预防**：把「前端构建 → 后端打包 → 复制资源 → 壳层构建」固定成一条脚本或 CI 步骤，禁止手工跳步。

---

### 坑 6：后端日志一片空白，出了问题无从查起

**问题现象**：启动失败只看到「转圈」，日志目录里没有文件，或者文件是空的。

**根本原因**：`Stdio::null()` 把输出丢了；或者用 `Stdio::piped()` 却从不读取，缓冲区写满后后端直接卡死。

**解决方案**：stdout/stderr 一律 append 到 `backend.log`；stderr 用 `try_clone()` 复用句柄；启动失败提示里带上日志绝对路径。

**预防**：只要涉及「子进程 + 长期运行」，就不要用 pipe，除非你确实有消费者在持续读。

---

### 坑 7：启动页白屏、一直转圈，或者一闪白底

**问题现象**：双击后先白一下，然后才出现深色启动页；或者卡在启动页没有任何提示。

**根本原因**：

1. 窗口配置 `visible: true`，WebView 创建瞬间会先画白底；
2. 启动失败只 `eprintln!`，页面不知道要显示错误；
3. 在页面还没加载完时 `eval`，脚本被丢弃。

**解决方案**：

1. `visible: false`，等 200ms 再 `show()`；
2. 给启动页约定 `window.showStartupError(message)`；
3. Rust 侧间隔 200ms 重试 10 次；
4. 导航失败也走同一个错误入口。

**预防**：桌面 App 的启动路径上，**每个失败分支都必须有用户可见的出口**，不允许「静默失败」。

---

### 坑 8：后端崩了，用户盯着一个永远加载不出来的页面

**问题现象**：运行中后端被系统杀掉或自己崩溃，页面所有请求报错，用户只能重启 App。

**根本原因**：没有看护（watchdog）线程；或者只看进程一次，没有循环检查。

**解决方案**：启动成功后每 2 秒 `try_wait` 一次；崩溃则回启动页 → 重启 → 导航新端口；重启失败退避 20 秒。

**预防**：桌面应用的「后端」是不可靠资源，凡是本地服务都要假设它会死。

---

### 坑 9：双击两次出现两个托盘、两个后端

**问题现象**：托盘出现两个图标；两个后端同时读写 SQLite，偶发数据库锁。

**根本原因**：没有单实例插件，或插件注册顺序太靠后。

**解决方案**：`tauri-plugin-single-instance` 必须**最先注册**；回调里把已有窗口唤到前台。

**预防**：只要 App 会写本地数据库，就必须做单实例；端口和文件锁都救不了「两个写者」。

---

### 坑 10：`bundle_dmg.sh` 报权限错误

**问题现象**：`cargo tauri build --bundles dmg` 在 `bundle_dmg.sh` 阶段失败，提示无法写 `/Volumes/dmg.xxx/Applications: Permission denied`。

**根本原因**：当前执行环境（IDE 的命令沙箱）禁止挂载和写入 `/Volumes`，不是 Tauri 配置错误。

**解决方案**：先 `--bundles app`，再用 `ditto` + `ln -s /Applications` + `hdiutil create` 手工生成 dmg。

**预防**：CI 用干净 runner 不会有这个问题；本地遇到时先判断是「环境权限」还是「配置错误」，不要盲目改配置。

---

### 坑 11：`dist/cizha-backend/cizha-backend` 报 `not a directory`

**问题现象**：直接执行 `dist/` 下的后端，shell 报 `zsh: not a directory`；复制到别处却能跑。

**根本原因**：`dist/` 路径下存在与可执行文件同名的特殊文件/目录状态问题（本次为环境偶发现象），不是代码问题。

**解决方案**：用 `src-tauri/resources/backend/` 的副本验证；App 实际读取的也是这个副本。

**预防**：验证后端时优先用「App 真正会用的路径」，减少环境干扰。

---

### 坑 12：首次运行 ready 文件为空 / 进程秒退

**问题现象**：刚复制出来的后端第一次运行时，ready 文件为空或进程立即退出；第二次就正常。

**根本原因**：macOS 对新建可执行文件的首次校验（Gatekeeper / 文件元数据）会带来瞬时延迟，叠加首次冷启动。

**解决方案**：保持 30 秒就绪超时 + 2 次自动重试；`prepare-sidecar.py` 复制后 `chmod 0755`。

**预防**：不要把「首次启动」当成稳定态来测；至少连续启动 3 次再下结论。

---

### 坑 13：`cargo add` 离线失败 / 找不到 cargo

**问题现象**：`cargo add tauri-plugin-single-instance@2 --offline` 报找不到包；或终端里 `cargo: command not found`。

**根本原因**：本地 registry 缓存里没有该 crate；cargo 安装在 `~/.cargo/bin`，不在默认 PATH。

**解决方案**：去掉 `--offline` 让它联网拉取；命令统一写 `~/.cargo/bin/cargo`。

**预防**：新环境先跑 `~/.cargo/bin/cargo --version` 和一次 `cargo fetch`。

---

### 坑 14（Mac 潜在坑）：用户双击提示「已损坏，无法打开」

**问题现象**：未签名/未公证的 App 下载后被系统拦下，提示「无法验证开发者」或「已损坏，请移到废纸篓」。

**根本原因**：文件带 `com.apple.quarantine` 扩展属性，且 App 没有 Developer ID 签名与公证。

**解决方案（用户侧）**：

```bash
xattr -dr com.apple.quarantine "/Applications/词札.app"
open "/Applications/词札.app"
# 或：右键 → 打开 → 再次确认「打开」
```

**解决方案（开发者侧，未来）**：配置 `bundle.macOS.signingIdentity` + Apple 公证（notarization）。

**预防**：在内测说明里写清「右键打开」；正式分发前一定要做签名和公证。

---

### 坑 15（Mac 潜在坑）：在 Apple Silicon 上打出了 x86_64 的后端

**问题现象**：App 能启动，但后端起不来；日志里是 `Bad CPU type in executable`。

**根本原因**：PyInstaller 用的是 x86_64 的 Python（例如通过 Rosetta 安装的旧 Python），打出来的后端是 x86_64；而 App 或系统期望 arm64。

**解决方案**：

```bash
# 确认 Python 架构
file $(which python3)
python3 -c "import platform; print(platform.machine())"   # 期望 arm64
```

用 arm64 的 Python 重新打包；CI 固定 `macos-latest`（arm64）。

**预防**：把「Python 架构与目标机器一致」写进构建检查；跨架构分发需要 universal2 或分别打包。

---

### 坑 16（Mac 潜在坑）：Hardened Runtime 下加载不了 Python 的动态库

**问题现象**：签名后 App 启动即崩，Console 里是 `code signature invalid` 或 dyld 加载失败。

**根本原因**：Hardened Runtime 默认禁止加载「不同 Team ID 签名」或未签名的 dylib；PyInstaller 产物里大量 `.so/.dylib` 需要被允许。

**解决方案**：在 `entitlements.plist` 中按需开启：

```xml
<key>com.apple.security.cs.disable-library-validation</key>
<true/>
<key>com.apple.security.cs.allow-unsigned-executable-memory</key>
<true/>
<key>com.apple.security.cs.allow-jit</key>
<true/>
```

**预防**：这三项是 Python sidecar 的常见组合；但它们是「降低安全限制」，正式分发前要评估，并且需要配合公证。

---

### 坑 17（Mac 潜在坑）：临时目录路径带空格 / 特殊字符

**问题现象**：ready 文件偶发读不到；或 Python 侧路径处理报错。

**根本原因**：`$TMPDIR` 在 macOS 上通常是 `/var/folders/xx/.../T/`，不同机器可能包含特殊字符；手工拼命令时未加引号。

**解决方案**：Rust 用 `std::env::temp_dir().join(...)` 生成路径，不要字符串拼接；shell 命令一律加双引号。

**预防**：任何路径都当作「可能含空格」处理。

---

### 坑 18（Mac 潜在坑）：WebView 缓存导致页面像「没更新」

**问题现象**：重新打包后，页面还是旧样式；清缓存后正常。

**根本原因**：WKWebView 会缓存资源；或者你连的还是旧后端端口（旧进程没退）。

**解决方案**：先确认旧进程已退出；必要时在开发阶段清 WebView 缓存，或每次启动使用新端口（本项目 `--port 0` 天然规避了端口复用）。

**预防**：把「先杀旧进程」作为验证新构建的第一步；发布版本用新端口 + 新版本号双重确认。

---

### 坑 19（CI 必现坑）：GitHub Actions `working-directory` 导致 .spec 相对路径错位

**问题现象**：CI 三平台 PyInstaller step 全挂，报错 `ERROR: Spec file "build/pyinstaller/cizha-backend.spec" not found!`。本地打包正常，只有 CI 挂。

**根本原因**：CI step 设了 `working-directory: backend`，PyInstaller 会从当前工作目录起找 .spec——变成找 `backend/build/pyinstaller/...`，但 .spec 实际在仓库根 `build/pyinstaller/...`。

```yaml
# ❌ 错误写法
- name: Build backend
  working-directory: backend
  run: python -m PyInstaller build/pyinstaller/cizha-backend.spec ...
  # PyInstaller 从 backend/ 起找，变成 backend/build/pyinstaller/... → 找不到

# ✅ 正确写法：不用 working-directory，显式 cd + 相对路径
- name: Build backend
  run: |
    cd backend
    python -m PyInstaller ../build/pyinstaller/cizha-backend.spec \
      --workpath ../_pybuild --distpath ../dist --clean
```

**解决方案**：去掉 `working-directory`，改用 `cd backend` + `../build/pyinstaller/...` 相对路径。

**预防**：CI 里尽量不用 `working-directory`——它改变的是 shell 的 cwd，但工具链内部（PyInstaller、cargo、npm）可能依赖相对于 repo root 的路径。显式 `cd` + 相对路径更不歧义。

---

### 坑 20（Tauri 2 API 坑）：`activate_ignoring_other_apps` 是 Builder 方法，不是运行时方法

**问题现象**：编译报错 `no method named activate_ignoring_other_apps found for mutable reference &mut tauri::App`。你在 `setup(|app| { app.activate_ignoring_other_apps(true); })` 里调，编译不过。

**根本原因**：Tauri 2 把「启动时的配置」和「运行时的 API」分得很清：

| 谁 | `activate_ignoring_other_apps` 可用 |
|---|---|
| `tauri::Builder` | ✅ 链式方法 `.activate_ignoring_other_apps(true)` |
| `&mut tauri::App`（setup 闭包里） | ❌ 没有这个方法 |
| `&AppHandle` | ❌ 没有这个方法 |

它是 Builder 链式配置项——**在 `.setup()` 之前调用**，运行时不能再改。

```rust
// ✅ 正确位置：Builder 链上
tauri::Builder::default()
    .plugin(...)
    .activate_ignoring_other_apps(true)  // ← 这里
    .setup(|app| { ... })
    .run(...)

// ❌ 错误位置：setup 闭包里
.setup(|app| {
    app.activate_ignoring_other_apps(true);  // ← 编译不过
})
```

**解决方案**：移到 Builder 链上。效果是：以后每次 `window.show()` 或 `window.set_focus()` 时，底层都会自动调 `NSApp.activate(ignoringOtherApps: true)`，把窗口强制拉到最前。

**预防**：Tauri 2 的 Builder 上有不少「只在构建期可用」的配置方法，搜到文档里是 Builder 链式的，就别在 setup/run 里找。

---

### 坑 21（macOS Gatekeeper 坑）：`spctl` 报 "has no resources but signature indicates they must be present"

**问题现象**：`codesign -dv` 显示 `Signature=adhoc` + `Sealed Resources=none`，`spctl -a -vv 词札.app` 返回：
```
词札.app: code has no resources but signature indicates they must be present
```
本地双击能开，但发给别人 Gatekeeper 会拦。

**根本原因**：两个条件叠加触发：
1. entitlements.plist 里开了 Hardened Runtime（`hardenedRuntime: true`）
2. adhoc 自签时 `Sealed Resources=none`（自签不会为资源目录生成密封哈希）

Hardened Runtime **要求** sealed resources——因为它会校验动态库加载、内存权限等运行时行为，没密封就等于"我信你但你没给身份证"。

**解决方案**（按优先级）：

| 场景 | 做法 |
|---|---|
| 本地开发 / 自测 | 关掉 Hardened Runtime（`hardenedRuntime: false`），spctl 不严格 |
| 内部分发（小范围） | 保持 Hardened Runtime + adhoc，用户 `xattr -cr` 去隔离即可 |
| 公开分发 | 必须 Developer ID 签名 + notarization，签名会自动生成 sealed resources |

**预防**：本地开发阶段别开 Hardened Runtime——它会引入一堆你暂时还不想解决的签名问题。等准备发布了再开。

---

### 坑 22（entitlements 配置坑）：`com.apple.security.app-sandbox` 不能同时 true 和 false

**问题现象**：entitlements.plist 里同时写了：
```xml
<key>com.apple.security.app-sandbox</key>
<false/>
<key>com.apple.security.network.client</key>
<true/>
```
编译后 App 启动崩溃，日志里有 sandbox 相关错误。

**根本原因**：macOS entitlement 的规则是——**如果 plist 里出现了任何 entitlement key，系统就会把你当作"参与 sandbox"处理**。你写 `app-sandbox = false` 但又写了 `network.client = true`，等于告诉系统"我不进沙箱但我要沙箱里的网络权限"——冲突，系统行为不可预测。

**解决方案**：要么全关（不写任何 sandbox 相关 key，让 App 跑在非沙箱模式），要么全开（开 sandbox + 逐项授权）。不要混合。

本项目最终用的配置：
```xml
<!-- 不写 app-sandbox，也不写任何 sandbox 子 key → 非沙箱模式 -->
<key>com.apple.security.cs.allow-jit</key>
<true/>
<key>com.apple.security.cs.disable-library-validation</key>
<true/>
<key>com.apple.security.network.client</key>
<true/>
<key>com.apple.security.network.server</key>
<true/>
```

**预防**：entitlements.plist 里不要为了"完整"把所有 key 都写上——只写你真的需要的。一个都不写 = 非沙箱模式，最灵活。

---

### 坑 23（Tauri 2 MenuBuilder 坑）：自定义菜单栏的 API 签名和想象不一样

**问题现象**：想给 App 加 Cmd+W / Cmd+R 自定义菜单项，照 Tauri 1 的写法写：
```rust
let menu = Menu::with_submenus(&[&file_submenu, ...])?;
```
编译报错——要么缺参数，要么泛型 trait 不满足。

**根本原因**：Tauri 2 的菜单 API 做了大改——**Menu / Submenu / MenuItem 的构造都需要 `Manager<R>` 泛型约束**（通常是 `AppHandle`），不能无参构造：

```rust
// ❌ Tauri 1 写法（Tauri 2 没有）
let menu = Menu::with_submenus(&[&file_submenu])?;

// ✅ Tauri 2 正确写法
//   1. 每个 Submenu / MenuItem 都要传 &AppHandle
let show_item = MenuItem::with_id(&app_handle, MENU_SHOW, "打开词札", true, None::<&str>)?;
let menu = Menu::with_items(&app_handle, &[&show_item])?;
```

而且 Builder 上的 `.menu()` 需要 `AppHandle`，但 AppHandle 只有在 setup 闭包（或 plugin 初始化时）才能拿到——Builder 链本身拿不到。所以**自定义菜单栏要么在 plugin 里做，要么放弃自定义用 Tauri 自动提供的默认菜单栏**。

**解决方案（本项目选择）：用 Tauri 默认菜单栏**。Tauri 2 在 macOS 上会自动生成：
```
词札 | 文件 | 编辑 | 视图 | 窗口 | 帮助
```
里面已经包含 Cmd+Q 退出、Cmd+W 关闭窗口、Cmd+M 最小化、Cmd+` 切换窗口 等所有标准行为——和你手写的体验完全一样，而且不用写任何 Rust 代码。**90% 的 macOS App 都直接用默认的**。

**什么时候才需要自定义菜单栏？** 当你需要加"关于我的 App"之外的自定义菜单项（比如菜单里有动态列表、或者跨平台的自定义快捷键冲突处理）时。

**预防**：Tauri 2 的 Menu API 不是"拿来就用"的——先确认你是不是真的需要自定义，再动手写。

---

## 四、导师总结与下一步建议

### 4.1 对你这次实践的客观评价

**做得好的地方（已经超过很多「套壳教程」）**：

1. **没有重写业务**：保留了 FastAPI 和 210 个测试，这是最正确的决策。桌面化是「加壳」，不是「重做」。
2. **端口方案选对了**：`--port 0` + ready 文件，直接消灭了最常见的一类随机启动失败。
3. **退出链路完整**：信号接管 + SIGTERM→SIGKILL + 三处退出入口统一，这已经是生产级思路。
4. **有构建防腐机制**：manifest + `build.rs` 校验，防止「旧后端混进新包」。这个意识很值钱。
5. **失败可见**：启动页错误钩子、导航失败回写、日志落盘，说明你在从「能跑」转向「可运维」。

**还不够的地方（也是下一步的发力点）**：

1. **未签名 / 未公证**：内部分发可以，公开分发体验会打折。
2. **CI 还没真正跑过**：YAML 写好了，但没打 tag 验证过，第一次发布大概率会遇到工具版本问题。
3. **没有桌面端自动化测试**：目前靠手工 `kill -9` 验证恢复，容易漏。
4. **Rust 部分主要靠「照葫芦画瓢」**：能跑，但对所有权、线程、信号的理解还不牢。
5. **没有自动更新**：每次发版都要用户手动下载。

### 4.2 你目前的知识盲区

按优先级排：

| 盲区 | 具体表现 | 为什么要补 |
|---|---|---|
| **Unix 进程与信号** | 说不清 SIGTERM/SIGKILL 区别、屏蔽字继承、孤儿进程 | 所有「退出残留」问题都源于这里 |
| **Rust 并发与所有权** | `Arc`/`Mutex`/`Send` 边界、为什么用 `run_on_main_thread` | 壳层逻辑会越来越复杂，靠猜容易写出死锁 |
| **Tauri 的两种通信方式** | 分不清「HTTP 访问本地后端」和「Tauri IPC 调 Rust 命令」 | 决定你以后加功能时该走哪条路 |
| **macOS 签名体系** | 不懂 ad-hoc / Developer ID / 公证 / Hardened Runtime 的关系 | 决定能不能公开分发 |
| **PyInstaller 内部机制** | 不清楚 `_MEIPASS`、hook、hiddenimports、onedir 结构 | 打包报错时只能瞎试 |
| **CI/CD** | 不熟矩阵构建、artifact、Release 附件 | 手工打包不可持续 |

> **IPC 是什么？**
> 一句话：**同一个 App 里，前端页面和 Rust 主进程之间直接对话的专用通道**（Tauri 的 `invoke`），不经过网络端口。
> 本项目没用 IPC，而是让前端直接 HTTP 访问 Python 后端 —— 因为后端本来就是 HTTP 服务，多绕一层没有收益。

### 4.3 学习路线（按顺序，别跳）

**第 1 阶段：把「进程生命周期」学透（1~2 周）**

- 读《Unix 环境高级编程》里信号、fork/exec、wait 的章节（只需这几节）。
- 动手实验：写一个最小 C 或 Rust 程序，父进程 spawn 子进程，分别测试 `kill -TERM`、`kill -9`、父进程先死。
- 目标：能解释本项目 `terminate_child` 每一行为什么必须那样写。

**第 2 阶段：Rust 基础 + Tauri 机制（2~3 周）**

- 过一遍 Rust Book 第 1~10 章 + 第 16 章（并发）。
- 读 Tauri 官方文档的「Process Model」「Command (IPC)」「Sidecar」三节。
- 动手：给本项目加一个「关于」窗口，用 IPC 从 Rust 取版本号。
- 目标：能判断一个新需求该用 HTTP、IPC 还是前端纯本地实现。

**第 3 阶段：打包与分发（1~2 周）**

- 读 PyInstaller 官方文档的 `Spec Files`、`Runtime Information`、`Hooks`。
- 学 `codesign`、`spctl`、`notarytool` 的基本用法。
- 动手：给本项目加签名（自签证书即可），验证 `spctl -a -vv` 的行为变化。
- 目标：能独立产出一个「双击不报错」的 dmg。

**第 4 阶段：自动化与可观测性（持续）**

- 把发布流程固化成脚本；给 CI 加缓存和失败重试。
- 加结构化日志（至少带时间戳和启动次数）。
- 目标：打一个 tag 就能产出可分发版本，不需要手工介入。

### 4.4 这个项目接下来最值得做的 5 件事

按「性价比」排序：

1. **打一次真实 tag，跑通 CI**（验证 PyInstaller / Tauri CLI 版本可安装）。
2. **加自动更新**（Tauri updater + 签名密钥），解决「用户手动下载」的体验断点。
3. **桌面端冒烟测试脚本**：启动 → 检查健康 → `kill -9` → 等待恢复 → 退出 → 检查残留，全部自动化。
4. **签名与公证**：拿到 Developer ID 后补齐，这是公开分发的前置条件。
5. **开机自启 + 通知**：桌面常驻类工具的自然延伸，Tauri 都有官方插件。

### 4.5 给你的三条长期建议

1. **把「验证方式」写在需求里**。你这次最宝贵的不是代码，而是 PRD 里那套可执行的验收标准（单实例、2 秒恢复、3 秒退出）。以后每加一个功能，先写「怎么证明它成了」。
2. **不要为了「技术统一」重写能跑的东西**。Python 后端有 210 个测试，这是资产，不是包袱。Easydict 那种成熟 App 也是「Swift 壳 + 内嵌 HTTP 服务」的混合结构。
3. **每次踩坑都补一条「不变量」**。比如「子进程必须恢复信号掩码」「release 必须有 manifest」。坑会重复，但写成规则就不会重复第三次。

---

## 附录：术语小抄（一句话版）

| 术语 | 一句话解释 |
|---|---|
| **Tauri** | 用系统自带浏览器内核 + Rust 壳来做桌面 App 的框架，体积小。 |
| **WebView** | 系统提供的「浏览器组件」，Tauri 用它来显示你的网页。 |
| **Sidecar** | 跟着主程序一起分发、由主程序启动和关闭的副进程。 |
| **IPC** | 同一 App 内前后端直接对话的专用通道（Tauri 的 `invoke`），不走网络。 |
| **PyInstaller** | 把 Python 代码 + 解释器 + 依赖打成一个可执行程序的工具。 |
| **onedir / onefile** | onedir = 一个目录（启动快）；onefile = 单个文件（每次启动要解压，慢）。 |
| **`_MEIPASS`** | PyInstaller 运行时的临时资源目录，打包后代码靠它找资源。 |
| **ready 文件** | 后端启动成功后写下真实端口的临时文件，用来消除端口竞态。 |
| **SIGTERM** | 「请你体面地退出」信号，程序可以收尾。 |
| **SIGKILL** | 「立刻死」信号，程序无法拦截，可能丢数据。 |
| **孤儿进程** | 启动它的程序已经退出，它还在后台跑。 |
| **单实例** | 同一时刻只允许一个 App 进程，避免双写数据库。 |
| **Hardened Runtime** | macOS 的运行时加固选项，限制加载未签名动态库等行为。 |
| **公证（Notarization）** | 把 App 交给 Apple 自动扫描，通过后系统才默认信任。 |
| **Gatekeeper** | macOS 的「这道菜谁做的」检查，未签名会被拦。 |
| **quarantine** | 下载文件带的「隔离」标记，是 Gatekeeper 拦截的触发条件之一。 |
| **ad-hoc 签名** | 没有证书的本地签名，能骗过一部分检查，但不能公证。 |
| **manifest** | 构建时生成的「资源清单」，用来校验打包内容没被替换。 |
| **SPA 兜底** | 前端路由用 history 模式时，所有未知路径都返回 index.html。 |
| **SSE** | 服务器单向持续推送数据的 HTTP 技术，本项目用于流式翻译。 |
