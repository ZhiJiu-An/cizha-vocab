# Easydict 技术栈分析 & cizha 桌面化方案

> 分析对象：<https://github.com/tisfeng/Easydict>（GPL-3.0）
> 分析方式：clone 源码后逐层阅读（`Easydict/Swift`、`Easydict/objc`、`Podfile`、`Info.plist`、`project.pbxproj`、`docs/design-docs/`）
> 目标：把 cizha（FastAPI + Vue 3 的本地 Web 工具）做成桌面软件
> 日期：2026-10
>
> 📖 **看不懂里面的名词？先读 [`00-名词科普.md`](00-名词科普.md)**——Tauri / sidecar / Rust / 签名公证 / GPL 逐个白话解释。

---

## 第一部分：Easydict 用了什么技术

### 1.1 基本事实

| 项 | 值 |
|---|---|
| 形态 | macOS 原生 App，**常驻菜单栏**（`LSUIElement=1`，无 Dock 图标） |
| 最低系统 | **macOS 13.0** |
| 许可证 | **GPL-3.0**（重要，见 1.8） |
| 语言构成 | Swift **372** 个文件 + Objective-C **206** 个 `.m/.h`（遗留层） |
| 规模 | `Service/` 下近 30 个目录，README 自述支持 **20+** 词典/翻译/AI 服务 |
| 测试 | **58** 个 Swift 测试文件，用 Apple 新的 **Swift Testing**（`import Testing` / `@Suite`） |
| 构建 | Xcode workspace + **CocoaPods**（ObjC 老三件）+ **SPM**（现代依赖）双轨 |

### 1.2 分层架构

```text
Easydict/
├── App/         # 入口、Assets、Info.plist、本地化(xcstrings)、Bridging-Header
├── Swift/
│   ├── Feature/      # 产品功能：划词、截图、快捷键、HTTPServer、AnkiConnect、VocabularyNotebook…
│   ├── Model/        # 共享数据模型（QueryModel / QueryResult / QueryError…）
│   ├── Service/      # 每个翻译/词典/AI 服务一个目录（Youdao/DeepL/OpenAI/Ollama…）
│   ├── Utility/      # EventMonitor（事件监听）、SystemUtility（AX/选区/菜单动作）、Defaults
│   └── View/         # SwiftUI 为主，AppKit 兜底
├── objc/        # 遗留实现：MMKit、StatusItem、ViewController、WebViewTranslator、Service
└── EasydictTests/
```

架构文档自己写明了边界：

> 新的 UI 组件使用 SwiftUI；在平台集成需要时，保留现有的 AppKit 和 Objective-C 边界。

**这是一个"渐进式现代化"的真实样本**：新代码全 SwiftUI，老代码（菜单栏 `StatusItem`、WebView 翻译、`Masonry`/`ReactiveObjC` 那套）原样留着，靠 Bridging Header 互通。没有为了"技术栈统一"重写一遍。

### 1.3 依赖清单（从 pbxproj 的 `repositoryURL` 提取）

| 依赖 | 用途 | 对我们有参考价值吗 |
|---|---|---|
| **Sparkle** | 自动更新（EdDSA 签名） | ⭐⭐⭐ 桌面版必选 |
| **LaunchAtLogin-Modern** | 开机自启 | ⭐⭐⭐ |
| **KeyHolder** | 全局快捷键注册 | ⭐⭐⭐ |
| **KeySender** | 模拟键盘事件（发 Cmd+C 取选区） | ⭐⭐⭐ |
| **SelectedTextKit** | 划词取词库（作者自己维护） | ⭐⭐⭐ 权限方案参考 |
| **Defaults** | UserDefaults 类型安全封装 | ⭐⭐ |
| **Alamofire** | 网络层 | ⭐ |
| **SnapKit / Masonry / ReactiveObjC** | 布局 + 响应式（新旧两代） | ✕ |
| **JLRoutes** | URL Scheme 路由（`easydict://`） | ⭐⭐ 深链 |
| **Vapor** | **内嵌 HTTP 服务器** | ⭐⭐⭐⭐ 见 1.4 |
| **Sentry / Firebase** | 崩溃上报 / 分析 | ⭐⭐ |
| **CryptoSwift / ZipArchive / MJExtension** | 加密 / 解压 / JSON 映射 | ⭐ |
| **MacPaw/OpenAI** | OpenAI 兼容 SDK | ⭐ |
| **SettingsAccess / SFSafeSymbols / Hue / OmenTextField / AcknowList** | UI 小工具 | ✕ |
| **SwiftFormat / SwiftLint**（BuildTools 里的 SPM 插件） | 格式化 / 静态检查 | ⭐⭐ |

