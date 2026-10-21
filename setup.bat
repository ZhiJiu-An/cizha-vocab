@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem 下载源：可用环境变量覆盖（pip 与 npm 原生支持这两个变量）
if not defined PIP_INDEX_URL set "PIP_INDEX_URL=https://pypi.org/simple"
if not defined npm_config_registry set "npm_config_registry=https://registry.npmjs.org"

echo ==^> 检查环境

where python >nul 2>nul
if errorlevel 1 (
  where py >nul 2>nul
  if errorlevel 1 goto :no_python
  set "PY=py -3"
) else (
  set "PY=python"
)

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 goto :bad_python

where node >nul 2>nul
if errorlevel 1 goto :no_node
node -e "const [a,b]=process.versions.node.split('.').map(Number);const ok=(a===20&&b>=19)||(a>=22&&(a>22||b>=12));process.exit(ok?0:1)"
if errorlevel 1 goto :bad_node

echo ==^> 创建 Python 虚拟环境 backend\venv
if not exist backend\venv\Scripts\python.exe (
  %PY% -m venv backend\venv
  if errorlevel 1 goto :error
)

echo ==^> 安装后端依赖（索引：%PIP_INDEX_URL%）
backend\venv\Scripts\python.exe -m pip install --upgrade pip -q
if errorlevel 1 goto :network
backend\venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if errorlevel 1 goto :network

echo ==^> 安装并构建前端（registry：%npm_config_registry%）
pushd frontend
if exist package-lock.json (
  call npm ci --no-audit --no-fund
) else (
  call npm install --no-audit --no-fund
)
if errorlevel 1 (
  popd
  goto :network
)
call npm run build
if errorlevel 1 (
  popd
  echo 错误：前端构建失败，请检查上面的输出。
  goto :error
)
popd

if not exist backend\.env (
  copy /Y backend\.env.example backend\.env >nul
  echo.
  echo 已生成 backend\.env，请填写 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
)

echo.
echo 安装完成。下一步：
echo   1. 编辑 backend\.env 填入模型配置（图片取词还需配置视觉模型）
echo   2. 双击 start.bat 启动，浏览器访问 http://127.0.0.1:8000
pause
exit /b 0

:network
echo.
echo 安装失败。若上面的报错是 "Could not find a version that satisfies ..." 或各种超时，
echo 通常是下载源不通或过慢（不是依赖写错）。国内网络可在运行前设置镜像：
echo.
echo   set PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
echo   set npm_config_registry=https://registry.npmmirror.com
echo   setup.bat
goto :error

:no_python
echo 错误：未找到 Python，请先安装 Python 3.10+ 并勾选 Add to PATH
goto :error
:bad_python
echo 错误：Python 版本过低，需要 3.10 及以上
goto :error
:no_node
echo 错误：未找到 Node.js，请先安装 Node.js 20.19+ 或 22.12+
goto :error
:bad_node
echo 错误：Node 版本过低，Vite 8 需要 20.19+ 或 22.12+
goto :error
:error
echo.
echo 安装未完成，请根据上面的提示处理后重试。
pause
exit /b 1
