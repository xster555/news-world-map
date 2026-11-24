# -*- coding: utf-8 -*-
"""
地名匹配引擎。

RSS 里没有任何地理字段（已逐源核实），因此定位完全靠文本分析：
把标题/摘要里的地名与 gazetteer.json 中的地名库比对，按「具体程度 × 出现位置」打分，
取最高分作为该条新闻的落点，并把所有命中地点一并记录，便于前端展示。

打分基准：
    城市/首都/热点区 出现在标题 → 1.00        出现在摘要 → 0.78
    国家              出现在标题 → 0.70        出现在摘要 → 0.50
    美国州            出现在标题 → 0.62        出现在摘要 → 0.42
    运行期新发现地名  出现在标题 → 0.55        出现在摘要 → 0.40

三条防误判规则：
  1. 拉丁文地名必须以大写出现（否则 "nice day" 会被当成尼西亚），中文不适用。
  2. 短别名（US / UK / UAE…）必须全大写出现，避免命中英文代词。
  3. 「土耳其/约旦/乍得/几内亚…」这类本身是常用词的国家名，
     需要方位介词（in/at/from…）佐证；但属格形式（Turkish/Jordanian）免检。
"""

from __future__ import annotations

import json

from .normalize import is_cjk, strip_edge_punct, tokens

# 本身是常用词/人名，必须有方位佐证才采信的国家名
AMBIGUOUS_COUNTRIES = {
    "turkey", "jordan", "chad", "guinea", "niger", "mali", "panama", "cyprus",
    "malta", "samoa", "tonga", "fiji", "belize", "guyana", "suriname",
    "dominica", "monaco", "andorra",
}

# 方位介词 / 移动动词：出现在地名之前或之后即视为「在谈论该地」
LOCATIVE_PREPS = {
    "in", "at", "from", "to", "into", "onto", "near", "across", "toward",
    "towards", "outside", "inside", "within", "of", "over", "around",
    "throughout", "visits", "visited", "visit", "reached", "leaves", "left",
    "arrives", "arrived", "returned", "fled", "flee", "headed", "bound",
    "heading", "protests", "protest",
}

# 只接受这些地理编码类型
OK_FEATURES = {"PCLI", "PPLC", "PPLA"}

# 这些国家名不作国家匹配（只走美国州层），避免 "Georgia" 落到第比利斯
COUNTRY_NAME_SKIP = {"georgia"}

# 允许保留的短别名（需全大写出现）
SHORT_ALIAS_WHITELIST = {"us", "uk", "un", "uae", "drc", "prc", "rss"}

MAX_ALIAS_WORDS = 4


class Place:
    """一个可被定位的地点。"""

    __slots__ = ("kind", "name", "zh", "lat", "lon", "cc", "country",
                 "country_zh", "aliases", "specificity", "matched_alias")

    def __init__(self, kind, name, zh, lat, lon, cc="", country="", country_zh="",
                 aliases=None, specificity=2):
        self.kind = kind
        self.name = name
        self.zh = zh
        self.lat = lat
        self.lon = lon
        self.cc = cc
        self.country = country
        self.country_zh = country_zh
        self.aliases = [a for a in (aliases or []) if a]
        self.specificity = specificity
        self.matched_alias = ""

    def to_dict(self):
        return {
            "kind": self.kind,
            "name": self.name,
            "zh": self.zh,
            "lat": self.lat,
            "lon": self.lon,
            "cc": self.cc,
            "country": self.country,
            "country_zh": self.country_zh,
            "matched_alias": self.matched_alias,
        }


