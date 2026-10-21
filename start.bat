@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem 新名 CIZHA_PORT 为准，DANCIJI_PORT 保留一版兼容
if not defined CIZHA_PORT if defined DANCIJI_PORT set "CIZHA_PORT=%DANCIJI_PORT%"
if not defined CIZHA_PORT set "CIZHA_PORT=8000"
if not defined CIZHA_NO_OPEN if defined DANCIJI_NO_OPEN set "CIZHA_NO_OPEN=%DANCIJI_NO_OPEN%"
set "URL=http://127.0.0.1:%CIZHA_PORT%"

if not exist backend\venv\Scripts\python.exe (
  echo 尚未安装依赖，请先运行 setup.bat
  pause
  exit /b 1
)

if exist frontend\dist\index.html goto :check_port

if not exist frontend\node_modules (
  echo 错误：前端依赖未安装，请先运行 setup.bat
  pause
  exit /b 1
)

echo ==^> 前端尚未构建，正在构建……
pushd frontend
call npm run build
set "BUILD_RC=%errorlevel%"
popd
if not "%BUILD_RC%"=="0" (
  echo 错误：前端构建失败，请检查上面的输出。
  pause
  exit /b 1
)

:check_port
rem 端口占用检查：避免 uvicorn 报 address already in use 时浏览器已打开旧实例
backend\venv\Scripts\python.exe -c "import socket,sys; s=socket.socket(); s.settimeout(0.5); sys.exit(0 if s.connect_ex(('127.0.0.1',%CIZHA_PORT%))==0 else 1)"
if not errorlevel 1 (
  echo 错误：端口 %CIZHA_PORT% 已被占用，未启动。
  echo   可能已经有一个实例在运行：%URL%
  echo   换个端口：设置环境变量 CIZHA_PORT=8001 后重试
  pause
  exit /b 1
)

if exist backend\.env (
  findstr /C:"sk-在这里填你的Key" backend\.env >nul 2>nul
  if not errorlevel 1 echo 提示：backend\.env 仍使用模板中的 API Key，词典可正常使用，但大模型翻译会失败。
)

echo ==^> 启动：%URL%
echo     关闭此窗口即可停止服务
rem 与 start.sh 对齐：轮询 /api/health 就绪后再开浏览器（最多约 20 秒），
rem 避免固定睡眠导致首次迁移 / 大库时打开一个还连不上的页面。
if not "%CIZHA_NO_OPEN%"=="1" (
  start "" powershell -NoProfile -WindowStyle Hidden -Command "$ok=$false; for($i=0; $i -lt 40; $i++){ try { Invoke-WebRequest -UseBasicParsing -Uri '%URL%/api/health' -TimeoutSec 1 | Out-Null; $ok=$true; break } catch { Start-Sleep -Milliseconds 500 } }; if($ok){ Start-Process '%URL%' }"
)

cd backend
venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port %CIZHA_PORT%
