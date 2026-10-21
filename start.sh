#!/usr/bin/env bash
# 一键启动：后端托管构建后的前端，单端口
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# 端口与自动开浏览器：新名 CIZHA_* 为准，DANCIJI_* 保留一版兼容
PORT="${CIZHA_PORT:-${DANCIJI_PORT:-8000}}"
URL="http://127.0.0.1:${PORT}"
PY="$ROOT/backend/venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "尚未安装依赖，请先运行 ./setup.sh" >&2
  exit 1
fi

if [ ! -f frontend/dist/index.html ]; then
  if [ ! -d frontend/node_modules ]; then
    echo "错误：前端依赖未安装，请先运行 ./setup.sh" >&2
    exit 1
  fi
  echo "==> 前端尚未构建，正在构建……"
  (cd frontend && npm run build) || {
    echo "错误：前端构建失败，请检查上面的输出。" >&2
    exit 1
  }
fi

# 端口占用检查：与其让 uvicorn 打印「启动」后再报 address already in use
# （此时浏览器已自动打开，用户看到的是旧实例，误以为启动成功），不如提前拦住。
if (exec 3<>"/dev/tcp/127.0.0.1/${PORT}") 2>/dev/null; then
  echo "错误：端口 ${PORT} 已被占用，未启动。" >&2
  echo "  可能已经有一个实例在运行：${URL}" >&2
  echo "  换个端口：CIZHA_PORT=8001 ./start.sh" >&2
  exit 1
fi

if [ -f backend/.env ] && grep -q "sk-在这里填你的Key" backend/.env; then
  echo "提示：backend/.env 仍使用模板中的 API Key，词典可正常使用，但大模型翻译会失败。"
fi

# 等后端真的能响应再开浏览器（最多 20 秒），避免打开一个还连不上的页面。
open_when_ready() {
  local i
  for i in $(seq 1 40); do
    if "$PY" -c 'import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=1)' \
        "${URL}/api/health" >/dev/null 2>&1; then
      if command -v open >/dev/null 2>&1; then
        open "$URL"
      elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$URL" >/dev/null 2>&1
      fi
      return 0
    fi
    sleep 0.5
  done
  echo "提示：服务未在 20 秒内就绪，请检查上面的日志。" >&2
}

if [ "${CIZHA_NO_OPEN:-${DANCIJI_NO_OPEN:-}}" != "1" ]; then
  open_when_ready &
fi

echo "==> 启动：$URL"
echo "    按 Ctrl+C 停止"

cd backend
exec venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
