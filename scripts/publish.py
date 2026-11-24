# -*- coding: utf-8 -*-
"""发布数据快照：data/news.json → web/data/

这是「新闻获取」（collector/）与「地图」（web/）两个模块之间的桥，
**不属于任何一方**：它同时知道 data/ 和 web/data/，
而采集核心（feeds / geocode / gazetteer / collect）完全不知道前端的存在。

    python3 scripts/publish.py [--window-days 30] [--max-bytes 3145728]

流程：
  1. 读 data/news.json（模块 A 的唯一真相）
  2. 按 contract/news-v1.json 校验（契约层，两侧共享）
  3. 不通过 → 打印错误列表、退出码非 0、**一个字节都不写**
     （旧的发布产物原样保留，网页继续显示上一次的好数据）
  4. 通过 → 裁掉采集器内部字段、限制发布窗口，再校验一次
  5. 原子写出 web/data/ 下的三个文件，打印摘要

发布时做两件「减负」的事：

  A. 裁掉内部字段——契约 internal_fields 里列的那些（tkey / ukey / fallback /
     section / source_id）是采集器的去重键与实现细节，地图端根本读不到。
     裁掉之后发布产物与契约逐字一致：「前端不得依赖」从一句约定，
     变成数据层面的硬边界。

  B. 限制发布窗口（默认 30 天）——采集器本机保留完整档案（90 天 / 4000 条上限），
     页面只拿最近的一段。档案涨到上限时，页面载荷不会跟着线性膨胀。
     实际生效的天数写进产物的 window_days 字段，页面据此如实告知用户。

产物：
    web/data/news.json      机器可读快照
    web/data/news-data.js   页面用（<script> 注入 window.__NEWS__，file:// 也能读）
    web/data/contract.js    随快照一同发布的契约（window.__NWM_CONTRACT__）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from collector.contract import load_spec, validate  # noqa: E402

DATA_JSON = os.path.join(ROOT, "data", "news.json")
WEB_DATA_DIR = os.path.join(ROOT, "web", "data")
OUT_JSON = os.path.join(WEB_DATA_DIR, "news.json")
OUT_JS = os.path.join(WEB_DATA_DIR, "news-data.js")
OUT_CONTRACT = os.path.join(WEB_DATA_DIR, "contract.js")

BANNER = "/* 自动生成，勿手改；由 python3 scripts/publish.py 写出 */\n"

# 发布窗口（天）：0 表示不限。页面只拿这一段，完整档案留在本机 data/news.json。
PUBLISH_WINDOW_DAYS = 30
# 发布产物的体积上限（字节）。超了就自动收紧窗口，保证浏览器不会被拖垮。
PUBLISH_MAX_BYTES = 3 * 1024 * 1024


def log(*a):
    print(*a, flush=True)


def write_atomic(path, text):
    """先写临时文件再替换，避免写到一半被读到半个文件。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def dumps(payload):
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def prune_items(items, internal_fields):
    """去掉采集器内部字段——地图端用不到，也不该看到。"""
    if not internal_fields:
        return items, 0
    keys = set(internal_fields)
    out = []
    removed = 0
    for it in items:
        kept = {}
        for k, v in it.items():
            if k in keys:
                removed += 1
            else:
                kept[k] = v
        out.append(kept)
    return out, removed


def window_items(items, days, now=None):
    """只保留最近 days 天的条目。

    published_at 是 ISO-8601（末尾 Z），字典序即时间序，可直接比字符串。
    """
    if not days or days <= 0:
        return items, 0
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    kept = [it for it in items if (it.get("published_at") or "") >= cutoff]
    return kept, len(items) - len(kept)


def build_payload(raw, items, window_days):
    """组装发布载荷。count 始终等于实际条数（发布器的额外不变量）。"""
    payload = {
        "generated_at": raw.get("generated_at"),
        "count": len(items),
        "sources": raw.get("sources") or [],
        "items": items,
        "window_days": window_days,
    }
    return payload


