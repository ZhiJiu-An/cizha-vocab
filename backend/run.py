#!/usr/bin/env python3
"""PyInstaller 打包入口：替换 `uvicorn app.main:app` 命令行方式。

用法：
    python run.py --host 127.0.0.1 --port 8000
    或直接运行 PyInstaller 产物：./cizha-backend --port 8000

桌面壳层用 `--port 0 --ready-file <path>` 启动：端口交给系统分配，
服务就绪后把实际监听端口写入 ready 文件，避免「先探测空端口再 bind」的竞态。
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path


def _resolve_packaged_dir() -> str | None:
    """PyInstaller 打包后返回临时解压目录，源码模式下返回 None。"""
    return getattr(sys, "_MEIPASS", None)


def _write_ready_port(server, ready_file: str) -> None:
    """等 uvicorn 真正开始监听后，把实际端口写进 ready 文件。"""
    path = Path(ready_file)
    while not server.started:
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    path.write_text(str(port), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Cizha vocabulary backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="源码开发模式热重载")
    parser.add_argument("--ready-file", default=None, help="就绪后把实际监听端口写入该文件")
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

    if args.reload or not args.ready_file:
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
        return 0

    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port))
    threading.Thread(
        target=_write_ready_port,
        args=(server, args.ready_file),
        daemon=True,
    ).start()
    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
