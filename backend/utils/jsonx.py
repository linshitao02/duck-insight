# -*- coding: utf-8 -*-
import json
import math
from datetime import date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd


def _finite_or_none(value):
    """NaN / Infinity 不是合法 JSON，浏览器 JSON.parse 会直接抛错，统一转成 None。"""
    try:
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def json_safe(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        # 注意：整列全空时 pandas describe() 会给出原生 float('nan')，
        # 这里必须拦掉，否则响应体带上 NaN，前端 JSON.parse 失败并误报「上传失败」。
        return _finite_or_none(value)
    if isinstance(value, str):
        return value
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        if np.isnan(value) or np.isinf(value):
            return None
        return float(value)
    if isinstance(value, Decimal):
        return _finite_or_none(float(value))
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    if isinstance(value, pd.DataFrame):
        return {"rows": int(len(value)), "columns": [str(c) for c in value.columns]}
    if isinstance(value, pd.Series):
        return [json_safe(v) for v in value.head(80).tolist()]
    if isinstance(value, np.ndarray):
        if value.size > 400:
            return {"shape": list(value.shape), "dtype": str(value.dtype)}
        return json_safe(value.tolist())
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return str(value)


class JSONEncoder(json.JSONEncoder):
    def default(self, obj):
        converted = json_safe(obj)
        if converted is obj:
            return str(obj)
        return converted


def _strip_nonfinite(value):
    """兜底：递归把残留的 NaN/Infinity 换成 None，保证输出一定是合法 JSON。"""
    if isinstance(value, float):
        return _finite_or_none(value)
    if isinstance(value, dict):
        return {str(k): _strip_nonfinite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_strip_nonfinite(v) for v in value]
    return value


def dumps(obj, **kwargs):
    kwargs.setdefault("ensure_ascii", False)
    kwargs.setdefault("cls", JSONEncoder)
    try:
        obj = json_safe(obj)
    except Exception:
        pass
    try:
        # allow_nan=False：绝不允许 NaN/Infinity 出现在响应里
        return json.dumps(obj, allow_nan=False, **kwargs)
    except ValueError:
        return json.dumps(_strip_nonfinite(obj), allow_nan=False, **kwargs)


def loads(text, default=None):
    if text is None or text == "":
        return default
    if isinstance(text, (dict, list)):
        return text
    try:
        return json.loads(text)
    except Exception:
        return default


def row_to_dict(row):
    if not row:
        return row
    out = {}
    for k, v in row.items():
        out[k] = json_safe(v)
        if k.endswith("_json") and isinstance(v, str):
            parsed = loads(v, default=v)
            out[k[:-5] if k.endswith("_json") else k] = parsed
            out[k] = parsed
    return out
