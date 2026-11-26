#!/usr/bin/env bash
# 一键打包桌面版（macOS）。
# 顺序不可颠倒：frontend/dist 会被打进后端，后端产物再复制进 App。
# 任一步失败立即停止，并指出失败步骤。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STEP="初始化"
trap 'echo "错误：打包在「${STEP}」步骤失败，请查看上面的输出。" >&2' ERR

CARGO="${CARGO:-$HOME/.cargo/bin/cargo}"
if [ ! -x "$CARGO" ]; then
  CARGO="cargo"
fi

step() {
  STEP="$1"
  printf '\n==> %s\n' "$STEP"
}

step "1/4 构建前端"
(cd frontend && npm run build)

step "2/4 打包后端（PyInstaller onedir）"
backend/venv/bin/python -m PyInstaller build/pyinstaller/cizha-backend.spec \
  --noconfirm --workpath _pybuild --distpath dist --clean

step "3/4 复制后端产物到 src-tauri/resources/backend"
python3 scripts/prepare-sidecar.py

step "4/4 打包 Tauri App"
(cd src-tauri && "$CARGO" tauri build --bundles app)

echo
echo "完成：App 产物见 src-tauri/target/release/bundle/macos/"
