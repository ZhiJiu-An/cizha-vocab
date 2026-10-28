#!/usr/bin/env python3
"""准备后端资源 —— 把 PyInstaller onedir 产物复制到 src-tauri/resources/backend/

用法：
    # PyInstaller 产物在 dist/cizha-backend/（目录）
    python3 scripts/prepare-sidecar.py

    # 指定源目录
    python3 scripts/prepare-sidecar.py --src /path/to/cizha-backend

为什么不是单文件：onefile 每次启动都要解压，实测 6 秒才就绪；
onedir 首次约 2 秒、之后 0.5 秒内，直接决定「双击即用」的体感。
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="准备 Tauri 后端资源（onedir）")
    parser.add_argument(
        "--src",
        default="dist/cizha-backend",
        help="PyInstaller onedir 产物目录（默认 dist/cizha-backend）",
    )
    parser.add_argument(
        "--tauri-dir",
        default="src-tauri",
        help="Tauri 目录（默认 src-tauri）",
    )
    args = parser.parse_args()

    src_dir = Path(args.src).resolve()
    dest_dir = Path(args.tauri_dir).resolve() / "resources" / "backend"

    if not src_dir.is_dir():
        print(f"❌ 源目录不存在: {src_dir}")
        print("   请先跑 PyInstaller（onedir 产物应是一个目录）:")
        print("     cd backend && python -m PyInstaller ../build/pyinstaller/cizha-backend.spec ...")
        return 1

    exe_name = "cizha-backend.exe" if sys.platform == "win32" else "cizha-backend"
    if not (src_dir / exe_name).is_file():
        print(f"❌ 源目录里找不到可执行文件: {src_dir / exe_name}")
        return 1

    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src_dir, dest_dir)

    exe_path = dest_dir / exe_name
    if sys.platform != "win32":
        exe_path.chmod(0o755)

    files = [p for p in dest_dir.rglob("*") if p.is_file()]
    total_bytes = sum(p.stat().st_size for p in files)

    # 写一份 manifest 给 build.rs 校验：release 构建时会比对 exe 大小和文件数，
    # 防止「改了后端忘记重跑本脚本」把旧产物打进 App。
    manifest_path = dest_dir.parent / "backend-manifest.json"
    manifest_path.write_text(
        "\n".join(
            [
                "# 由 scripts/prepare-sidecar.py 生成，build.rs 会据此校验后端资源",
                f"source={src_dir}",
                f"exe={exe_name}",
                f"exe_size={exe_path.stat().st_size}",
                f"file_count={len(files)}",
                f"total_size={total_bytes}",
                f"generated_at={int(time.time())}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"✅ 已准备后端资源: {dest_dir}  ({total_bytes / 1024 / 1024:.1f} MB)")
    print(f"   源: {src_dir}")
    print(f"   清单: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