def parse_args(argv):
    ap = argparse.ArgumentParser(
        description="发布数据快照到 web/data/（先按契约校验，校验不过一个字节都不写）")
    ap.add_argument("--window-days", type=int, default=PUBLISH_WINDOW_DAYS,
                    help="发布最近多少天的新闻；0 = 不限（默认 %d）" % PUBLISH_WINDOW_DAYS)
    ap.add_argument("--max-bytes", type=int, default=PUBLISH_MAX_BYTES,
                    help="发布产物的体积上限（字节）；超了自动收紧窗口（默认 %d）" % PUBLISH_MAX_BYTES)
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if not os.path.exists(DATA_JSON):
        log("! 找不到 data/news.json —— 请先运行 python3 -m collector.collect")
        return 1

    with open(DATA_JSON, encoding="utf-8") as f:
        raw = json.load(f)

    spec = load_spec()

    # ---- 第一道校验：原始档案（采集器的产出）必须符合契约 ----
    errors = validate(raw, spec)
    raw_items = raw.get("items") or []
    if raw.get("count") != len(raw_items):
        errors.append("count: 声明 %r，实际 %d 条" % (raw.get("count"), len(raw_items)))
    if errors:
        log("! 契约校验未通过，共 %d 处问题；未发布任何文件" % len(errors))
        log("  契约版本：%s" % spec.get("version", "?"))
        for line in errors[:20]:
            log("    - %s" % line)
        if len(errors) > 20:
            log("    ... 另有 %d 处未列出" % (len(errors) - 20))
        log("  web/data/ 保持上一次发布的版本不变")
        return 1

    # ---- 减负 A：裁掉内部字段 ----
    internal = list(spec.get("internal_fields") or {})
    pruned, removed = prune_items(raw_items, internal)

    # ---- 减负 B：限制发布窗口 ----
    window_days = max(0, args.window_days)
    kept, dropped = window_items(pruned, window_days)
    published = build_payload(raw, kept, window_days)

    # 体积超限就逐步收紧窗口（1 天是下限）
    shrunk = False
    while window_days > 1 and len(dumps(published).encode("utf-8")) > args.max_bytes:
        window_days -= 1
        kept, dropped = window_items(pruned, window_days)
        published = build_payload(raw, kept, window_days)
        shrunk = True

    size = len(dumps(published).encode("utf-8"))
    if size > args.max_bytes:
        log("! 警告：即使只发布 1 天，产物仍有 %.1f MB（上限 %.1f MB），已按原样发布"
            % (size / 1024.0 / 1024.0, args.max_bytes / 1024.0 / 1024.0))

    # ---- 第二道校验：裁剪后的发布载荷同样必须符合契约 ----
    errors = validate(published, spec)
    if published.get("count") != len(published.get("items") or []):
        errors.append("count: 声明 %r，实际 %d 条"
                      % (published.get("count"), len(published.get("items") or [])))
    if errors:
        log("! 发布载荷未通过契约校验，共 %d 处问题；未发布任何文件" % len(errors))
        for line in errors[:20]:
            log("    - %s" % line)
        log("  web/data/ 保持上一次发布的版本不变")
        return 1

    os.makedirs(WEB_DATA_DIR, exist_ok=True)
    write_atomic(OUT_JSON, dumps(published))
    write_atomic(OUT_JS, BANNER + "window.__NEWS__ = " + dumps(published) + ";\n")
    write_atomic(OUT_CONTRACT, BANNER + "window.__NWM_CONTRACT__ = " + dumps(spec) + ";\n")

    ok_sources = sum(1 for s in published.get("sources") or [] if s.get("ok"))
    log("✓ 已发布 %d 条 / %d 个来源（契约 %s）" % (
        len(published["items"]), ok_sources, spec.get("version", "?")))
    log("  发布窗口：最近 %s 天%s" % (
        window_days if window_days else "不限",
        "（体积超限，已自动收紧）" if shrunk else ""))
    if dropped:
        log("  窗口外未发布：%d 条（本机档案保留完整数据）" % dropped)
    if removed:
        log("  已裁掉采集器内部字段：%d 个（%s）" % (removed, "、".join(internal)))
    log("  产物大小：%.1f KB" % (size / 1024.0))
    log("  → web/data/news.json")
    log("  → web/data/news-data.js")
    log("  → web/data/contract.js")
    return 0


if __name__ == "__main__":
    sys.exit(main())
