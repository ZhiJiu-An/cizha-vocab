@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not defined DANCIJI_PORT set "DANCIJI_PORT=8000"
set "URL=http://127.0.0.1:%DANCIJI_PORT%"

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
backend\venv\Scripts\python.exe -c "import socket,sys; s=socket.socket(); s.settimeout(0.5); sys.exit(0 if s.connect_ex(('127.0.0.1',%DANCIJI_PORT%))==0 else 1)"
if not errorlevel 1 (
  echo 错误：端口 %DANCIJI_PORT% 已被占用，未启动。
  echo   可能已经有一个实例在运行：%URL%
  echo   换个端口：设置环境变量 DANCIJI_PORT=8001 后重试
  pause
  exit /b 1
)

if exist backend\.env (
  findstr /C:"sk-在这里填你的Key" backend\.env >nul 2>nul
  if not errorlevel 1 echo 提示：backend\.env 仍使用模板中的 API Key，词典可正常使用，但大模型翻译会失败。
)

echo ==^> 启动：%URL%
echo     关闭此窗口即可停止服务
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process '%URL%'"

cd backend
venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port %DANCIJI_PORT%