### 1.4 关键发现一：它内嵌了一个 HTTP 服务器

这是整个分析里**对你最有价值的一条**。Easydict 用 **Vapor（Swift 的 Web 框架）** 在本机起了一个 HTTP 服务，默认端口 **8080**（`Defaults` key `httpPort`，设置页可改）：

```text
GET  /                  → "Hello, Welcome to Easydict server!"
POST /translate         → 同步翻译
POST /streamTranslate   → SSE 流式翻译（text/event-stream）
POST /detect            → 语言检测
GET  /selectedText      → 拿系统当前选中的文本
```

它做这件事的动机很清楚：**把 App 的能力变成可编程的本地 API**，让 Raycast / Alfred / 自己的脚本 / 编辑器插件都能调它。

也就是说：**一款成熟的 macOS 原生 App，内部也是"前端 + 本地 Web 服务"的结构。**

而 cizha 现在就是「Vue 前端 + FastAPI 本地服务」——**架构方向是对的，你缺的只是外壳，不是重构。**

### 1.5 关键发现二：一项桌面能力，一种系统级实现

下表的 "实现方式" 全部来自源码，是"桌面软件才能做"的能力清单，也是 cizha Web 版**永远做不到**的部分：

| 桌面能力 | Easydict 的实现 | cizha Web 版现状 |
|---|---|---|
| 常驻菜单栏 / 托盘 | `Info.plist` 的 `LSUIElement=1` + `objc/StatusItem/` | ❌ 必须开着浏览器标签页 |
| 全局快捷键 | `KeyHolder` + `CGEventTap`（`Utility/EventMonitor/Engine/EventTapMonitor.swift`）+ `NSEvent.addGlobalMonitorForEvents` | ❌ 只在页面聚焦时有效 |
| 划词取词（核心） | `SelectedTextKit` + `SystemUtility+AX`（AXUIElement API，**需要"辅助功能"授权**），取不到时用 `KeySender` 模拟 `Cmd+C` 兜底 | ❌ 只能手动粘贴/上传图片 |
| 静默截图 OCR | `/usr/sbin/screencapture` + `CGDisplayCreateImage` + 自绘选区 overlay | ❌ 只能上传/粘贴图片 |
| OCR 引擎 | 系统 **Vision**（`VNRecognizeTextRequest`），并自研 `OCRLineAnalyzer` / `OCRSectionMerger` / `OCRPoetryDetector` 做**断行合并与断句** | 用云端视觉大模型（另一种路线，成本更高但零本地依赖） |
| 系统词典 | Apple Dictionary（读 macOS"词典"App 已启用的词典）+ MDict（导入 MDX/MDD） | ❌ |
| 系统翻译 | Apple Translate（离线） | ❌ |
| 开机自启 | `LaunchAtLogin-Modern` | ❌ |
| 自动更新 | **Sparkle** + `appcast.xml` + EdDSA 公钥（`SUPublicEDKey`） | ❌ 用户自己 `git pull` |
| URL Scheme 深链 | `easydict://` + JLRoutes | ❌ |
| 权限：辅助功能 / AppleScript | `NSAppleEventsUsageDescription` + AX 信任检查 | — |
| 崩溃上报 | Sentry + Firebase | ❌ |

> 注意：`Easydict.entitlements` 是**空字典**——它是**未开启 App Sandbox**的应用。这是划词/模拟键盘/读系统词典的前提，也意味着它**无法上架 Mac App Store**，只能 Developer ID 分发 + 公证。这个取舍你做桌面版时同样要面对。

### 1.6 关键发现三：它刻意不做"复习"

`Feature/VocabularyNotebook/VocabularyNotebookService.swift` 的注释写得很直白：

