# -*- coding: utf-8 -*-
"""发布数据快照：data/news.json → web/data/

这是「新闻获取」（collector/）与「地图」（web/）两个模块之间的桥，
**不属于任何一方**：它同时知道 data/ 和 web/data/，
而采集核心（feeds / geocode / gazetteer / collect）完全不知道前端的存在。

    python3 scripts/publish.py

流程：
  1. 读 data/news.json（模块 A 的唯一真相）
  2. 按 contract/news-v1.json 校验（契约层，两侧共享）
  3. 不通过 → 打印错误列表、退出码非 0、**一个字节都不写**
     （旧的发布产物原样保留，网页继续显示上一次的好数据）
  4. 通过 → 原子写出 web/data/ 下的三个文件
  5. 打印摘要

产物：
    web/data/news.json      机器可读快照
    web/data/news-data.js   页面用（<script> 注入 window.__NEWS__，file:// 也能读）
    web/data/contract.js    随快照一同发布的契约（window.__NWM_CONTRACT__）
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from collector.contract import load_spec, validate  # noqa: E402

DATA_JSON = os.path.join(ROOT, "data", "news.json")
WEB_DATA_DIR = os.path.join(ROOT, "web", "data")
OUT_JSON = os.path.join(WEB_DATA_DIR, "news.json")
OUT_JS = os.path.join(WEB_DATA_DIR, "news-data.js")
OUT_CONTRACT = os.path.join(WEB_DATA_DIR, "contract.js")

BANNER = "/* 自动生成，勿手改；由 python3 scripts/publish.py 写出 */\n"


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


def main():
    if not os.path.exists(DATA_JSON):
        log("! 找不到 data/news.json —— 请先运行 python3 -m collector.collect")
        return 1

    with open(DATA_JSON, encoding="utf-8") as f:
        payload = json.load(f)

    spec = load_spec()

    errors = validate(payload, spec)

    # 发布器额外的不变量：count 必须与实际条数一致
    items = payload.get("items") or []
    if payload.get("count") != len(items):
        errors.append("count: 声明 %r，实际 %d 条" % (payload.get("count"), len(items)))

    if errors:
        log("! 契约校验未通过，共 %d 处问题；未发布任何文件" % len(errors))
        log("  契约版本：%s" % spec.get("version", "?"))
        for line in errors[:20]:
            log("    - %s" % line)
        if len(errors) > 20:
            log("    ... 另有 %d 处未列出" % (len(errors) - 20))
        log("  web/data/ 保持上一次发布的版本不变")
        return 1

    os.makedirs(WEB_DATA_DIR, exist_ok=True)
    write_atomic(OUT_JSON, dumps(payload))
    write_atomic(OUT_JS, BANNER + "window.__NEWS__ = " + dumps(payload) + ";\n")
    write_atomic(OUT_CONTRACT, BANNER + "window.__NWM_CONTRACT__ = " + dumps(spec) + ";\n")

    ok_sources = sum(1 for s in payload.get("sources") or [] if s.get("ok"))
    log("✓ 已发布 %d 条 / %d 个来源（契约 %s）" % (
        len(items), ok_sources, spec.get("version", "?")))
    log("  → web/data/news.json")
    log("  → web/data/news-data.js")
    log("  → web/data/contract.js")
    return 0


if __name__ == "__main__":
    sys.exit(main())
