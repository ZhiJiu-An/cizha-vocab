# PyInstaller 配置：Phase 1
#
# 打包命令（中间产物放 _pybuild/，避免和 .gitignore 冲突）：
#   backend/venv/bin/python -m PyInstaller build/pyinstaller/cizha-backend.spec \
#       --noconfirm --workpath _pybuild --distpath dist
#
# 产物：dist/cizha-backend/（onedir 目录：可执行文件 + _internal/）
#
# 为什么用 onedir 而不是 onefile：
#   onefile 每次启动都要把 ~39MB 内容解压到临时目录，实测启动到端口就绪要 6 秒；
#   onedir 首次约 2 秒、之后 0.5 秒内，桌面端「双击即用」的体感差别很大。
#   目录由 scripts/prepare-sidecar.py 复制进 src-tauri/resources/backend/，
#   再由 Tauri bundle.resources 打进 App。
#
# Phase 1 完成内容：
#   - SQLite / llm_config.json / .env 首次启动自动复制到用户目录
#     macOS: ~/Library/Application Support/cizha/
#     Windows: %APPDATA%/cizha/
#     Linux:  $XDG_DATA_HOME/cizha/
#   - 前端 dist 嵌入，FastAPI 直接托管静态页面
#
# 已知限制：
#   - 未做代码签名 / notarization
#   - 不跨平台（macOS arm64 单文件不能在 Windows 跑）
#
# macOS add-data 分隔符 ':'，Windows 用 ';'。

import os

block_cipher = None

# SPECPATH = build/pyinstaller/，dirname 两次回项目根
project_root = os.path.dirname(os.path.dirname(SPECPATH))
backend_root = os.path.join(project_root, "backend")


def _data_dirs():
    """打包时 --add-data 带进去的资源。

    规则：都从 PyInstaller 临时目录（_MEIPASS）作为源，paths.py 的
    get_data_dir() 在首次启动时自动复制到用户目录。
    """
    items = []
    # 1. 数据库 + llm_config.json（首次从这里复制到用户目录）
    data = os.path.join(backend_root, "data")
    if os.path.isdir(data):
        items.append((data, "data"))
    # 2. 前端 dist（FastAPI 直接托管，不走用户目录复制）
    frontend_dist = os.path.join(project_root, "frontend", "dist")
    if os.path.isdir(frontend_dist):
        items.append((frontend_dist, "frontend/dist"))
    # 3. .env.example（首次启动复制到用户目录的 .env）
    env_example = os.path.join(backend_root, ".env.example")
    if os.path.isfile(env_example):
        items.append((env_example, "."))
    return items


a = Analysis(
    [os.path.join(backend_root, "run.py")],
    pathex=[backend_root],
    binaries=[],
    datas=_data_dirs(),
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    collect_all=["app"],
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="cizha-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name="cizha-backend",
)
