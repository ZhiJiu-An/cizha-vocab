# 词札 macOS 安装指南

当前版本：**v0.2.1**  |  适用系统：**macOS 12.0 (Monterey) 及以上 / Apple Silicon**

---

## 方式一：正常安装（推荐）

### 1. 下载

从 GitHub Releases 页面下载 `.dmg` 文件：

> 待发布到 GitHub Releases 后更新链接

文件名：`词札_0.2.1_aarch64.dmg`（~42 MB）

### 2. 安装

1. **双击** 下载的 `.dmg` 文件，系统会弹出安装窗口
2. 把左侧的 **词札** 图标 **拖拽** 到右侧的 Applications 文件夹
3. 等待拷贝完成后，**双击 Applications** 里的 **词札**

### 3. 首次打开 — Gatekeeper 提示

macOS 首次打开从网络下载的 App 时会弹出安全提示，这是正常现象，不是错误。

**弹窗内容：**
> "无法打开'词札'，因为无法验证开发者。"

**解决方法（三选一）：**

**方法 A — 右键打开（最简单）**
1. 在 Applications 里找到 词札.app
2. **右键点击** → 选 **"打开"**（不是双击）
3. 弹窗变成二次确认，再点 **"打开"**
4. 之后就可以直接双击启动了

**方法 B — 系统设置允许**
1. 打开 **系统设置 → 隐私与安全性**
2. 底部会看到提示："已阻止打开'词札'"
3. 点击右侧 **"仍要打开"** 按钮
4. 再双击 词札.app 即可

**方法 C — 终端一行命令**
```bash
xattr -cr "/Applications/词札.app"
```
> 这条命令只在终端跑一次，之后双击就能正常开。建议复制粘贴，引号别漏。

---

## 方式二：开发者手动编译

需要 macOS + Rust 工具链。

```bash
# 1. 装 Rust（minimal profile 足够，~500MB，5 分钟）
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
source "$HOME/.cargo/env"

# 2. 克隆项目（如果你还没 clone）
git clone https://github.com/ZhiJiu-An/cizha-vocab.git
cd cizha-vocab

# 3. 编译后端二进制（首次需要 Python 3.12+）
cd backend && source venv/bin/activate
pip install pyinstaller
python -m PyInstaller ../build/pyinstaller/cizha-backend.spec --noconfirm \
    --workpath ../_pybuild --distpath ../dist --clean
deactivate && cd ..

# 4. 构建前端（loading 页也在这一步进 dist）
cd frontend && npm ci && npm run build && cd ..

# 5. 准备后端资源（onedir 产物 → src-tauri/resources/backend）
python3 scripts/prepare-sidecar.py --src dist/cizha-backend

# 6. 编译桌面 App（~2 分钟 release 构建）
cd src-tauri
cargo tauri build

# 7. 产物在：
# src-tauri/target/release/bundle/macos/词札.app     (95 MB)
# src-tauri/target/release/bundle/dmg/词札_0.2.1_aarch64.dmg  (42 MB)
```

---

## 数据位置

| 项目 | 路径 |
|---|---|
| SQLite 数据库 | `~/Library/Application Support/cizha/cizha.db` |
| llm_config.json | `~/Library/Application Support/cizha/llm_config.json` |
| .env 配置 | `~/Library/Application Support/cizha/.env` |
| App Bundle | `/Applications/词札.app` |

升级版本不会覆盖这些数据，首次启动会自动从旧版本目录迁移。

---

## 常见问题

**Q: 为什么双击 dmg 里的 词札.app 不能直接开？**
因为 macOS Gatekeeper 默认阻止未签名的 App。按上方"方式一 → 步骤 3"的任一方法处理即可。

**Q: 为什么不是"已验证开发者"？**
App 目前是 adhoc 自签（本地可用、Gatekeeper 会提示）。要消除所有提示需要：
1. Apple Developer 账号（$99/年）
2. `cargo tauri signer generate` 生成证书
3. `cargo tauri build --sign` + `cargo tauri build --notarize`

签名 notarization 后下载零提示双击即开，留待后续版本。

**Q: 词札会在 Dock 栏常驻吗？**
默认会在 Dock 里显示（有菜单栏）。关窗口只是隐藏到托盘不退出，托盘图标在右上角菜单栏。

要纯托盘模式（不在 Dock 显示），可以在 Info.plist 里加：
```xml
<key>LSUIElement</key>
<true/>
```
需要重新打包。

**Q: 全局快捷键没反应？**
macOS 首次触发 `Cmd+Shift+C` 时会弹出"是否允许词札使用全局快捷键"，选允许即可。之后在任意 App 里按这个组合键都会唤起词札窗口。

**Q: 后端端口被占了怎么办？**
不用管。词札每次启动都让系统分配空闲端口，后端启动后把实际端口回传给壳层，不会因为端口被占而失败。

**Q: 启动后一直停在"词札 · 加载中"怎么办？**
正常 1 秒内就会进入主界面。超过 30 秒会重试一次；仍然失败会显示"词札启动失败"和具体原因（含日志路径）。
遇到时可先 Cmd+Q 退出再打开；如果反复出现，检查是否有残留后端进程并清理：
```bash
pkill -f cizha-backend
```
后端运行日志在 `~/Library/Logs/com.cizha.vocab/backend.log`，排查启动问题时先看这里。
退出词札时壳层会自动结束后端进程，正常使用不会残留。

---

## 卸载

1. 拖 `/Applications/词札.app` 到废纸篓
2. 可选（清数据）：
   ```bash
   rm -rf ~/Library/Application\ Support/cizha
   ```

---

## 架构说明

```
词札.app (95 MB)
├── 壳层（Rust + Tauri 2）
│   ├── 系统托盘
│   ├── 全局快捷键 Cmd+Shift+C
│   ├── loading 页（后端就绪后跳转前端，失败显示原因）
│   └── WebView（WKWebView，系统自带）
├── Contents/Resources/backend/（PyInstaller onedir，启动无需解压）
│   ├── 监听 127.0.0.1:{port}
│   ├── SQLite + llm_config.json
│   └── 前端静态资源（Vue3 dist）
└── 系统分配端口（后端回传给壳层，崩溃后自动重启）
```
