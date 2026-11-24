# -*- coding: utf-8 -*-
"""
运行期地名自扩展。

地名库收录了 250 国 + 375 座主要城市 + 31 个热点区，但世界新闻里仍会出现
库外的中小城市（如 Pokrovsk、Sumy）。这里在采集时对标题中「未知的大写专名」
做一次受限的地理编码尝试：

    严格门槛：命中类型必须是 PCLI/PPLC/PPLA，且人口 ≥ 10 万
    上限：每条新闻最多尝试 3 个候选
    缓存：解析结果落盘，第二次运行不再请求

这样地名库会随采集自动生长，且不会把噪声灌进来。
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
import time
from concurrent.futures import ThreadPoolExecutor

from .config import GEOCODE_CACHE_PATH, USER_AGENT
from .normalize import is_cjk

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

MIN_POPULATION = 100_000
OK_FEATURES = {"PCLI", "PPLC", "PPLA"}
MAX_CANDIDATES_PER_ITEM = 3

# 标题中常见的、不是地名的首字母大写词
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "for", "with", "after", "before",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    "president", "presidents", "prime", "minister", "ministers", "chancellor",
    "presidential", "government", "parliament", "senate", "congress",
    "minister", "ministry", "official", "officials", "spokesperson", "spokesman",
    "report", "reports", "reported", "says", "said", "say", "told", "tells",
    "news", "update", "updates", "breaking", "live", "world", "global",
    "police", "army", "navy", "air", "force", "forces", "troops", "soldiers",
    "what", "why", "how", "when", "where", "who", "which", "who's", "isn't",
    "i", "we", "they", "he", "she", "it", "this", "that", "these", "those",
    "video", "photos", "photo", "watch", "live", "exclusive", "analysis",
    "opinion", "editorial", "explainer", "feature", "special", "read", "more",
    "new", "now", "just", "still", "also", "after", "over", "under", "more",
    "former", "current", "next", "top", "best", "first", "last", "next",
    "us", "uk", "eu", "un", "nato", "gdp", "ceo", "cfo", "vo", "amid",
    "here", "there", "why", "how", "what", "who", "when", "where",
    "white", "black", "red", "green", "blue", "north", "south", "east", "west",
    "western", "eastern", "northern", "southern", "central", "middle",
    "russia", "ukraine", "israel", "gaza", "china", "japan", "india",
    "trump", "biden", "putin", "zelensky", "netanyahu", "xi", "modi",
    "reuters", "ap", "afp", "bloomberg",
}

# 单词首字母大写的连续片段 → 候选地名
_CAP_SEQ = re.compile(r"[A-Z][A-Za-z'’\-]+(?:\s+(?:of|the|de|al|and)\s+[A-Z][A-Za-z'’\-]+|\s+[A-Z][A-Za-z'’\-]+)*")


class Discoverer:
    def __init__(self, cache_path: str = GEOCODE_CACHE_PATH, log=print):
        self.log = log
        self.cache_path = cache_path
        self.cache: dict[str, dict | None] = {}
        if os.path.exists(cache_path):
            try:
                with open(cache_path, encoding="utf-8") as f:
                    self.cache = json.load(f)
            except Exception:  # noqa: BLE001
                self.cache = {}
        self.new_places: list[dict] = []
        self._known: set[str] = set()

    def set_known(self, names: set[str]):
        """告知已在地名库中的名称，避免重复解析。"""
        self._known = {n.lower() for n in names}

    # ------------------------------------------------------------------
    def candidates(self, title: str) -> list[str]:
        out: list[str] = []
        for m in _CAP_SEQ.finditer(title or ""):
            phrase = m.group(0).strip()
            if not phrase:
                continue
            # 去掉末尾的介词残留
            words = phrase.split()
            while words and words[-1].lower() in ("of", "the", "and", "in", "at", "on", "for", "to"):
                words.pop()
            if not words:
                continue
            phrase = " ".join(words)
            low = phrase.lower()
            if low in STOPWORDS or low in self._known:
                continue
            if all(w.lower() in STOPWORDS for w in words):
                continue
            if len(words) > 3:
                continue
            if phrase not in out:
                out.append(phrase)
            if len(out) >= MAX_CANDIDATES_PER_ITEM:
                break
        return out

    # ------------------------------------------------------------------
    def _geocode(self, name: str) -> dict | None:
        key = name.strip().lower()
        if key in self.cache:
            return self.cache[key]
        url = GEOCODE_URL + "?" + urllib.parse.urlencode(
            {"name": name, "count": 6, "language": "en", "format": "json"}
        )
        data = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=20) as r:
                    data = json.loads(r.read().decode("utf-8"))
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    self.log(f"    ~ 解析失败 {name!r}: {e}")
                else:
                    time.sleep(1.5 * (attempt + 1))
        if data is None:
            self.cache[key] = None
            return None

        best = None
        for x in data.get("results") or []:
            if x.get("feature_code") not in OK_FEATURES:
                continue
            if (x.get("population") or 0) < MIN_POPULATION:
                continue
            if best is None or (x.get("population") or 0) > (best.get("population") or 0):
                best = x
        if best is None:
            self.cache[key] = None
            return None

        hit = {
            "name": best.get("name", name),
            "zh": "",
            "lat": round(best["latitude"], 4),
            "lon": round(best["longitude"], 4),
            "cc": best.get("country_code", ""),
            "country": best.get("country", ""),
            "country_zh": "",
            "population": best.get("population"),
            "feature": best.get("feature_code", ""),
        }
        self.cache[key] = hit
        return hit

    # ------------------------------------------------------------------
    def resolve_many(self, names: list[str], workers: int = 6) -> dict[str, dict | None]:
        """并发解析一批地名，返回 {name_lower: hit}。"""
        todo = []
        seen = set()
        for n in names:
            k = n.strip().lower()
            if k in seen:
                continue
            seen.add(k)
            if k in self.cache:
                continue
            todo.append(n)
        if todo:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                list(ex.map(self._geocode, todo))
        return {n.strip().lower(): self.cache.get(n.strip().lower()) for n in names}

    # ------------------------------------------------------------------
    def discover(self, title: str, hits: dict[str, dict | None] | None = None) -> list[dict]:
        """返回本条新闻新发现的地名（可能为空）。"""
        found = []
        for cand in self.candidates(title):
            key = cand.strip().lower()
            if hits is not None and key in hits:
                hit = hits[key]
            else:
                hit = self._geocode(cand)
            if not hit:
                continue
            rec = dict(hit)
            rec["matched_name"] = cand
            found.append(rec)
            self.new_places.append(rec)
            self._known.add(cand.lower())
            self._known.add(rec["name"].lower())
        return found

    # ------------------------------------------------------------------
    def save(self):
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=0)
