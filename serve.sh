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
echo "▶ http://127.0.0.1:${PORT}/"
exec "$PY_BIN" -m http.server "$PORT" --directory web
