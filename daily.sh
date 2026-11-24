#!/usr/bin/env bash
# 每日采集（可交给系统 crontab：0 7 * * * /path/to/daily.sh）
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

"$PY_BIN" -m collector.collect
"$PY_BIN" scripts/publish.py
