# -*- coding: utf-8 -*-
"""
新闻世界地图 · 采集主流程

    python3 -m collector.collect

做四件事：
    1. 抓取全部 RSS 源
    2. 把每条新闻定位到地图坐标（地名库匹配 + 运行期自扩展）
    3. 与历史数据去重合并（累加，不覆盖）
    4. 写出 data/news.json 与 data/news-data.js
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

from . import config as C
from .feeds import fetch_all
from .gazetteer import Gazetteer
from .geocode import Discoverer
from .normalize import title_key, truncate, url_key

MAX_ITEMS = 4000


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def setup_console():
    """
    Windows 中文控制台默认 GBK，个别符号（如 ✓）会导致 UnicodeEncodeError 直接崩溃。
    这里保留控制台原生编码（中文能正常显示），但把无法编码的字符降级为 '?' 而不是抛异常。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding=stream.encoding or "utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
def confidence_label(score: float) -> str:
    if score >= 0.90:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"


def load_existing() -> list[dict]:
    if not os.path.exists(C.NEWS_JSON_PATH):
        return []
    try:
        with open(C.NEWS_JSON_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("items", []) or []
    except Exception as e:  # noqa: BLE001
        log(f"    ! 读取历史数据失败（将重新开始）: {e}")
        return []


def save_dataset(items: list[dict], source_status: list[dict]):
    items = sorted(items, key=lambda x: x.get("published_at", ""), reverse=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(items),
        "sources": source_status,
        "items": items,
    }
    with open(C.NEWS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    # 同时输出一份 JS 版本，让页面用 file:// 直接打开也能读到数据
    os.makedirs(C.WEB_DATA_DIR, exist_ok=True)
    for js_path, json_path in ((C.NEWS_JS_PATH, C.NEWS_JSON_PATH),
                               (C.WEB_NEWS_JS_PATH, C.WEB_NEWS_JSON_PATH)):
        with open(js_path, "w", encoding="utf-8") as f:
            f.write("/* 自动生成，勿手改；由 python3 -m collector.collect 写出 */\n")
            f.write("window.__NEWS__ = ")
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
            f.write(";\n")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    return payload


def write_discovered(gaz: Gazetteer, new_places: list[dict]) -> int:
    """把新发现的地名写回地名库，供下次采集使用。"""
    if not new_places:
        return 0
    path = C.GAZETTEER_PATH
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    existing = raw.get("discovered", [])
    seen = {(e["name"], e["lat"], e["lon"]) for e in existing}
    added = 0
    for p in new_places:
        key = (p["name"], p["lat"], p["lon"])
        if key in seen:
            continue
        seen.add(key)
        existing.append({
            "name": p["name"], "zh": p.get("zh", ""),
            "lat": p["lat"], "lon": p["lon"], "cc": p.get("cc", ""),
            "country": p.get("country", ""), "country_zh": p.get("country_zh", ""),
            "population": p.get("population"),
        })
        added += 1
    if added:
        raw["discovered"] = existing
        with open(path, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, separators=(",", ":"))
    return added


# ---------------------------------------------------------------------------
def locate(gaz: Gazetteer, item: dict) -> dict:
    """为一条新闻确定落点。返回 {location, confidence, places, located}"""
    hits = gaz.match(item["title"], item["summary"])

    # 候选落点：文本命中 + 来源国/区域兜底，取分高者。
    # 注意：不能因为文本命中分低就丢弃它——描述里明确点名的国家（0.50）
    # 远比「来自 NPR，所以在美国」（0.30）更可信。
    best = hits[0] if hits else None
    best_score = best["score"] if best else 0.0

    cc = gaz.source_country.get(item["feed_id"], "")
    fallback = gaz.country_placeholder(cc) if cc else None
    if fallback is None:
        region = gaz.feed_region.get(item["feed_id"], "")
        fallback = gaz.region_placeholder(region) if region else None

    if best is None and fallback is None:
        return {"location": None, "confidence": 0.0, "places": [], "located": False}

    if best is not None and (fallback is None or best_score >= 0.30):
        place = best["place"]
        location = {
            "kind": place.kind,
            "name": place.name,
            "zh": place.zh or place.name,
            "lat": place.lat,
            "lon": place.lon,
            "cc": place.cc,
            "country": place.country,
            "country_zh": place.country_zh,
            "matched_alias": best["alias"],
        }
        places = []
        for h in hits[:6]:
            places.append({
                "kind": h["place"].kind,
                "name": h["place"].name,
                "zh": h["place"].zh or h["place"].name,
                "lat": h["place"].lat,
                "lon": h["place"].lon,
                "cc": h["place"].cc,
                "country": h["place"].country,
                "country_zh": h["place"].country_zh,
                "matched_alias": h["alias"],
                "score": round(h["score"], 3),
            })
        return {
            "location": location,
            "confidence": round(best_score, 3),
            "places": places,
            "located": True,
            "fallback": False,
        }

    # 兜底：来源国 / 区域
    return {
        "location": fallback,
        "confidence": 0.30 if fallback.get("cc") else 0.25,
        "places": [fallback],
        "located": True,
        "fallback": True,
    }


def build_record(gaz: Gazetteer, item: dict, loc: dict) -> dict:
    pub = item["published_at"].astimezone(timezone.utc)
    return {
        "id": title_key(item["title"]),
        "title": item["title"],
        "summary": truncate(item["summary"], 280),
        "url": item["url"],
        "source": item["source"],
        "source_id": item["feed_id"],
        "section": item.get("section", ""),
        "published_at": pub.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "image": item.get("image", ""),
        "lat": loc["location"]["lat"] if loc["location"] else None,
        "lon": loc["location"]["lon"] if loc["location"] else None,
        "location": loc["location"],
        "places": loc["places"],
        "confidence": loc["confidence"],
        "confidence_label": confidence_label(loc["confidence"]),
        "located": loc["located"],
        "fallback": loc.get("fallback", False),
        "tkey": title_key(item["title"]),
        "ukey": url_key(item["url"]),
    }


# ---------------------------------------------------------------------------
def main():
    setup_console()
    t0 = time.time()
    log("=" * 62)
    log("新闻世界地图 · 采集")
    log("=" * 62)

    if not os.path.exists(C.GAZETTEER_PATH):
        log(f"! 找不到地名库 {C.GAZETTEER_PATH}，请先运行 python3 build_gazetteer.py")
        return 1

    gaz = Gazetteer(C.GAZETTEER_PATH)
    log(f"[1/5] 地名库就绪：{len(gaz.places)} 条地点 / {len(gaz.alias_map)} 个别名")

    existing = load_existing()
    seen_t = {i.get("tkey") or i.get("id") for i in existing}
    seen_u = {i.get("ukey") for i in existing if i.get("ukey")}
    log(f"[2/5] 历史数据：{len(existing)} 条")

    log(f"[3/5] 抓取 {len(C.FEEDS)} 个源 ...")
    items, status = fetch_all(C.FEEDS, log=log)
    log(f"      抓取完成，共 {len(items)} 条")

    # --- 第一轮定位 ---
    records = []
    for it in items:
        loc = locate(gaz, it)
        records.append((it, loc))

    # --- 对定位不明确的条目尝试自扩展地名 ---
    disc = Discoverer(C.GEOCODE_CACHE_PATH, log=log)
    disc.set_known({p.name for p in gaz.places} | {a for p in gaz.places for a in p.aliases})
    weak = [(it, loc) for it, loc in records if loc["confidence"] < 0.45 and loc["located"]]
    weak = weak[:C.DISCOVERY_MAX_ITEMS]
    log(f"[4/5] {len(weak)} 条定位不明确，尝试扩展地名库 ...")

    # 先把所有候选地名收集起来，一次性并发解析（比逐条解析快得多）
    cand_names: list[str] = []
    seen_cand = set()
    for it, _ in weak:
        for c in disc.candidates(it["title"]):
            if c.lower() not in seen_cand:
                seen_cand.add(c.lower())
                cand_names.append(c)
    if cand_names:
        log(f"      待解析地名 {len(cand_names)} 个，并发请求中 ...")
    hits = disc.resolve_many(cand_names)

    improved = []
    for it, loc in weak:
        found = disc.discover(it["title"], hits)
        if found:
            improved.append((it, loc, found))
    disc.save()

    if disc.new_places:
        added = write_discovered(gaz, disc.new_places)
        log(f"      新发现 {len(disc.new_places)} 个地名，写入地名库 {added} 个")
        if added:
            gaz = Gazetteer(C.GAZETTEER_PATH)
            for it, loc, found in improved:
                new_loc = locate(gaz, it)
                if new_loc["confidence"] > loc["confidence"]:
                    loc = new_loc
                records = [(i, l) for (i, l) in records if i is not it]
                records.append((it, loc))
    else:
        log("      没有新地名")

    # --- 去重合并 ---
    new_records = []
    dup = 0
    for it, loc in records:
        rec = build_record(gaz, it, loc)
        if rec["tkey"] in seen_t or (rec["ukey"] and rec["ukey"] in seen_u):
            dup += 1
            continue
        seen_t.add(rec["tkey"])
        if rec["ukey"]:
            seen_u.add(rec["ukey"])
        new_records.append(rec)

    merged = existing + new_records

    # --- 按时间保留窗口裁剪 ---
    cutoff = (datetime.now(timezone.utc) - timedelta(days=C.RETENTION_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    merged = [r for r in merged if r.get("published_at", "") >= cutoff]
    merged.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    trimmed = 0
    if len(merged) > MAX_ITEMS:
        trimmed = len(merged) - MAX_ITEMS
        merged = merged[:MAX_ITEMS]

    payload = save_dataset(merged, status)
    log(f"[5/5] 写入完成：新 {len(new_records)} 条 / 重复 {dup} 条 / "
        f"超出上限裁掉 {trimmed} 条 / 累计 {payload['count']} 条")
    log(f"      耗时 {time.time() - t0:.1f}s")

    # 简单统计
    located = sum(1 for r in merged if r.get("located"))
    high = sum(1 for r in merged if r.get("confidence_label") == "high")
    log(f"      已定位 {located} 条（其中城市级 {high} 条），未定位 {len(merged) - located} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