> Appends completed query results to the local `words.jsonl` file consumed by an **external review program** and synced via Syncthing.

它只把查询结果追加到 `words.jsonl`：

```swift
struct VocabularyEntry: Codable {
    var text: String              // 查询文本
    var sourceLanguage: String    // BCP-47
    var targetLanguage: String
    var translatedText: String?
    var timestamp: Date
    var dictionaryEntry: DictionaryEntry?   // 句子/流式查询时为 nil
}
```

然后**交给外部复习程序 + Syncthing 同步**。

**这句话等价于：Easydict 的作者认为"查词"和"记忆复习"是两件事，后者留给外部工具。**

而 cizha 恰好做了后者（六档间隔重复 + 错题本 + 统计）。这是一个非常明确的定位差异点，详见第三部分。

### 1.7 工程质量做法（可直接借鉴）

| 做法 | 说明 |
|---|---|
| **规格文档驱动** | `AGENTS.md` 是 Agent 唯一入口 + 任务路由；`docs/design-docs/`（架构）、`docs/exec-plans/`（计划）、`docs/histories/`（历史）分离 |
| 规则单一职责 | 各专题文档只写一件事，跨职责用链接，不复制条款 |
| 发布流程工具化 | `.agents/skills/release-easydict/` 里带 Python 测试（`test_release_appcast.py` 等），**连 appcast 生成都有测试** |
| 测试边界 | 测试目录镜像源码目录（`Service/OpenAI/` → `EasydictTests/Service/OpenAI/`），用 Swift Testing 的 `.serialized` / tags 组织 |
| 新功能验收 | "新增服务必须新增该服务专属验证测试文件"，且允许依赖本机 CLI/密钥（不进 CI） |
| 分阶段迁移 | ObjC 不强行重写，新 UI 一律 SwiftUI |

> 这几条跟你 cizha 现在的做法（MVP.md + `docs/versions/` 归档 + 210 测试 + 三轮审查）**高度一致**，说明你的工程习惯没问题，差距只在"平台层"。

### 1.8 许可证警告（必须先说）

**Easydict 是 GPL-3.0，cizha 是 Apache-2.0。**

- ❌ **不能**把 Easydict 的任何代码（包括它 `SelectedTextKit` 那套划词实现，需自行确认该库许可证）复制/改写到 cizha 里——那会让你的整个项目被迫 GPL。
- ✅ **可以**读它的源码学习"用什么 API、走什么流程、申请什么权限"，然后**自己用系统 API 重写**。思路不受版权保护，实现受。
- ✅ **可以**读写它产出的 `words.jsonl`（那是用户自己的数据文件，程序间通过数据文件交互不构成链接）。

---

## 第二部分：cizha 与 Easydict 的能力对照

| 维度 | Easydict | cizha 现状 | 差距性质 |
|---|---|---|---|
| 查词入口 | 划词 / 快捷键 / 截图 / 手动 | 必须在浏览器里输入或粘贴 | **桌面外壳缺失（可补）** |
| 释义来源 | 20+ 服务并行对比 | 有道（通用）+ 1 个 LLM（领域五段式） | 定位不同，非差距 |
| 结构化输出 | 各服务原样展示 | **五段式定名/全称/详解/例句/译文**，可映射进数据库字段 | **cizha 优势** |
| 词库 | 只写 `words.jsonl` | SQLite 完整词库 + 标签 + 批量操作 + CSV | **cizha 优势** |
| 复习 | ❌ 交给外部程序 | **六档间隔 + 三档自评 + 错词本 + 趋势统计** | **cizha 优势（核心）** |
| 平台 | 仅 macOS | 任意浏览器（mac/Linux/Win） | cizha 可跨平台 |
| 安装方式 | DMG + 自动更新 | `git clone` + 跑脚本 | **明显短板** |
| 划词 | ✅ 系统级 | ❌ | 需要桌面壳 |
| 通知提醒 | ✅ 原生 | 页面内 / 浏览器通知（页面关了就没了） | 需要桌面壳 |
| 数据位置 | 标准 App 目录 | 仓库内 `backend/data/` | 需要迁移 |

