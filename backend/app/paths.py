"""统一的资源路径解析——源码模式和 PyInstaller 打包模式同一份代码。

使用：
    from app.paths import get_data_dir, get_env_path, is_packaged

源码模式：
    数据目录 = backend/data/
    .env   = backend/.env

PyInstaller 模式：
    数据目录 = ~/Library/Application Support/cizha/     (macOS)
            或 %APPDATA%/cizha/                         (Windows)
            或 $XDG_DATA_HOME/cizha/                    (Linux)
    .env   = 数据目录/.env（首次从 PyInstaller 内置的 .env.example 复制过去）

为什么要独立一个 paths.py：
    database.py / config.py / main.py 都要找 data/ 下的资源，
    把「PyInstaller 临时目录 → 用户目录」的平台判断写在一处，
    避免三份重复代码、也方便以后加更多资源类型。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


APP_NAME = "cizha"


def is_packaged() -> bool:
    """是否跑在 PyInstaller 打出来的单文件里。"""
    return getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS")


def _source_backend_root() -> Path:
    """源码模式下的 backend/ 根目录（从 paths.py 自身位置推）。"""
    return Path(__file__).resolve().parent.parent


def _packaged_bundle_dir() -> Path:
    """PyInstaller 临时解压目录——里面有打包时 --add-data 带进去的资源。"""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(os.path.dirname(sys.executable))


def _user_data_dir() -> Path:
    """用户可写的数据目录（PyInstaller 模式用这个）。"""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    target = base / APP_NAME
    target.mkdir(parents=True, exist_ok=True)
    return target


def get_data_dir() -> Path:
    """SQLite / llm_config.json / .env 统一存放位置。

    PyInstaller 首次启动时会把打包时内置的 data/ 目录（含 cizha.db 占位、
    llm_config.json 等）复制到用户目录，之后一直读写用户目录，
    临时目录退出即丢也不影响数据。
    """
    if not is_packaged():
        return _source_backend_root() / "data"

    user_dir = _user_data_dir()
    bundle_data = _packaged_bundle_dir() / "data"
    if bundle_data.is_dir():
        for item in bundle_data.iterdir():
            dest = user_dir / item.name
            if not dest.exists():
                try:
                    if item.is_file():
                        shutil.copy2(item, dest)
                    elif item.is_dir():
                        shutil.copytree(item, dest)
                except OSError as exc:
                    print(f"paths: 复制资源 {item.name} 到用户目录失败（{exc}），忽略。", file=sys.stderr)
    return user_dir


def get_env_path() -> Path:
    """.env 文件位置。源码模式下不存在不会报错（默认没配 Key 也能跑）。"""
    if not is_packaged():
        candidate = _source_backend_root() / ".env"
        if candidate.is_file():
            return candidate
        # fallback：可执行文件同级（源码模式下一般 cwd 就是 backend/）
        candidate = Path.cwd() / ".env"
        return candidate

    user_dir = _user_data_dir()
    user_env = user_dir / ".env"
    if user_env.is_file():
        return user_env
    # 首次启动：从 PyInstaller 内置的 .env.example 复制过去
    bundle_example = _packaged_bundle_dir() / ".env.example"
    if bundle_example.is_file():
        try:
            shutil.copy2(bundle_example, user_env)
            return user_env
        except OSError:
            pass
    # 都没有，让 python-dotenv 自己去找（会静默跳过）
    return Path.cwd() / ".env"


def get_app_version() -> str:
    """版本号集中在这里导出，避免 database.py / config.py / main.py 各写一份。

    从 src/main.py 的 APP_VERSION 读取，保证单一数据源。
    """
    # main.py 还没加载就被 database.py / config.py 提前 import 时，
    # 这里硬编码兜底一个值；正式版本号由 main.py 在启动时覆盖到 /api/health。
    try:
        from .main import APP_VERSION  # noqa: WPS433 —— 延迟 import 避免循环
        return APP_VERSION
    except (ImportError, AttributeError):
        return "0.1.1"
