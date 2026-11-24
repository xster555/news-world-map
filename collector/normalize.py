# -*- coding: utf-8 -*-
"""文本归一化与去重键。"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_WS_RE = re.compile(r"\s+")

# 保留字母（含中日韩）、数字、空格；其余转空格
_KEEP_RE = re.compile(r"[^\w\s]", re.UNICODE)

# 需要从词首/词尾剥离的标点（含中英文）
_EDGE_PUNCT = ".,;:!?()[]{}\"'`~@#$%^&*-_=+|\\/<>，。、；：？！“”‘’（）《》「」『』【】…—～·"

# 英文所有格：haiti's → haiti
_POSSESSIVE_RE = re.compile(r"[’'](?:s|s)$")


def strip_edge_punct(s: str) -> str:
    """剥离词首/词尾的标点（中英文），保留中间的缩写点（U.S. → U.S）。"""
    if not s:
        return ""
    return s.strip(_EDGE_PUNCT).strip()



def strip_html(raw: str) -> str:
    """去标签 + 解实体 + 压缩空白。"""
    if not raw:
        return ""
    s = _SCRIPT_RE.sub(" ", raw)
    s = _TAG_RE.sub(" ", s)
    s = html.unescape(s)
    s = s.replace("\u00a0", " ").replace("\u200b", "")
    s = _WS_RE.sub(" ", s).strip()
    return s


def normalize(text: str) -> str:
    """小写 + 去标点 + 压缩空白，用于匹配与去重。"""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text).lower()
    s = _KEEP_RE.sub(" ", s)
    return _WS_RE.sub(" ", s).strip()


def tokens(text: str) -> list[str]:
    """切词：拉丁文按空白切，CJK 按字切（地名多为中英混合）。"""
    s = unicodedata.normalize("NFKC", text or "")
    out: list[str] = []
    for chunk in s.split():
        buf = ""
        for ch in chunk:
            if is_cjk(ch):
                if buf:
                    out.append(_clean_token(buf))
                    buf = ""
                out.append(ch)
            else:
                buf += ch
        if buf:
            out.append(_clean_token(buf))
    return [t for t in out if t]


def _clean_token(tok: str) -> str:
    """剥离标点与英文所有格：'Ukraine,' → 'Ukraine'，"Haiti's" → 'Haiti'。

    保留原始大小写——匹配器要用大小写做防误判判断。
    """
    t = _POSSESSIVE_RE.sub("", tok)
    t = strip_edge_punct(t)
    return t


def is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (
        0x4E00 <= o <= 0x9FFF      # CJK 统一表意
        or 0x3400 <= o <= 0x4DBF   # 扩展 A
        or 0xF900 <= o <= 0xFAFF   # 兼容表意
        or 0x3040 <= o <= 0x30FF   # 日文假名
        or 0xAC00 <= o <= 0xD7AF   # 韩文
    )


def title_key(title: str) -> str:
    """标题去重键：归一化后取 SHA1 前 12 位。"""
    n = normalize(title)
    return hashlib.sha1(n.encode("utf-8")).hexdigest()[:12]


def url_key(url: str) -> str:
    """URL 去重键：去掉协议、www、查询串与末尾斜杠。"""
    if not url:
        return ""
    u = url.strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    u = u.split("#")[0].split("?")[0]
    u = u.rstrip("/")
    return hashlib.sha1(u.encode("utf-8")).hexdigest()[:12]


def truncate(text: str, limit: int = 320) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    sp = cut.rfind(" ")
    if sp > limit * 0.6:
        cut = cut[:sp]
    return cut.rstrip() + "…"