**一句话结论**：cizha 的**数据层与复习层更强**，Easydict 的**取词入口与系统集成更强**。你要补的是"入口"，不是"能力"。

---

## 第三部分：桌面化路线选型

### 3.1 五条路线

| 方案 | 体积 | 代码复用 | 系统能力 | 跨平台 | 开发成本 | 结论 |
|---|---|---|---|---|---|---|
| **A. Tauri 2**（Rust 壳 + 系统 WebView） | 安装包 **10~15MB**（+ Python sidecar 30~60MB） | 前端 **100%**、后端 100%（作为 sidecar） | ⭐⭐⭐⭐⭐ 托盘/全局快捷键/自启/通知/更新/深链全有官方插件；划词需自己写 AX 绑定 | ✅ Win/mac/Linux | 中（Rust 只写胶水） | **推荐** |
| **B. Electron** | **120~200MB** | 前端 100%、后端 sidecar | ⭐⭐⭐⭐ 生态最全（`uiohook-napi`、`nut.js`、`active-win`） | ✅ | 低（纯 JS） | 备选（怕 Rust 就选它） |
| **C. pywebview / Python 原生壳** | 40~80MB | 前后端 **100%** | ⭐⭐ 托盘要 `pystray`，无官方更新器，快捷键靠 `pynput` | ✅ | 最低 | 想"两天出可用版"选它 |
| **D. 原生 Swift 重写**（Easydict 路线） | **< 10MB** | **0%** | ⭐⭐⭐⭐⭐ | ❌ 仅 macOS | 极高（6 千行重写 + 学 AppKit/AX） | 长期终极形态，不建议现在 |
| **E. PWA / 加桌面书签** | 0 | 100% | ⭐ 无全局快捷键、无划词、无托盘 | ✅ | 零 | 治不了你的核心痛点 |

### 3.2 推荐：Tauri 2 + Python sidecar（阶段式）

**为什么是 Tauri 而不是 Electron：**

1. 你的痛点集中在「托盘 / 全局快捷键 / 划词 / 通知 / 自启 / 更新」——这六项 Tauri 有**官方插件**（`tauri-plugin-global-shortcut`、`notification`、`autostart`、`updater`、`single-instance`、`deep-link`），不用自己拼生态。
2. 安装包体量小一个数量级（10MB vs 150MB），**对你这种个人项目，下载转化率就是推广效果**。
3. 复用系统 WebView（mac 用 WKWebView、Win 用 WebView2），Vue 3 的构建产物**原样塞进去就行**，前端零改动。

**为什么保留 Python 后端而不是重写成 Rust：**

- 你有 210 个测试、六档复习算法、幂等迁移、SSE 代理，全部在 FastAPI 里，重写风险极高、收益为零。
- **Easydict 自己也是「原生壳 + 内嵌 HTTP 服务」**（Vapor on 8080）。你的 FastAPI 就是那个"内嵌服务"，只是换个运行时。
- 代价是安装包多 30~60MB（打进去一个 Python 运行时）。**可接受，且可以日后再优化**。

> ⚠️ 一个前置事实：**你机器上没装 Rust**（`cargo --version` 不存在），Node 是 v26、Python 是 3.14。选 Tauri 需要先 `brew install rustup` + `rustup default stable`，第一次 `cargo build` 会编译几百个 crate，约 5~15 分钟。这不是问题，只是别在赶文章截稿时开始。

---

## 第四部分：落地路线（分四阶段，每阶段都可发布）

### Phase 0 · 先蹭 Easydict（1~2 天，零桌面开发）

**不需要写任何桌面代码，就能拿到"划词"和"导入历史词"两个能力。** 但要精确区分两条路，它们的机制完全不同。

#### 路 A · 读它的笔记本（文件级 / 离线）

Easydict 有 **VocabularyNotebook** 功能，每查完一个词就往 `words.jsonl` 追加一行。细节已从源码确认：

| 项 | 值 |
|---|---|
| 文件名 | `words.jsonl`（固定） |
| 位置 | **用户自选目录**（设置 → 高级 → 词本目录），默认空 = 功能关闭 |
| 格式 | JSONL，每行一条；时间戳为本地时区 ISO 8601（`yyyy-MM-dd'T'HH:mm:ssXXX`） |
| 写入 | 串行队列追加，应用退出前 `flush()` 落盘 |

