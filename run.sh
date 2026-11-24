#!/usr/bin/env bash
# 新闻世界地图 —— 一键运行：采集最新新闻 → 启动本地服务
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

# 先起服务：页面立刻可用（包内已带一份已采集的数据）
# 再在后台采集，采完写回 data/，页面会自动检测并刷新
LOG="$PWD/collect.log"
echo "▶ 启动本地服务：http://127.0.0.1:${PORT}/"
echo "▶ 同时在后台采集最新新闻（日志：collect.log）"
echo "  按 Ctrl+C 停止"
echo ""

"$PY_BIN" -m http.server "$PORT" --directory web &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null' EXIT INT TERM

"$PY_BIN" -m collector.collect > "$LOG" 2>&1 &
echo "   （采集完成前，页面展示的是包内自带的数据；完成后会自动刷新）"
wait $SERVER_PID
