# 桌面化（Desktop）文档

把 cizha 从「浏览器里的本地 Web 工具」变成「双击就能用的桌面软件」的调研与方案。

| 文档 | 内容 | 什么时候读 |
|---|---|---|
| [`00-名词科普.md`](00-名词科普.md) | Tauri / sidecar / Rust / 签名公证 / GPL 的白话解释 | **先读这篇**。没做过原生桌面开发，直接看方案会卡在名词上 |
| [`01-Easydict技术栈与cizha桌面化方案.md`](01-Easydict技术栈与cizha桌面化方案.md) | Easydict 源码级拆解、能力对照、五种桌面路线选型、四阶段落地路线 | 决策阶段读；动手前当 checklist 用 |
| [`Tauri-PyInstaller-实战与避坑指南.md`](Tauri-PyInstaller-实战与避坑指南.md) | 1–18 号坑（规划阶段）+ 19–23 号坑（实际开发补） | 踩了坑查对应号；发布前通读一遍做自检 |
| [`macOS-安装指南.md`](macOS-安装指南.md) | 正常用户下载 .dmg 的完整流程 + Gatekeeper 三种绕过 + 开发者手动编译 | 写用户文档、发布 Release 时 |
| [`03-Phase0-4开发复盘.md`](03-Phase0-4开发复盘.md) | 从 Web 到桌面的完整开发历程：每个阶段做了什么、为什么那样决策、踩了什么坑、最终架构长什么样 | 想知道「这次到底怎么搞成的」时读；给别人讲解时当素材 |

---

## 三句话版本

1. **Easydict 是菜单栏常驻的 Swift/SwiftUI + AppKit + ObjC 混合原生 App**，靠 `SelectedTextKit` + macOS AX API 做划词、`screencapture` + 系统 Vision 做截图 OCR、Sparkle 做自动更新，并且**在 `127.0.0.1:8080` 内嵌了一个 Vapor HTTP 服务**。
2. 它内部也是「前端 + 本地 HTTP 服务」，所以 **cizha 的架构不需要重构，缺的只是外壳**。推荐 **Tauri 2 + Python sidecar**：前端零改动、安装包 10MB 级、托盘/快捷键/通知/自启/更新都有官方插件。
3. 唯一必须写原生代码的是**划词取选区**（macOS AX / Windows UIA），且要设计三档降级。**最大风险不是技术，是 macOS 签名公证。**

---

## 关键结论速查

| 问题 | 结论 |
|---|---|
| 需要重写 Vue 前端吗 | ❌ 不需要，dist 原样塞进 Tauri |
| 需要重写 FastAPI 后端吗 | ❌ 不需要，PyInstaller 打成 sidecar |
| 必须装 Rust 吗 | ✅ 要装（约 100~300 行胶水代码），但**用户电脑上不需要** |
| 自己开发的 App 不签名能跑吗 | ✅ 能，本机编译不带隔离属性，双击就开 |
| 发给普通用户不签名行吗 | ⚠️ 会被 Gatekeeper 拦，转化率约砍半；可 `xattr` 绕过或买 Developer Program（$99/年） |
| 能抄 Easydict 的代码吗 | ❌ 不能。它 GPL-3.0，cizha Apache-2.0，**只能学思路** |
| 最快的收益点是什么 | 🎯 Phase 0：读它的 `words.jsonl` 导入词库 + 请求它的 `GET /selectedText` 取选区 |

---

## 阶段划分

> 下面是**实际开发历程**（不是最初的规划）。完整细节见 [`03-Phase0-4开发复盘.md`](03-Phase0-4开发复盘.md)。

| 阶段 | 内容 | 状态 | 关键 commit |
|---|---|---|---|
| **Phase 0** | PyInstaller 可行性验证（onefile 37MB 单文件） | ✅ 完成 | 合并到 main |
| **Phase 1** | 数据持久化 + 前端嵌入（paths.py 统一路径 + FastAPI 托管 dist） | ✅ 完成 | 合并到 main |
| **Phase 2** | 多平台 CI（macOS/Linux/Windows 三矩阵 PyInstaller） | ✅ 完成 | 合并到 main，v0.2.1 发布 |
| **Phase 3** | Tauri 壳层（sidecar spawn + WebView 窗口 + 托盘 + 全局快捷键） | ✅ 完成 | 合并到 main |
| **Phase 4** | macOS 专属优化（entitlements + Hardened Runtime + 启动体验 + .app/.dmg） | ✅ 完成 | 合并到 main |
| **Phase 5**（下一步） | 签名 + notarization（需 Developer ID）+ 自动更新（Tauri updater） | 📋 规划 | — |
| **Phase 6**（可选） | Windows/Linux Tauri 壳层完整验证 + .exe/.deb 安装包 | 📋 规划 | — |

---

## 最终架构一句话

> **macOS 双击 词札.app → Tauri 2（Rust 壳）spawn PyInstaller onedir sidecar → 壳层托管托盘/快捷键/进程生命周期 → WebView 加载 FastAPI 后端托管的 Vue 3 前端 → 用户数据跑在 `~/Library/Application Support/cizha/`**

---

## 战略定位（一句话）

> **Easydict 负责"看到就查"，词札负责"查完记住"。**

做**收集器**，不做**翻译器**——不要在划词翻译上正面硬刚，你的护城河是「五段式结构化领域释义 + 六档间隔复习闭环 + 跨平台」。