单行结构：

```jsonc
{
  "text": "transformer",
  "sourceLanguage": "en",
  "targetLanguage": "zh",
  "translatedText": "变换器",
  "timestamp": "2026-10-22T19:09:12+08:00",
  "dictionaryEntry": {                    // 整句/流式查询时为 null
    "phonetics": [{ "word": "transformer", "language": "en",
                    "value": "trænsˈfɔːrmər", "accent": "us", "speakURL": "https://…" }],
    "parts": [{ "part": "n.", "means": ["变换器", "变压器"] }],
    "exchanges": [], "tags": [], "etymology": null,
    "synonyms": [], "antonyms": [], "collocation": []
  }
}
```

**cizha 侧**：新增 `POST /api/words/import/easydict`，映射表见下表。

| Easydict 字段 | cizha `Word` | 说明 |
|---|---|---|
| `text` | `abbreviation` | 主词（必填） |
| `translatedText` | `my_meaning` | cizha 必填；为 null 时用 `parts` 首条兜底 |
| `phonetics[].value`（按 `accent`） | `phonetic_uk` / `phonetic_us` | 按 `us` / `uk` 分流 |
| `parts[].part` + `means[]` | `api_meaning` | 拼成 `n. 变换器；变压器` 多行文本 |
| `timestamp` | `created_at` | 保留原始查询时间 |
| `exchanges` / `synonyms` / `antonyms` / `collocation` / `etymology` / `tags` | （无对应） | 可选塞 `note` 或丢弃 |
| — | `cn_term` / `domain_detail` | **Easydict 没有**，导入后可选择性批量调 LLM 补全 |
| — | `examples` | 词典结果通常不带例句，留空数组 |
| — | `review_stage=0` / `next_review_at=今天` / `in_review=1` | 与现有新词入库规则一致 |

导入的四条业务规则（照 cizha 已有的数据纪律来）：

1. **跳过整句**：`text` 含空格、或 `dictionaryEntry == null` 的多为句子，默认不导（给开关）。
2. **按 `abbreviation` 去重**：已存在则跳过，保证重复导入幂等。
3. **`my_meaning` 必填**：`translatedText` 为空必须兜底，否则整个导入事务失败。
4. **增量同步**：`words.jsonl` 是追加写的，记录"已处理到第几字节偏移"，不要每次全量重扫。

#### 路 B · 问它现在选了什么（请求级 / 在线）

Easydict 在本机 `127.0.0.1:8080`（默认，可在设置里改）开了 HTTP 服务：

```text
GET  /selectedText      ← 返回当前系统选区文本
POST /translate         ← 同步翻译
POST /streamTranslate   ← SSE 流式翻译
POST /detect            ← 语言检测
```

cizha 侧：前端加一个「从 Easydict 取词」按钮 → 后端代理 `GET /selectedText` → 文本灌进搜索框 → 走现有双源查询。

- ✅ 省掉复制粘贴，等于白嫖一个"划词"入口
- ⚠️ 需要 Easydict 开着 + 用户启用了该服务；**必须做优雅降级**（拿不到就提示"手动粘贴也可以"，不能报错）
- ⚠️ **不要写成强依赖**：cizha 必须能完全脱离 Easydict 独立使用

**成本**：两个后端接口 + 一个按钮。**收益**：立刻有划词入口 + 解决"我已有几百个词在别的工具里"这个最高频迁移痛点 + 宣传上"与 Easydict 联动"天然吸它的用户。

> 这一阶段还能顺手验证一件重要的事：**用户到底更在意"划词"还是"复习"**。如果没人用这个按钮，说明桌面化的优先级应该降。

### Phase 1 · Tauri 外壳 MVP（1~2 周）

目标：双击图标 → 出窗口 → 能用 → 能退出干净。**不含划词。**

要做的事：

