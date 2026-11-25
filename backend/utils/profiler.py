# -*- coding: utf-8 -*-
import math
import re

import numpy as np
import pandas as pd

from utils.field_labels import label_zh_for
from utils.jsonx import json_safe

ID_HINTS = re.compile(r"(^id$|_id$|id$|code$|key$|编号|编码)", re.I)
DATE_HINTS = re.compile(r"(date|time|day|日期|时间)", re.I)
TARGET_HINTS = re.compile(r"(sales|amount|target|label|y$|销量|销售额|目标)", re.I)


def _parse_datetime_sample(series: pd.Series):
    """解析一小段样本。显式 mixed 格式，避免日期字符串触发逐行推断警告。"""
    sample = series.head(200)
    try:
        return pd.to_datetime(sample, errors="coerce", format="mixed")
    except (TypeError, ValueError):
        return pd.to_datetime(sample, errors="coerce")


def infer_series_type(series: pd.Series):
    name = str(series.name or "")
    s = series.dropna()
    if s.empty:
        return "unknown"
    if DATE_HINTS.search(name):
        parsed = _parse_datetime_sample(s)
        if parsed.notna().mean() > 0.8:
            return "datetime"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    if pd.api.types.is_numeric_dtype(series):
        nunique = s.nunique()
        if ID_HINTS.search(name) or (nunique > 50 and nunique / max(len(s), 1) > 0.9):
            return "id"
        return "numeric"
    parsed = _parse_datetime_sample(s)
    if parsed.notna().mean() > 0.85:
        return "datetime"
    nunique = s.nunique()
    if ID_HINTS.search(name) or nunique / max(len(s), 1) > 0.95:
        return "id"
    if nunique <= 50:
        return "categorical"
    return "text"


def suggest_role(col_name, inferred, n_unique, n_rows):
    name = str(col_name)
    if TARGET_HINTS.search(name):
        return "target"
    if inferred == "id" or ID_HINTS.search(name):
        return "key"
    if inferred == "datetime":
        return "time"
    if name.lower() in ("customers",):
        return "leakage"
    return "feature"


def profile_dataframe(df: pd.DataFrame, sample_n=6):
    rows = []
    n = len(df)
    for col in df.columns:
        s = df[col]
        inferred = infer_series_type(s)
        n_null = int(s.isna().sum())
        n_unique = int(s.nunique(dropna=True))
        sample = [json_safe(v) for v in s.dropna().head(sample_n).tolist()]
        stats = {
            "name": str(col),
            "label_zh": label_zh_for(col),
            "dtype": str(s.dtype),
            "inferred": inferred,
            "role": suggest_role(col, inferred, n_unique, n),
            "null_count": n_null,
            "null_ratio": round(n_null / max(n, 1), 4),
            "unique_count": n_unique,
            "null_strategy": "auto" if n_null else "keep",
            "included": suggest_role(col, inferred, n_unique, n) != "leakage",
            "sample": sample,
        }
        if pd.api.types.is_numeric_dtype(s):
            desc = s.describe()
            stats["min"] = json_safe(desc.get("min"))
            stats["max"] = json_safe(desc.get("max"))
            stats["mean"] = json_safe(desc.get("mean"))
        rows.append(stats)
    return {
        "n_rows": int(n),
        "n_cols": int(df.shape[1]),
        "columns": rows,
    }


def preview_records(df: pd.DataFrame, n=30):
    head = df.head(n).replace({np.nan: None})
    records = []
    for rec in head.to_dict(orient="records"):
        records.append({k: json_safe(v) for k, v in rec.items()})
    return records
