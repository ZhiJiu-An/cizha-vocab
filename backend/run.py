#!/usr/bin/env python3
"""PyInstaller 打包入口：替换 `uvicorn app.main:app` 命令行方式。

用法：
    python run.py --host 127.0.0.1 --port 8000
    或直接运行 PyInstaller 产物：./cizha-backend --port 8000
"""
from __future__ import annotations

import argparse
import os
import sys


def _resolve_packaged_dir() -> str | None:
    """PyInstaller 打包后返回临时解压目录，源码模式下返回 None。"""
    return getattr(sys, "_MEIPASS", None)


def main() -> int:
    parser = argparse.ArgumentParser(description="Cizha vocabulary backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="源码开发模式热重载")
    args = parser.parse_args()

    # PyInstaller 模式：把工作目录切到可执行文件所在目录，
    # 这样 data/、.env.example 等相对路径资源都能找到。
    packaged_dir = _resolve_packaged_dir()
    if packaged_dir:
        os.chdir(os.path.dirname(sys.executable))

    # 确保 backend 在 sys.path 里（源码模式下需要）
    backend_root = os.path.dirname(os.path.abspath(__file__))
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)

    import uvicorn
    from app.main import app

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
