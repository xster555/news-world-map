#!/usr/bin/env bash
# 只启动本地服务（不采集）
set -euo pipefail
cd "$(dirname "$0")"

PY_BIN=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then PY_BIN="$c"; break; fi
done
if [ -z "$PY_BIN" ]; then
  echo "✗ 没找到 python。请先安装 Python 3.8+（https://www.python.org/downloads/）" >&2
  exit 1
fi

PORT="${PORT:-8000}"

# 仓库不含新闻数据：还没采集过就直接开服务，页面会是空的
if [ ! -f web/data/news-data.js ]; then
  echo "⚠ 还没有发布过数据快照（仓库不含新闻数据）。"
  echo "  先跑一次采集：./daily.sh"
  echo "  或：python3 -m collector.collect && python3 scripts/publish.py"
  echo ""
fi

echo "▶ http://127.0.0.1:${PORT}/"
exec "$PY_BIN" -m http.server "$PORT" --directory web
