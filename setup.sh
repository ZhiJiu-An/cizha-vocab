#!/usr/bin/env bash
# 一次性安装依赖：创建 venv、安装后端依赖、安装并构建前端
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

fail() {
  echo "错误：$1" >&2
  exit 1
}

# 下载源：可直接用环境变量覆盖（pip 与 npm 原生支持这两个变量），
# 国内网络建议换成镜像，见 README「国内网络」一节。
PIP_INDEX="${PIP_INDEX_URL:-https://pypi.org/simple}"
NPM_REGISTRY="${npm_config_registry:-https://registry.npmjs.org}"

# 依赖下载失败时给人话提示。
# pip 在索引请求超时后会报 "Could not find a version that satisfies ..."，
# 看起来像依赖名写错，实际是网络问题 —— 不点破会让用户白排查很久。
network_hint() {
  cat >&2 <<EOF

安装失败。若上面的报错是 "Could not find a version that satisfies ..." 或各种超时，
通常是下载源不通或过慢（**不是依赖写错**）。国内网络请改用镜像后重试：

  PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \\
  npm_config_registry=https://registry.npmmirror.com \\
  ./setup.sh
EOF
}

echo "==> 检查环境"
command -v python3 >/dev/null 2>&1 || fail "未找到 python3，请先安装 Python 3.10+"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || fail "Python 版本过低，需要 3.10 及以上"

command -v node >/dev/null 2>&1 || fail "未找到 node，请先安装 Node.js 20.19+ 或 22.12+"
command -v npm >/dev/null 2>&1 || fail "未找到 npm，请先安装 Node.js"
node -e 'const [a,b]=process.versions.node.split(".").map(Number); const ok=(a===20&&b>=19)||(a>=22&&(a>22||b>=12)); process.exit(ok?0:1)' \
  || fail "Node 版本过低，Vite 8 需要 20.19+ 或 22.12+"

echo "==> 创建 Python 虚拟环境 backend/venv"
python3 -m venv backend/venv

echo "==> 安装后端依赖（索引：${PIP_INDEX}）"
backend/venv/bin/python -m pip install --upgrade pip -q || { network_hint; exit 1; }
backend/venv/bin/python -m pip install -r backend/requirements.txt || { network_hint; exit 1; }

echo "==> 安装并构建前端（registry：${NPM_REGISTRY}）"
(
  cd frontend
  if [ -f package-lock.json ]; then
    # 用 ci 而不是 install：严格按 lock 安装，可复现；lock 与 package.json 不一致时立即报错
    npm ci --no-audit --no-fund || { network_hint; exit 1; }
  else
    npm install --no-audit --no-fund || { network_hint; exit 1; }
  fi
  npm run build || { echo "错误：前端构建失败，请检查上面的输出。" >&2; exit 1; }
)

if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  echo
  echo "已生成 backend/.env，请填写 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL"
fi

echo
echo "安装完成。下一步："
echo "  1. 编辑 backend/.env 填入模型配置（图片取词还需配置视觉模型）"
echo "  2. 运行 ./start.sh 启动，浏览器访问 http://127.0.0.1:8000"
