@echo off
REM 法考 AI 学习 Harness - Windows 启动脚本
setlocal

cd /d "%~dp0"

set PYTHON=python
set PORT=5057
set HOST=127.0.0.1

echo [1/3] 检查 Python 依赖...
%PYTHON% -c "import flask, requests" 2>nul
if errorlevel 1 (
  echo   缺少依赖,正在安装...
  %PYTHON% -m pip install -r requirements.txt
)

if not exist config.json (
  echo [2/3] 初始化 config.json (从模板复制)
  copy config.example.json config.json
  echo   请编辑 config.json 填入 API Key 后再访问 Web UI
)

echo [3/3] 启动本地 server...
echo   访问 http://%HOST%:%PORT%
%PYTHON% -m server.server