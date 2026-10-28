# PyInstaller 配置：Phase 0 可行性验证
#
# 打包后产物：dist/cizha-backend（单文件 arm64 Mach-O）
# 验证步骤：
#   cp backend/.env.example dist/.env   # 占位 dotenv
#   ./dist/cizha-backend --port 18765
#   curl http://127.0.0.1:18765/api/health
#
# 已知限制（Phase 0 阶段）：
#   - SQLite 被解压到临时目录，程序退出即丢。持久化路径迁移 Phase 1 加。
#   - 首次启动需解压 37MB 二进制，约 10-12 秒就绪（桌面用户可接受）。
#
# macOS 上 add-data 路径分隔符用 ':'（Windows 用 ';'）。

import os
import sys

block_cipher = None

# SPECPATH 是 build/pyinstaller/，dirname 两次回到项目根
project_root = os.path.dirname(os.path.dirname(SPECPATH))
backend_root = os.path.join(project_root, "backend")


def _data_dirs():
    """要打包进去的资源目录"""
    items = []
    data = os.path.join(backend_root, "data")
    if os.path.isdir(data):
        items.append((data, "data"))
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
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
    collect_all=["app"],  # FastAPI 路由 / Pydantic schema / SQLAlchemy models 全收
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="cizha-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
