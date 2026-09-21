#!/usr/bin/env bash
# ============================================================================
# 启动 chan.py 后端 FastAPI 服务
#
# 用法:
#   ./start_backend.sh                       # 默认 0.0.0.0:8000
#   PORT=9000 ./start_backend.sh             # 指定端口
#   PG_DSN="host=... dbname=... user=... password=..." ./start_backend.sh  # 覆盖默认连接
#   ./start_backend.sh --reload              # 开发热重载（透传 uvicorn 参数）
#
# 说明:
#   - 必须在项目根目录运行（脚本已自动 cd 到自身所在目录）
#   - /api/health、/api/klines 无需 PG，可直接用（K线数据走 DuckDB）
#   - PG_DSN 默认: host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres
#   - /api/auth/* 及 stocks/watchlist/monitor 等业务路由需要 PG_DSN
# ============================================================================

set -euo pipefail

# 定位项目根目录（本脚本位于 Script/ 下，上一级即项目根目录），并切换到该目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

PY=".venv/bin/python"
PIP=".venv/bin/pip"

# 依赖自检：缺少 fastapi / uvicorn 时自动补齐
if ! "$PY" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
    echo "[start_backend] 缺少 fastapi/uvicorn，正在安装..."
    "$PIP" install -q fastapi uvicorn
fi

# 确保项目根目录在导入路径中（from ChanAnalyse.Common.CEnum / ChanAnalyse.Chan / ChanAnalyse.DataAPI ...）
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

# PostgreSQL 连接（默认本地 chan 库；可用 PG_DSN 环境变量覆盖）
PG_DSN="${PG_DSN:-host=127.0.0.1 port=5432 dbname=chan user=postgres password=postgres}"
export PG_DSN

echo "[start_backend] 启动 FastAPI 服务: http://${HOST}:${PORT}"
exec "$PY" -m uvicorn WebAPI.main:app --host "$HOST" --port "$PORT" "$@"
