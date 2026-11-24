# -*- coding: utf-8 -*-
"""全局配置：数据源、路径、常量。"""

from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
WEB_DIR = os.path.join(ROOT, "web")

GAZETTEER_PATH = os.path.join(DATA_DIR, "gazetteer.json")
NEWS_JSON_PATH = os.path.join(DATA_DIR, "news.json")
NEWS_JS_PATH = os.path.join(DATA_DIR, "news-data.js")
WEB_DATA_DIR = os.path.join(WEB_DIR, "data")
WEB_NEWS_JS_PATH = os.path.join(WEB_DATA_DIR, "news-data.js")
WEB_NEWS_JSON_PATH = os.path.join(WEB_DATA_DIR, "news.json")
DISCOVERED_PATH = os.path.join(DATA_DIR, "_discovered_places.json")
GEOCODE_CACHE_PATH = os.path.join(DATA_DIR, "_geocode_cache.json")

# 历史数据保留天数（超出则裁剪，保证文件不无限增长）
RETENTION_DAYS = 90

# 单轮最多对多少条「定位不明确」的新闻尝试扩展地名库
DISCOVERY_MAX_ITEMS = 90

# 单次抓取的 HTTP 超时（秒）
HTTP_TIMEOUT = 25

# 抓取时的并发度
FETCH_WORKERS = 6

USER_AGENT = "news-world-map/1.0 (RSS aggregator; +https://localhost)"

# ---------------------------------------------------------------------------
# 数据源（全部为实测可达且保持更新的 feed）
#   region  —— 区域源，用于「只知道大概在哪」时的兜底定位
#   country —— 该媒体总部所在国家，最低置信度兜底
# ---------------------------------------------------------------------------
FEEDS = [
    {"id": "npr_world", "name": "NPR World", "region": "", "country": "US",
     "url": "https://feeds.npr.org/1004/rss.xml"},
    {"id": "npr_us", "name": "NPR US", "region": "Americas", "country": "US",
     "url": "https://feeds.npr.org/1001/rss.xml"},
    {"id": "cbs_world", "name": "CBS News World", "region": "", "country": "US",
     "url": "https://www.cbsnews.com/latest/rss/world"},
    {"id": "cbs_us", "name": "CBS News US", "region": "Americas", "country": "US",
     "url": "https://www.cbsnews.com/latest/rss/us"},
    {"id": "sky_world", "name": "Sky News World", "region": "Europe", "country": "GB",
     "url": "https://feeds.skynews.com/feeds/rss/world.xml"},
    {"id": "un_all", "name": "UN News", "region": "", "country": "",
     "url": "https://news.un.org/feed/subscribe/en/news/all/rss.xml"},
    {"id": "un_asia", "name": "UN News Asia-Pacific", "region": "Asia / Pacific", "country": "",
     "url": "https://news.un.org/feed/subscribe/en/news/region/asia-pacific/feed/rss.xml"},
    {"id": "un_europe", "name": "UN News Europe", "region": "Europe", "country": "",
     "url": "https://news.un.org/feed/subscribe/en/news/region/europe/feed/rss.xml"},
    {"id": "f24_main", "name": "France 24", "region": "", "country": "FR",
     "url": "https://www.france24.com/en/rss"},
    {"id": "f24_africa", "name": "France 24 Africa", "region": "Africa", "country": "FR",
     "url": "https://www.france24.com/en/africa/rss"},
    {"id": "f24_asia", "name": "France 24 Asia-Pacific", "region": "Asia / Pacific", "country": "FR",
     "url": "https://www.france24.com/en/asia-pacific/rss"},
    {"id": "f24_americas", "name": "France 24 Americas", "region": "Americas", "country": "FR",
     "url": "https://www.france24.com/en/americas/rss"},
    {"id": "f24_me", "name": "France 24 Middle East", "region": "Middle East", "country": "FR",
     "url": "https://www.france24.com/en/middle-east/rss"},
    {"id": "f24_europe", "name": "France 24 Europe", "region": "Europe", "country": "FR",
     "url": "https://www.france24.com/en/europe/rss"},
    {"id": "abc_intl", "name": "ABC News International", "region": "", "country": "US",
     "url": "https://abcnews.go.com/abcnews/internationalheadlines"},
]