```text
1. 前端：dist 原样作为 Tauri 前端（不改一行 Vue）
2. 后端：PyInstaller 打成 onedir → 随 Tauri `bundle.resources` 放进 App（启动不用解压）
3. 启动握手：Python 启动后把实际端口打到 stdout，Rust 侧读到即 window.show()
4. 数据目录：从 <repo>/backend/data 迁到 ~/Library/Application Support/com.cizha.vocab
5. 托盘：显示/隐藏窗口、今日待复习数、退出
6. 单实例 + 二次启动只唤醒已有窗口
7. Windows / macOS 双构建（Linux 暂缓）
```

关键代码骨架（FastAPI 侧要改的地方很少）：

```python
# backend/run.py：从 argv 取端口与 ready 文件
import time
from pathlib import Path

def _ready_port(server, ready_file: str) -> None:
    while not server.started:      # 等 uvicorn 真正开始监听
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    Path(ready_file).write_text(str(port), encoding="utf-8")
```

```rust
// src-tauri/src/main.rs（骨架）
fn spawn_backend(ready_file: &Path) -> std::process::Child {
    Command::new(sidecar_path())            // PyInstaller onedir 产物
        .args(["--port", "0", "--ready-file"])
        .arg(ready_file)
        .stdin(Stdio::null())
        .spawn().expect("backend failed to start")
}

// 壳层轮询 ready 文件拿实际端口，再探测 /api/health
let port = read_ready_port(ready_file);
```

**必须处理的四个坑**（都是别人踩过的）：

1. **进程生命周期**：Rust 退出时要结束后子进程，否则每次退出留一个 Python 孤儿；注销 / `kill` 也不会走 `RunEvent::Exit`，要自己接管 SIGTERM/SIGINT/SIGHUP。顺序是 SIGTERM → 等 3 秒 → SIGKILL，注意子进程会继承父进程的信号屏蔽字（在 `pre_exec` 里清空）。
2. **不要开 `--reload`**：桌面版绝不能带 `--reload`，否则 uvicorn 会拉起第二个进程，杀不干净。
3. **不要用 stdout 握手**：后端 stdout/stderr 已重定向到日志文件（`~/Library/Logs/<bundle id>/backend.log`），stdout 既会被块缓冲也可能与日志混在一起；改用 `--ready-file` 回传实际端口。
4. **不能用 `run_server` 里 `os.chdir` 到仓库目录**：桌面版没有仓库目录，所有相对路径都要改成基于数据目录的绝对路径。

### Phase 2 · 全局快捷键 + 划词取词（2~4 周，真正的分水岭）

这是唯一"必须写平台原生代码"的部分：

| 平台 | 取选区 | 权限 |
|---|---|---|
| macOS | `AXUIElementCopyAttributeValue(kAXSelectedTextAttribute)`；取不到时模拟 `Cmd+C` 读剪贴板 | 需 **辅助功能**授权（`AXIsProcessTrustedWithOptions`），首次引导用户去系统设置勾选 |
| Windows | **UI Automation**（`TextPattern`）| 通常不需要额外授权；少数 UWP 应用取不到，回落 `Ctrl+C` |
| Linux | `xdotool` / AT-SPI | 依赖桌面环境 |

三档降级路径（**照这个顺序写，用户才不会觉得"这软件坏了"**）：

```text
AX 直接读选区  →  模拟 Cmd+C 读剪贴板（备份原剪贴板内容，读完还原）  →  托盘图标点击后粘贴
```

权限被拒时**不能只在控制台打日志**——弹一个可操作的引导（"去系统设置 → 隐私与安全性 → 辅助功能，勾上词札"），并且**降级到剪贴板轮询**（监听剪贴板变化，检测到英文词就弹小窗）。

> 提醒：全局快捷键 + 划词 + 系统通知 + 读剪贴板，这几件事加起来会触发 macOS 多个隐私授权项。**第一次启动就要有一个"权限引导"页**，一次讲清楚要什么、为什么、不给我怎么用。Easydict 也经历过这个阶段（它的 README 里有专门的空间讲权限）。

### Phase 3 · 系统通知 + 自动更新 + 签名公证（1 周）

