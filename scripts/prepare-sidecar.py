#!/usr/bin/env python3
"""准备 Tauri sidecar —— 把 PyInstaller 产物按 platform triple 重命名放到 src-tauri/binaries/

用法：
    # dev 模式（PyInstaller 产物在 _pybuild/dist/cizha-backend）
    python3 scripts/prepare-sidecar.py

    # 指定源路径（比如 CI 里 PyInstaller 产物在 dist/）
    python3 scripts/prepare-sidecar.py --src dist/cizha-vocab-v0.2.1-darwin-arm64
"""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def get_host_triple() -> str:
    """获取当前平台 Rust target triple。"""
    # 先试 rustc（已安装的情况）
    try:
        result = subprocess.run(
            ["rustc", "--print", "host-tuple"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # fallback：手动映射
    system = platform.system()
    machine = platform.machine()

    if system == "Darwin":
        if machine == "arm64":
            return "aarch64-apple-darwin"
        elif machine == "x86_64":
            return "x86_64-apple-darwin"
    elif system == "Linux":
        if machine in ("x86_64", "AMD64"):
            return "x86_64-unknown-linux-gnu"
        elif machine == "aarch64":
            return "aarch64-unknown-linux-gnu"
    elif system == "Windows":
        if machine in ("x86_64", "AMD64"):
            return "x86_64-pc-windows-msvc"
        elif machine == "ARM64":
            return "aarch64-pc-windows-msvc"

    raise RuntimeError(f"无法识别的平台: {system} {machine}")


def main() -> int:
    parser = argparse.ArgumentParser(description="准备 Tauri sidecar 二进制")
    parser.add_argument(
        "--src",
        default="_pybuild/dist/cizha-backend",
        help="PyInstaller 产物路径（默认 _pybuild/dist/cizha-backend）",
    )
    parser.add_argument(
        "--tauri-dir",
        default="src-tauri",
        help="Tauri 目录（默认 src-tauri）",
    )
    args = parser.parse_args()

    src_path = Path(args.src).resolve()
    tauri_dir = Path(args.tauri_dir).resolve()
    binaries_dir = tauri_dir / "binaries"
    binaries_dir.mkdir(parents=True, exist_ok=True)

    triple = get_host_triple()
    is_windows = platform.system() == "Windows"

    # 源文件名（Windows 带 .exe）
    src_name = src_path.name
    exe_suffix = ".exe" if is_windows else ""

    # 如果用户给的 src 不带 .exe 但实际上是 Windows 产物，补一下
    if is_windows and not src_name.endswith(".exe") and src_path.with_suffix(".exe").exists():
        src_path = src_path.with_suffix(".exe")
        src_name = src_path.name

    if not src_path.exists():
        print(f"❌ 源文件不存在: {src_path}")
        print("   请先跑 PyInstaller:")
        print("     cd backend && python -m PyInstaller ../build/pyinstaller/cizha-backend.spec ...")
        print("   或指定 --src 参数")
        return 1

    # 目标文件名：cizha-backend-{triple}[.exe]
    dest_name = f"cizha-backend-{triple}{exe_suffix}"
    dest_path = binaries_dir / dest_name

    # 清理旧文件
    for old in binaries_dir.glob("cizha-backend-*"):
        if old != dest_path:
            print(f"  🧹 清理旧文件: {old.name}")
            old.unlink()

    # 复制
    shutil.copy2(src_path, dest_path)
    # chmod +x（类 Unix）
    if not is_windows:
        dest_path.chmod(0o755)

    size_mb = dest_path.stat().st_size / 1024 / 1024
    print(f"✅ 已准备 sidecar: {dest_path.name}  ({size_mb:.1f} MB)")
    print(f"   triple: {triple}")
    print(f"   源: {src_path}")
    print(f"   目标: {dest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
