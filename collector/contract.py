# -*- coding: utf-8 -*-
"""数据契约：加载 contract/news-v1.json 并校验数据是否符合规格。

契约只有一份（contract/news-v1.json），Python 端与 JS 端（web/contract.js）
各实现一个极简校验器读同一份规格，规则子集刻意保持很小、两边完全对称：

    type / required / nullable / enum / minLength / items / properties / $ref

用法：

    from collector.contract import load_spec, validate
    errors = validate(payload, load_spec())

返回错误列表（空列表表示通过），每条形如
``items[37].title: 缺失（必填）``。
"""

from __future__ import annotations

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT_PATH = os.path.join(ROOT, "contract", "news-v1.json")


def load_spec(path=None):
    """读取契约规格。path 省略时用仓库里的 contract/news-v1.json。"""
    with open(path or CONTRACT_PATH, encoding="utf-8") as f:
        return json.load(f)


def validate(payload, spec):
    """按规格校验一份数据，返回错误列表；空列表表示通过。"""
    errors = []
    if not spec or not spec.get("payload"):
        return errors
    _check(payload, _resolve(spec, spec["payload"]), spec, "", errors)
    return errors


# ---------------------------------------------------------------------------
def _resolve(spec, node):
    """把 {"$ref": "item"} 展开成本体，并与本层的覆盖项合并。"""
    if not isinstance(node, dict) or "$ref" not in node:
        return node
    base = dict(spec.get(node["$ref"]) or {})
    for key, value in node.items():
        if key != "$ref":
            base[key] = value
    return _resolve(spec, base)


def _type_ok(value, type_name):
    if type_name == "any":
        return True
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "object":
        return isinstance(value, dict)
    return False


def _kind(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _check(value, node, spec, path, errors):
    """校验一个值；node 是已展开引用的字段规格。"""
    if value is None:
        if node.get("nullable"):
            return
        errors.append("%s: 不允许为 null" % (path or "根"))
        return

    type_name = node.get("type", "any")
    if not _type_ok(value, type_name):
        errors.append("%s: 期望 %s，实际 %s" % (path or "根", type_name, _kind(value)))
        return

    if "enum" in node and value not in node["enum"]:
        errors.append("%s: 取值 %s 不在允许范围 (%s)"
                      % (path, value, ", ".join(str(x) for x in node["enum"])))

    if type_name == "string" and "minLength" in node and len(value) < node["minLength"]:
        errors.append("%s: 长度 %d 小于最小 %d" % (path, len(value), node["minLength"]))

    if type_name == "array" and "items" in node:
        item_node = _resolve(spec, node["items"])
        for index, element in enumerate(value):
            _check(element, item_node, spec, "%s[%d]" % (path, index), errors)

    if type_name == "object" and "properties" in node:
        props = node["properties"]
        # required 是「必填字段名数组」，只出现在对象级规格上。
        required = node.get("required") or []
        for name in required:
            if name not in props:
                errors.append("%s.%s: 契约声明为必填，但没有定义字段规格"
                              % (path or "根", name))
        for name, raw in props.items():
            sub = _resolve(spec, raw)
            child = "%s.%s" % (path, name) if path else name
            if name not in value:
                if name in required:
                    errors.append("%s: 缺失（必填）" % child)
                continue
            _check(value[name], sub, spec, child, errors)
