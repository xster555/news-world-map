# -*- coding: utf-8 -*-
"""RSS/Atom 抓取与解析（仅用标准库）。"""

from __future__ import annotations

import gzip
import re
import socket
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from .config import FETCH_WORKERS, HTTP_TIMEOUT, USER_AGENT
from .normalize import strip_html

# 命名空间
NS_MEDIA = "http://search.yahoo.com/mrss/"
NS_CONTENT = "http://purl.org/rss/1.0/modules/content/"
NS_DC = "http://purl.org/dc/elements/1.1/"
NS_RSS = "http://purl.org/rss/1.0/modules/dowjones/"

_IMG_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)
_DATE_FMTS = [
    "%a, %d %b %Y %H:%M:%S %z",
    "%a, %d %b %Y %H:%M:%S %Z",
    "%a, %d %b %Y %H:%M %z",
    "%a, %d %b %Y %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
]


def _tag(el) -> str:
    return el.tag.split("}")[-1] if "}" in el.tag else el.tag


def _find(parent, name):
    for c in parent:
        if _tag(c) == name:
            return c
    return None


def _find_all(parent, name):
    return [c for c in parent if _tag(c) == name]


def _parse_date(raw: str) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(raw)
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
    except Exception:  # noqa: BLE001
        pass
    s = raw.replace("Z", "+0000")
    for fmt in _DATE_FMTS:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def fetch(url: str, tries: int = 3) -> bytes:
    """带重试的 GET。失败抛异常，由调用方按源隔离处理。"""
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
                "Accept-Encoding": "gzip",
            })
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
                data = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return data
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 503):
                import time
                time.sleep(3 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as e:
            last = e
            import time
            time.sleep(1.5 * (attempt + 1))
    raise last if last else RuntimeError("fetch failed")


def _extract_image(item) -> str:
    """尽力从多种字段里取图片。"""
    # 1) <image>url</image> 或 <image><url>..</url></image>
    for img in _find_all(item, "image"):
        if (img.text or "").strip().startswith("http"):
            return img.text.strip()
        u = _find(img, "url")
        if u is not None and (u.text or "").strip().startswith("http"):
            return u.text.strip()
    # 2) media:thumbnail / media:content
    for c in item:
        tag = c.tag
        if tag.startswith("{" + NS_MEDIA + "}"):
            url = c.get("url") or ""
            if url.startswith("http"):
                return url
    # 3) enclosure
    enc = _find(item, "enclosure")
    if enc is not None:
        url = enc.get("url") or ""
        if url.startswith("http") and (enc.get("type") or "").startswith("image"):
            return url
    # 4) 正文里的第一张 <img>
    for c in item:
        t = _tag(c)
        if t in ("encoded", "description", "summary", "content"):
            m = _IMG_RE.search(c.text or "")
            if m:
                return m.group(1)
    return ""


def _item_link(item) -> str:
    link = _find(item, "link")
    if link is not None:
        if (link.text or "").strip().startswith("http"):
            return link.text.strip()
        href = link.get("href")
        if href:
            return href
    guid = _find(item, "guid")
    if guid is not None and (guid.text or "").strip().startswith("http"):
        return guid.text.strip()
    return ""


def parse_feed(raw: bytes, feed: dict) -> list[dict]:
    """解析 feed，返回条目列表。"""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise ValueError(f"XML parse error: {e}") from e

    items = []
    for el in root.iter():
        if _tag(el) in ("item", "entry"):
            items.append(el)

    out = []
    for item in items:
        title_el = _find(item, "title")
        title = strip_html(title_el.text if title_el is not None else "")
        if not title:
            continue
        link = _item_link(item)

        desc = ""
        for name in ("description", "summary", "encoded", "content"):
            d = _find(item, name)
            if d is not None and (d.text or "").strip():
                desc = d.text
                break

        published = None
        for name in ("pubDate", "published", "updated", "date"):
            d = _find(item, name)
            if d is not None and (d.text or "").strip():
                published = _parse_date(d.text)
                if published:
                    break
        if published is None:
            published = datetime.now(timezone.utc)

        # 来源栏目（France24 用 category 表示大区，WSJ 用 articletype）
        section = ""
        for c in item:
            if c.tag.startswith("{http://purl.org/dc/elements/1.1/}"):
                continue
            if _tag(c) == "category" and (c.text or "").strip():
                section = c.text.strip()
                break
        if not section:
            for c in item:
                if c.tag.startswith("{http://purl.org/rss/1.0/modules/dowjones/}"):
                    section = (c.text or "").strip()
                    break

        out.append({
            "title": title,
            "summary": strip_html(desc),
            "url": link,
            "published_at": published,
            "image": _extract_image(item),
            "section": section,
            "feed_id": feed["id"],
            "source": feed["name"],
        })
    return out


def fetch_all(feeds: list[dict], log=print) -> tuple[list[dict], list[dict]]:
    """并发抓取所有源。返回 (成功条目, 源状态列表)。"""
    results: list[dict] = []
    status: list[dict] = []

    def run(feed):
        try:
            raw = fetch(feed["url"])
            items = parse_feed(raw, feed)
            return feed, items, None
        except Exception as e:  # noqa: BLE001
            return feed, [], f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        for feed, items, err in ex.map(run, feeds):
            if err:
                log(f"    [--] {feed['id']:<14} 失败: {err}")
                status.append({"id": feed["id"], "ok": False, "count": 0, "error": err})
            else:
                log(f"    [OK] {feed['id']:<14} {len(items):>3} 条")
                status.append({"id": feed["id"], "ok": True, "count": len(items), "error": ""})
                results.extend(items)
    return results, status