| 事情 | 做法 | 坑 |
|---|---|---|
| 复习提醒 | `tauri-plugin-notification`，替代现在的浏览器 Notification（页面一关就没了） | 需要在应用启动时注册；通知点击要能拉起对应页面 |
| 自动更新 | `tauri-plugin-updater`（自带签名校验，等价于 Sparkle） | 需要一张签名私钥 + 一个静态 JSON 的更新地址（GitHub Release 即可） |
| macOS 签名 | `codesign` + Developer ID 证书 | 见下方「签名三情形」 |
| macOS 公证 | `notarytool` 提交苹果云端扫描 | **只有签名没有公证，照样被拦**，两个都要 |
| Windows 签名 | 可选，不签名会触发 SmartScreen 警告 | 个人项目可以先不买，文档写清"更多信息 → 仍要运行" |
| 分发 | GitHub Release 挂 `.dmg` / `.msi` | 顺手把 CHANGELOG 内容作为 Release 正文 |

#### 签名三情形（别被"装不上"吓到）

| 情形 | 结果 |
|---|---|
| **自己编译、自己用** | ✅ **双击就开**。本机编译的文件不带隔离属性，开发期完全不需要签名 |
| **别人从浏览器下载** | ⚠️ 被 Gatekeeper 拦：没签名 → "无法验证开发者"；签名未公证 → 同样被拦。**macOS 15 起"右键→打开"旁路已取消**，用户得去「系统设置 → 隐私与安全性 → 仍要打开」 |
| **用户执行 `xattr -dr com.apple.quarantine`** | ✅ 能绕过，但要求用户会开终端 |

准确表述是：**不签名 ≠ 装不上，而是 ≠ 普通用户愿意装。**

#### 三条分发路线

| 路线 | 成本 | 体验 |
|---|---|---|
| **Apple Developer Program** | **$99/年**（约 ¥688） | 用户双击就开，最顺 |
| **发未公证版**（README 写 `xattr` 命令） | 免费 | 转化率大约砍半，但能发 |
| **Homebrew Cask 分发** | 免费 | 非浏览器下载，通常不打隔离标记，可绕开弹窗；但要求用户装了 Homebrew |

#### 开发期的坑（做到划词时一定会遇到）

**没签名时，每次重新编译 App 的"辅助功能"系统授权可能被重置**，得去系统设置重新勾一遍。做划词功能时一天要重编几十次，这个坑非常折磨人。

对策：开发期至少做 **ad-hoc 签名**（`codesign -s -`），保持签名指纹稳定，授权就不会反复失效。

### Phase 4（可选）· 后端 Rust 化，出单文件二进制

只有当"安装包体积"变成真实用户抱怨时才做。届时把 FastAPI 换成 `axum` + `rusqlite`，安装包能压到 15MB 以内。**但要注意：等于重写一遍，210 个测试要重写成 Rust 测试。**

---

## 第五部分：风险清单（按危险程度排）

| # | 风险 | 影响 | 对策 |
|---|---|---|---|
| 1 | **macOS 不签名/不公证** | 普通用户被 Gatekeeper 拦下（“无法验证开发者”），转化率大约砍半 | 预算内买 Developer Program（$99/年）；否则 README 写清 `xattr` 绕过命令，或走 Homebrew Cask |
| 2 | **Python sidecar 杀不干净** | 用户每次退出留孤儿进程 / 端口占用 | 显式 `kill` + 退出钩子 + 启动时清理残留端口 |
| 3 | **辅助功能权限被拒** | 划词功能全废 | 三档降级 + 引导页 + 剪贴板轮询兜底 |
| 4 | **安装包过大（>150MB）** | 下载转化率暴跌 | Tauri + PyInstaller onedir；别塞 node_modules/modules |
| 5 | **数据目录迁移丢数据** | 用户炸号级事故 | 复用你已有的 `migrate_legacy_db` 思路：**复制不移动**、失败可回滚、先在 README 写明路径 |
| 6 | **本地端口冲突** | 启动失败 | 后端 `--port 0` 由 OS 分配 + stdout 握手 |
| 7 | **本地 HTTP 服务被外部访问** | 隐私泄露（词库 + 明文 Key） | 只绑 `127.0.0.1`；CORS 白名单你已有；sidecar 加一次性 token 更好 |
| 8 | **杀软误报（Windows）** | 用户不敢装 | PyInstaller 产物常见，签个名或多引擎扫一遍再发 |
| 9 | **WebView2 缺失（Win）** | 白屏 | Tauri 的 `webview2` 引导安装；或用 `offlineInstaller` 模式 |
| 10 | **GPL 污染** | 被迫开源整个项目 | **只读 Easydict 源码学思路，绝不复制代码** |

