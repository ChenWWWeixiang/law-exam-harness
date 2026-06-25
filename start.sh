#!/usr/bin/env bash
# 法考 AI 学习 Harness - Mac/Linux 启动脚本
set -e

cd "$(dirname "$0")"

PYTHON=${PYTHON:-python3}
PORT=${PORT:-5057}
HOST=${HOST:-127.0.0.1}

echo "[1/3] 检查 Python 依赖..."
if ! $PYTHON -c "import flask, requests" 2>/dev/null; then
  echo "  缺少依赖,正在安装..."
  $PYTHON -m pip install -r requirements.txt
fi

if [ ! -f config.json ]; then
  echo "[2/3] 初始化 config.json (从模板复制)"
  cp config.example.json config.json
  echo "  请编辑 config.json 填入 API Key 后再访问 Web UI"
fi

echo "[3/3] 启动本地 server..."
echo "  访问 http://$HOST:$PORT"
exec $PYTHON -m server.server