class Gazetteer:
    def __init__(self, path: str):
        with open(path, encoding="utf-8") as f:
            self.raw = json.load(f)
        self.places: list[Place] = []
        self.alias_map: dict[str, list[Place]] = {}
        self.demonym_aliases: set[str] = set()
        self.country_by_cc: dict[str, Place] = {}
        self.region_centroids = self.raw.get("region_centroids", {})
        self.source_country = self.raw.get("source_country", {})
        self.feed_region = self.raw.get("feed_region", {})
        self._build()

    # ------------------------------------------------------------------
    def _add(self, place: Place):
        self.places.append(place)
        for al in place.aliases:
            key = al.lower().strip()
            if not key:
                continue
            self.alias_map.setdefault(key, []).append(place)

    @staticmethod
    def _clean_aliases(aliases: list[str]) -> list[str]:
        out = []
        for al in aliases:
            low = al.lower().strip()
            if not low:
                continue
            alnum = sum(1 for ch in low if ch.isalnum())
            if alnum == 0:
                continue
            if len(low) > 60:
                continue
            if alnum <= 2 and low not in SHORT_ALIAS_WHITELIST:
                continue
            out.append(low)
            # 剥离首尾标点的变体（"u.s." → "u.s"，"gaza strip." → "gaza strip"）
            stripped = strip_edge_punct(low)
            if stripped and stripped != low:
                if sum(1 for ch in stripped if ch.isalnum()) > 2:
                    out.append(stripped)
        return sorted(set(out))

    def _build(self):
        raw = self.raw

        # ---- 首都先建，供国家取用 ----
        capital_by_cc: dict[str, dict] = {}
        for c in raw.get("capitals", []):
            capital_by_cc[c.get("cc", "")] = c

        # ---- 国家 ----
        for c in raw.get("countries", []):
            aliases = self._clean_aliases(c.get("aliases", []))
            aliases = [a for a in aliases if a not in COUNTRY_NAME_SKIP]
            demonym = (c.get("demonym_en") or "").strip().lower()
            if demonym:
                aliases.append(demonym)
                self.demonym_aliases.add(demonym)

            cap = capital_by_cc.get(c["cc"])
            lat, lon = (cap["lat"], cap["lon"]) if cap else (c.get("lat"), c.get("lon"))

            p = Place(
                kind="country", name=c["name"], zh=c.get("zh", ""),
                lat=lat, lon=lon, cc=c["cc"],
                country=c["name"], country_zh=c.get("zh", ""),
                aliases=aliases, specificity=0,
            )
            self._add(p)
            self.country_by_cc[c["cc"]] = p

        # ---- 首都 ----
        for c in raw.get("capitals", []):
            self._add(Place(
                kind="capital", name=c["name"], zh=c.get("zh", ""),
                lat=c["lat"], lon=c["lon"], cc=c.get("cc", ""),
                country=c.get("country", ""), country_zh=c.get("zh", ""),
                aliases=self._clean_aliases([c["name"], c.get("zh") or ""]),
                specificity=2,
            ))

        # ---- 城市 ----
        for c in raw.get("cities", []):
            self._add(Place(
                kind="city", name=c["name"], zh=c.get("zh", ""),
                lat=c["lat"], lon=c["lon"], cc=c.get("cc", ""),
                country=c.get("country", ""), country_zh=c.get("zh", ""),
                aliases=self._clean_aliases(c.get("aliases", [])),
                specificity=2,
            ))

        # ---- 热点地区 ----
        for c in raw.get("hotspots", []):
            self._add(Place(
                kind="hotspot", name=c["name"], zh=c.get("zh", ""),
                lat=c["lat"], lon=c["lon"],
                aliases=self._clean_aliases(c.get("aliases", [])),
                specificity=2,
            ))

        # ---- 美国州 ----
        for c in raw.get("us_states", []):
            self._add(Place(
                kind="state", name=c["name"], zh=c.get("zh", ""),
                lat=c["lat"], lon=c["lon"], cc="US", country="United States",
                country_zh="美国",
                aliases=self._clean_aliases(c.get("aliases", [])),
                specificity=1,
            ))

        # ---- 洲 / 大区（最低置信度） ----
        for c in raw.get("continents", []):
            self._add(Place(
                kind="continent", name=c["name"], zh=c.get("zh", ""),
                lat=c["lat"], lon=c["lon"],
                aliases=self._clean_aliases(c.get("aliases", [])),
                specificity=0,
            ))

        # ---- 运行期新发现的地名 ----
        for c in raw.get("discovered", []):
            self._add(Place(
                kind="discovered", name=c["name"], zh=c.get("zh", ""),
                lat=c["lat"], lon=c["lon"], cc=c.get("cc", ""),
                country=c.get("country", ""), country_zh=c.get("country_zh", ""),
                aliases=self._clean_aliases([c["name"]]),
                specificity=2,
            ))

    # ------------------------------------------------------------------
    def add_discovered(self, entries: list[dict]):
        """把运行期新解析出的地名并入索引。"""
        for c in entries:
            p = Place(
                kind="discovered", name=c["name"], zh=c.get("zh", ""),
                lat=c["lat"], lon=c["lon"], cc=c.get("cc", ""),
                country=c.get("country", ""), country_zh=c.get("country_zh", ""),
                aliases=self._clean_aliases([c["name"]]), specificity=2,
            )
            self._add(p)

    # ------------------------------------------------------------------
    def _base_score(self, place: Place, in_title: bool) -> float:
        if place.kind == "country":
            return 0.70 if in_title else 0.50
        if place.kind == "state":
            return 0.62 if in_title else 0.42
        if place.kind == "discovered":
            return 0.55 if in_title else 0.40
        if place.kind == "continent":
            return 0.40 if in_title else 0.30
        return 1.00 if in_title else 0.78  # city / capital / hotspot

    def _needs_cue(self, place: Place, alias: str) -> bool:
        """歧义国家名需要方位佐证；属格形式免检。"""
        if place.kind != "country":
            return False
        if alias in self.demonym_aliases:
            return False
        return alias in AMBIGUOUS_COUNTRIES

    def _has_cue(self, low: list[str], i: int, width: int) -> bool:
        before = low[max(0, i - 2):i]
        after = low[i + width:i + width + 2]
        return any(t in LOCATIVE_PREPS for t in before + after)

    def _case_ok(self, orig: list[str], i: int, phrase: str) -> bool:
        """大小写规则：拉丁文需首字母大写；短别名需全大写。"""
        if i >= len(orig):
            return True
        tok = orig[i]
        if not tok:
            return True
        if is_cjk(tok[0]):
            return True
        alnum = sum(1 for ch in phrase if ch.isalnum())
        if alnum <= 3:
            # US / UK / UAE —— 必须全大写
            return tok.isupper() and len(tok) >= 2
        return tok[0].isupper()

    # ------------------------------------------------------------------
    def match(self, title: str, description: str = "") -> list[dict]:
        """返回按置信度降序排列的命中列表 [{place, score, field, alias}, ...]"""
        hits: dict[int, dict] = {}

        for field, text in (("title", title), ("desc", description)):
            if not text:
                continue
            orig = tokens(text)
            low = [t.lower() for t in orig]
            n = len(low)
            for width in range(min(MAX_ALIAS_WORDS, n), 0, -1):
                for i in range(n - width + 1):
                    phrase = " ".join(low[i:i + width])
                    candidates = self.alias_map.get(phrase)
                    if not candidates:
                        continue
                    if not self._case_ok(orig, i, phrase):
                        continue
                    for place in candidates:
                        if self._needs_cue(place, phrase) and not self._has_cue(low, i, width):
                            continue
                        score = self._base_score(place, field == "title")
                        prev = hits.get(id(place))
                        if prev is None or score > prev["score"]:
                            hits[id(place)] = {
                                "place": place,
                                "score": score,
                                "field": field,
                                "alias": phrase,
                            }

        out = sorted(hits.values(), key=lambda h: (-h["score"], -h["place"].specificity))
        for h in out:
            h["place"].matched_alias = h["alias"]
        return out

    # ------------------------------------------------------------------
    def country_placeholder(self, cc: str) -> dict | None:
        """来源国兜底（最低置信度）。"""
        p = self.country_by_cc.get(cc)
        if not p or p.lat is None:
            return None
        return {
            "kind": "country",
            "name": p.name,
            "zh": p.zh,
            "lat": p.lat,
            "lon": p.lon,
            "cc": p.cc,
            "country": p.name,
            "country_zh": p.zh,
            "matched_alias": p.name,
        }

    def region_placeholder(self, region: str) -> dict | None:
        """区域源兜底。"""
        rc = self.region_centroids.get(region)
        if not rc:
            return None
        return {
            "kind": "region",
            "name": region,
            "zh": region,
            "lat": rc[0],
            "lon": rc[1],
            "cc": "",
            "country": region,
            "country_zh": region,
            "matched_alias": region,
        }