---

## 第六部分：战略建议（比技术更重要）

### 6.1 不要在"划词翻译"上正面硬刚

Easydict 在这个赛道上已经做了 3 年、20+ 服务、GPL、macOS 原生、体验打磨到极致。**你花半年做的划词，用户体验上限就是"又一个 Easydict"。**

### 6.2 你的护城河在别处

| 你的独有资产 | 为什么别人难以复制 | 怎么放大 |
|---|---|---|
| **五段式结构化领域释义** | 把 LLM 输出变成**可入库字段**（定名/全称/详解/例句/译文），这是"从查词到记词"的关键一跃 | 宣传时主打"查完就能存，存完就能复习" |
| **六档间隔复习闭环** | Easydict 明确把这块留给外部程序 | 桌面版做好"到点弹通知 → 点开就复习" |
| **跨平台** | Easydict 只有 macOS | Windows 用户是空白市场（CSDN 读者绝大多数是 Windows） |
| **统计与错题本** | 数据在自己手里才有的洞察 | 桌面版可做"每周学习周报" |

### 6.3 最优产品定位（一句话）

> **Easydict 负责"看到就查"，词札负责"查完记住"。**

具体到交互：桌面版不需要自己做划词翻译，只需要做**划词收集**——

```text
选中任意文本 → 全局快捷键 → 弹一个 3 行小窗
  [ 有道释义 ]  [ 领域定名 ]  [ 一键收藏 ]  [ 继续复习 ]
                      ↓
            不进任何翻译详情页，只进复习队列
```

**"收集器"而不是"翻译器"** —— 这个定位既避开了正面冲突，又把你的复习闭环变成入口的终点。

### 6.4 Phase 0 的联动值得先做

理由：零成本、验证需求、还顺带解决了"我已经有一堆词在别的工具里"的迁移痛点。而且写文章时"词札能与 Easydict 联动"是个很自然的技术话题。

---

## 第七部分：建议的下一步（三选一）

| 选项 | 工作内容 | 产出 | 耗时 |
|---|---|---|---|
| **A（推荐先做）** | Phase 0：Easydict 联动 | 后端 `/api/words/import/easydict` + 前端"从 Easydict 取词"按钮 | 1~2 天 |
| **B** | Phase 1：Tauri 骨架 | 能双击启动、托盘、单实例、干净退出的最小桌面版 | 1~2 周 |
| **C** | Phase 2：划词 | 全局快捷键 + AX 选区 + 收藏小窗 | 2~4 周 |

三条都不冲突，**建议 A → B → C 顺序做**。A 是纯增量、零风险；B 决定项目形态；C 是真正的体验分水岭。

---

## 附：本文档的结论速查

1. **Easydict = 菜单栏常驻（LSUIElement）的 Swift/SwiftUI + AppKit + ObjC 混合原生 App**，靠 `SelectedTextKit` + AX API 做划词、`screencapture` + Vision 做截图 OCR、Sparkle 做更新、**Vapor 在 8080 起内嵌 HTTP 服务**。
2. **它内部也是"前端 + 本地 HTTP 服务"**，所以 cizha 的架构不需要重构——**缺的只是外壳**。
3. **cizha → 桌面版推荐 Tauri 2 + Python sidecar**：前端零改动、安装包 10MB 级、托盘/快捷键/通知/自启/更新全有官方插件。
4. **唯一必须写原生代码的部分是划词取选区**（macOS AX / Windows UIA），且必须设计三档降级。
5. **最大风险不是技术，是 macOS 签名公证**。注意准确表述：自己用完全不需要签名（本机编译不带隔离属性）；发给普通用户才需要，不公证会被 Gatekeeper 拦（macOS 15 起“右键→打开”旁路已取消），可用 `xattr` 绕过但会劝退多数人。
6. **Easydict 是 GPL-3.0，只学思路，不要抄代码。**
7. **战略上做"收集器"而不是"翻译器"**，你的护城河是五段式结构化 + 复习闭环 + 跨平台。
