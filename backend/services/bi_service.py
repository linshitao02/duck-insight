# -*- coding: utf-8 -*-
"""FineBI 风格自助看板：数据源、维度/指标聚合、组件布局。

维度模型（新）
-------------
每个组件保存 ``dims`` 列表，元素形如::

    {"field": "ts", "split": "year_month_day_hour", "filters": [{...}]}

``split`` 支持 none / year / year_month / year_month_day /
year_month_day_hour / year_month_day_hour_minute；为 none 时按原始值展示，
时间类字段会退回全局 grain 分桶以兼容旧看板。

指标保存 ``measures`` 列表 ``{"field": "...", "agg": "avg"}``。
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime

import pandas as pd

from config import to_abs
from utils.db import insert, query, update
from utils.field_labels import label_zh_for
from utils.io import load_dataframe
from utils.jsonx import dumps, json_safe, loads, row_to_dict

METRIC_CATALOG = [
    {"key": "temp_c", "label": "温度 ℃"},
    {"key": "wind_10m", "label": "10m 风速 m/s"},
    {"key": "wind_100m", "label": "100m 风速 m/s"},
    {"key": "wind_gust", "label": "阵风 m/s"},
    {"key": "radiation", "label": "辐照 W/m²"},
    {"key": "precip_mm", "label": "降水 mm"},
    {"key": "humidity", "label": "湿度 %"},
]
HORIZON_CATALOG = [
    {"key": "actual", "label": "实况"},
    {"key": "short_1_3d", "label": "短期 1–3 天"},
    {"key": "medium_7_16d", "label": "中期 7–16 天"},
    {"key": "long_17_45d", "label": "中长期 17–45 天"},
    {"key": "midlong_7_45d", "label": "中长期 7–45 天"},
]
GRAINS = [
    {"key": "hour", "label": "按小时"},
    {"key": "day", "label": "按天"},
    {"key": "month", "label": "按月"},
]
# 时间维度拆分方式
TIME_SPLITS = [
    {"key": "none", "label": "不拆分（原始时间）"},
    {"key": "year", "label": "年"},
    {"key": "year_month", "label": "年月"},
    {"key": "year_month_day", "label": "年月日"},
    {"key": "year_month_day_hour", "label": "年月日时"},
    {"key": "year_month_day_hour_minute", "label": "年月日时分"},
]
TIME_SPLIT_FORMAT = {
    "year": "%Y",
    "year_month": "%Y-%m",
    "year_month_day": "%Y-%m-%d",
    "year_month_day_hour": "%Y-%m-%d %H:00",
    "year_month_day_hour_minute": "%Y-%m-%d %H:%M",
}
TIME_SPLIT_LABEL = {item["key"]: item["label"] for item in TIME_SPLITS}

AGG_OPS = [
    {"key": "avg", "label": "平均"},
    {"key": "sum", "label": "求和"},
    {"key": "max", "label": "最大"},
    {"key": "min", "label": "最小"},
    {"key": "count", "label": "计数"},
    {"key": "median", "label": "中位数"},
    {"key": "nunique", "label": "去重计数"},
]
_PANDAS_AGG = {
    "avg": "mean",
    "sum": "sum",
    "max": "max",
    "min": "min",
    "count": "count",
    "median": "median",
    "nunique": "nunique",
}
WIDGET_TYPES = [
    {"key": "kpi", "label": "指标卡", "group": "指标", "icon": "odometer", "dims": 0, "meas": 1},
    {"key": "line", "label": "折线图", "group": "趋势", "icon": "trend", "dims": 1, "meas": 8},
    {"key": "area", "label": "面积图", "group": "趋势", "icon": "area", "dims": 1, "meas": 8},
    {"key": "bar", "label": "柱状图", "group": "对比", "icon": "bar", "dims": 1, "meas": 8},
    {"key": "hbar", "label": "条形图", "group": "对比", "icon": "hbar", "dims": 1, "meas": 8},
    {"key": "combo", "label": "双轴组合", "group": "对比", "icon": "combo", "dims": 1, "meas": 4},
    {"key": "pie", "label": "饼图", "group": "构成", "icon": "pie", "dims": 1, "meas": 1},
    {"key": "scatter", "label": "散点图", "group": "相关", "icon": "scatter", "dims": 0, "meas": 2},
    {"key": "heatmap", "label": "热力图", "group": "分布", "icon": "heat", "dims": 2, "meas": 1},
    {"key": "table", "label": "明细表", "group": "明细", "icon": "table", "dims": 6, "meas": 8},
]
BOARD_TEMPLATES = [
    {"key": "blank", "label": "空白看板", "desc": "从组件库拖入图表后绑定字段"},
    {"key": "power_monitor", "label": "气象-负荷-出力-电价监测", "desc": "四联 KPI + 趋势/对比/热力/极端事件"},
    {"key": "realtime", "label": "实时监测看板", "desc": "直连 MySQL 活表，刷新即读最新数据"},
    {"key": "trend", "label": "趋势分析", "desc": "指标卡 + 时间折线 + 明细表"},
    {"key": "composition", "label": "构成分析", "desc": "饼图 + 对比柱状 + 排行条形"},
]
DIM_HINTS = {"ts", "date", "datetime", "hour", "day", "month", "year", "weekday", "site", "site_name",
             "event_type", "weather_source", "store", "storetype", "promo", "stateholiday"}
TIME_HINTS = {"ts", "date", "datetime", "time"}
SKIP_FIELDS = {"row_key", "_ts"}
WEEKDAY_ZH = {0: "周一", 1: "周二", 2: "周三", 3: "周四", 4: "周五", 5: "周六", 6: "周日"}
_FRAME_CACHE = {}
_LIVE_CACHE = {}
LIVE_CACHE_TTL = 60          # 实时表缓存秒数
LIVE_BI_ROWS = 30000         # BI 直连读取的最大行数（取最新）


def _user():
    try:
        from flask import g, has_request_context
        if has_request_context():
            return getattr(g, "user", None) or {}
    except Exception:
        pass
    return {}


def _new_id(prefix="w"):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _empty_layout():
    return {"theme": "finebi", "grain": "day", "filters": [], "widgets": [], "default_source": None}


# --------------------------------------------------------------------------- #
# 维度模型工具
# --------------------------------------------------------------------------- #
def _norm_dim(dim):
    if isinstance(dim, str):
        return {"field": dim, "kind": "dim", "split": "none", "filters": []}
    if not isinstance(dim, dict):
        return None
    field = dim.get("field")
    if not field:
        return None
    split = str(dim.get("split") or "none").lower()
    if split not in TIME_SPLIT_FORMAT and split != "none":
        split = "none"
    kind = str(dim.get("kind") or "").lower()
    if kind not in ("time", "dim"):
        kind = "time" if split != "none" else "dim"
    filters = []
    for flt in dim.get("filters") or []:
        if isinstance(flt, dict) and flt.get("field"):
            item = dict(flt)
            item.setdefault("kind", kind)
            item.pop("_open", None)
            filters.append(item)
    return {"field": field, "kind": kind, "split": split, "filters": filters}


def normalize_widget(widget):
    """统一为 dims / measures 新结构，兼容旧 dimensions 字段。"""
    if not isinstance(widget, dict):
        return widget
    w = dict(widget)
    dims = w.get("dims")
    if not isinstance(dims, list):
        dims = w.get("dimensions") or []
    cleaned = [d for d in (_norm_dim(d) for d in dims) if d]
    w["dims"] = cleaned
    measures = []
    for m in w.get("measures") or []:
        if isinstance(m, dict) and m.get("field"):
            measures.append(m)
        elif isinstance(m, str):
            measures.append({"field": m, "agg": "avg"})
    w["measures"] = measures
    if not isinstance(w.get("filters"), list):
        w["filters"] = []
    return w


def _dim(field, split="none", filters=None, kind=None):
    if kind not in ("time", "dim"):
        kind = "time" if split and split != "none" else "dim"
    return {"field": field, "kind": kind, "split": split, "filters": filters or []}


def _widget(wtype, title, source, dims, measures, x, y, w, h, extra=None):
    item = {
        "id": _new_id("w"),
        "type": wtype,
        "title": title,
        "x": x, "y": y, "w": w, "h": h,
        "source": source,
        "dims": [d for d in (_norm_dim(d) for d in (dims or [])) if d],
        "measures": measures or [],
        "filters": [],
    }
    if extra:
        item.update(extra)
    return item


def catalog():
    return {
        "metrics": METRIC_CATALOG,
        "horizons": HORIZON_CATALOG,
        "grains": GRAINS,
        "time_splits": TIME_SPLITS,
        "aggregations": AGG_OPS,
        "widget_types": WIDGET_TYPES,
        "templates": BOARD_TEMPLATES,
        "filter_ops": [
            {"key": "eq", "label": "等于"},
            {"key": "ne", "label": "不等于"},
            {"key": "in", "label": "包含任一（多选）"},
            {"key": "contains", "label": "包含文本"},
            {"key": "gt", "label": "大于"},
            {"key": "gte", "label": "大于等于"},
            {"key": "lt", "label": "小于"},
            {"key": "lte", "label": "小于等于"},
            {"key": "between", "label": "区间"},
            {"key": "daterange", "label": "日期范围"},
        ],
        # 时间维度专用筛选项
        "time_filter_ops": [
            {"key": "daterange", "label": "日期区间"},
            {"key": "ondate", "label": "某一天"},
            {"key": "month", "label": "某年月"},
            {"key": "gte", "label": "晚于等于"},
            {"key": "lte", "label": "早于等于"},
            {"key": "gt", "label": "晚于"},
            {"key": "lt", "label": "早于"},
            {"key": "eq", "label": "等于"},
            {"key": "ne", "label": "不等于"},
        ],
    }


# --------------------------------------------------------------------------- #
# 数据源与读帧
# --------------------------------------------------------------------------- #
def _mtime(path):
    try:
        return os.path.getmtime(path) if path and os.path.exists(path) else 0
    except Exception:
        return 0


def _load_live_frame(ds, nrows=LIVE_BI_ROWS):
    """直连 MySQL 活表：优先按时间列倒序取最新数据，并做短时缓存。"""
    ds_id = int(ds["id"])
    now = time.time()
    hit = _LIVE_CACHE.get(ds_id)
    if hit and now - hit[0] < LIVE_CACHE_TTL:
        return hit[1]
    from services import source_service
    sid = ds.get("source_id")
    db = ds.get("source_db")
    table = ds.get("source_table")
    if not sid or not db or not table:
        return pd.DataFrame()
    order_col = None
    try:
        for col in source_service.column_types(sid, db, table):
            if col.get("data_type") in ("datetime", "timestamp", "date"):
                order_col = col.get("name")
                break
    except Exception:
        order_col = None
    try:
        df = source_service.read_live_frame(
            sid, db, table, nrows=nrows, order_col=order_col, desc=bool(order_col),
        )
    except Exception:
        return pd.DataFrame()
    _LIVE_CACHE[ds_id] = (now, df)
    if len(_LIVE_CACHE) > 12:
        oldest = min(_LIVE_CACHE.items(), key=lambda kv: kv[1][0])
        _LIVE_CACHE.pop(oldest[0], None)
    return df


def _live_dataset_row(sid):
    return query(
        "SELECT id, origin_type, source_id, source_db, source_table, file_path, n_rows FROM dataset WHERE id=%s",
        (int(sid),), one=True,
    )


def _load_frame(kind, sid):
    kind = kind or "dataset"
    sid = int(sid)
    path = None
    if kind in ("dataset", "live"):
        ds = _live_dataset_row(sid)
        if ds and ds.get("origin_type") == "mysql_live":
            return _load_live_frame(ds)
        path = to_abs((ds or {}).get("file_path"))
    elif kind == "binding":
        bind = query("SELECT * FROM dataset_binding WHERE id=%s", (sid,), one=True)
        path = to_abs((bind or {}).get("snapshot_path"))
    elif kind == "bundle":
        row = query("SELECT * FROM dataset_bundle WHERE id=%s", (sid,), one=True)
        path = to_abs((row or {}).get("materialized_path"))
    else:
        ds = _live_dataset_row(sid)
        path = to_abs((ds or {}).get("file_path"))
    if not path or not os.path.exists(path):
        return pd.DataFrame()
    key = (kind, sid, path)
    stamp = _mtime(path)
    cached = _FRAME_CACHE.get(key)
    if cached and cached[0] == stamp:
        return cached[1]
    df = load_dataframe(path)
    _FRAME_CACHE[key] = (stamp, df)
    if len(_FRAME_CACHE) > 24:
        oldest = min(_FRAME_CACHE.items(), key=lambda kv: kv[1][0])
        _FRAME_CACHE.pop(oldest[0], None)
    return df


def _load_board_frame(board):
    layout = (board or {}).get("layout") or {}
    src = layout.get("default_source") or {}
    if src.get("id"):
        return _load_frame(src.get("kind") or "dataset", src["id"])
    binding_id = board.get("binding_id")
    if binding_id:
        return _load_frame("binding", binding_id)
    ds_id = board.get("dataset_id")
    if ds_id:
        return _load_frame("dataset", ds_id)
    try:
        from services.weather_asset import hourly_frame
        return hourly_frame()
    except Exception:
        return pd.DataFrame()


def _looks_like_time_name(name):
    low = str(name or "").lower()
    return low in TIME_HINTS or low.endswith("date") or low.endswith("_time") or "日期" in str(name)


def _ensure_time_parts(df):
    out = df.copy()
    preferred = ("ts", "Date", "date", "datetime", "biz_date")
    ts_col = next((c for c in preferred if c in out.columns), None)
    if not ts_col:
        ts_col = next((c for c in out.columns if _looks_like_time_name(c)), None)
    if not ts_col:
        return out, None
    out["_ts"] = _to_datetime(out[ts_col])
    if "hour" not in out.columns:
        out["hour"] = out["_ts"].dt.hour
    if "weekday" not in out.columns:
        out["weekday"] = out["_ts"].dt.dayofweek.map(WEEKDAY_ZH)
    if "month" not in out.columns:
        out["month"] = out["_ts"].dt.month
    if "year" not in out.columns:
        out["year"] = out["_ts"].dt.year
    if "day" not in out.columns:
        out["day"] = out["_ts"].dt.day
    return out, "_ts"


def _to_datetime(series):
    """尽量兼容各种时间格式：标准时间串、时间戳、紧凑数字串、混合格式等。"""
    s = series
    if pd.api.types.is_datetime64_any_dtype(s):
        return s
    if pd.api.types.is_numeric_dtype(s):
        num = pd.to_numeric(s, errors="coerce")
        valid = num.dropna()
        if len(valid):
            try:
                med = float(valid.abs().median())
            except Exception:
                med = 0.0
            if 1e8 <= med < 1e10:
                return pd.to_datetime(num, unit="s", errors="coerce")
            if 1e11 <= med < 1e13:
                return pd.to_datetime(num, unit="ms", errors="coerce")
        return pd.to_datetime(num, errors="coerce")
    txt = s.astype(str).str.strip()
    txt = txt.replace({"": None, "None": None, "nan": None, "NaT": None, "null": None})
    present = int(txt.notna().sum())
    # 先按常见格式快速解析，命中就不需要逐元素推断
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d",
                "%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y%m%d",
                "%d/%m/%Y", "%m/%d/%Y", "%Y年%m月%d日"):
        try:
            alt = pd.to_datetime(txt, errors="coerce", format=fmt)
        except Exception:
            continue
        if present and int(alt.notna().sum()) == present:
            return alt
    # 混合格式兜底
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return pd.to_datetime(txt, errors="coerce", format="mixed")
        except Exception:
            return pd.to_datetime(txt, errors="coerce")


def _is_time_field(df, field):
    if field not in df.columns:
        return False
    if pd.api.types.is_datetime64_any_dtype(df[field]):
        return True
    if not _looks_like_time_name(field):
        return False
    parsed = _to_datetime(df[field].head(40))
    return float(parsed.notna().mean() or 0) > 0.8


def _bucket_series(ts, grain):
    grain = grain or "day"
    if grain == "month":
        return ts.dt.strftime("%Y-%m")
    if grain == "hour":
        return ts.dt.strftime("%Y-%m-%d %H:00")
    return ts.dt.strftime("%Y-%m-%d")


def _schema_from_df(df):
    cols = []
    for name in list(df.columns):
        s = df[name]
        inferred = "numeric"
        if pd.api.types.is_datetime64_any_dtype(s):
            inferred = "datetime"
        elif not pd.api.types.is_numeric_dtype(s):
            parsed = _to_datetime(s.head(80))
            if parsed.notna().mean() > 0.8:
                inferred = "datetime"
            else:
                nunique = int(s.nunique(dropna=True))
                inferred = "categorical" if nunique <= 80 else "text"
        elif str(name).lower() in TIME_HINTS:
            inferred = "datetime"
        role = "measure" if inferred == "numeric" and str(name).lower() not in DIM_HINTS else "dimension"
        if inferred in ("datetime", "categorical", "text"):
            role = "dimension"
        zh = label_zh_for(name)
        cols.append({
            "name": str(name),
            "label": zh or str(name),
            "header": f"{name}（{zh}）" if zh else str(name),
            "inferred": inferred,
            "role": role,
            "is_time": inferred == "datetime" or str(name).lower() in TIME_HINTS,
        })
    return cols


def list_sources(project_id=None, scenario=None):
    ds_sql = "SELECT id, name, project_id, scenario_code, n_rows, n_cols, origin_type FROM dataset WHERE status=1"
    bun_sql = "SELECT id, name, project_id, scenario_code, n_rows, n_cols FROM dataset_bundle WHERE status=1"
    args_ds, args_bun = [], []
    if project_id:
        ds_sql += " AND project_id=%s"
        bun_sql += " AND project_id=%s"
        args_ds.append(int(project_id))
        args_bun.append(int(project_id))
    if scenario:
        ds_sql += " AND (scenario_code=%s OR scenario_code='generic')"
        bun_sql += " AND (scenario_code=%s OR scenario_code='generic')"
        args_ds.append(scenario)
        args_bun.append(scenario)
    ds_sql += " ORDER BY id DESC"
    bun_sql += " ORDER BY id DESC"
    datasets = []
    for r in query(ds_sql, args_ds):
        item = dict(r)
        item["kind"] = "dataset"
        item["is_live"] = (r.get("origin_type") == "mysql_live")
        datasets.append(item)
    bundles = [dict(r, kind="bundle") for r in query(bun_sql, args_bun)]
    return {"datasets": datasets, "bundles": bundles}


def describe_source(kind, sid):
    df = _load_frame(kind, sid)
    if df is None or df.empty:
        fields = []
    else:
        enriched, _ = _ensure_time_parts(df)
        fields = [c for c in _schema_from_df(enriched) if not c["name"].startswith("_")]
    filters = []
    if df is not None and not df.empty:
        for col in fields:
            name = col["name"]
            if name in SKIP_FIELDS:
                continue
            if name not in df.columns:
                continue
            if col["inferred"] == "categorical" or name.lower() in ("site", "site_name", "event_type", "weather_source"):
                vals = df[name].dropna().astype(str).value_counts().head(40)
                filters.append({"field": name, "label": col["header"], "values": [str(v) for v in vals.index]})
    n_rows = int(len(df)) if df is not None else 0
    if (kind or "dataset") in ("dataset", "live"):
        ds = _live_dataset_row(sid)
        if ds and ds.get("origin_type") == "mysql_live" and ds.get("n_rows"):
            n_rows = int(ds["n_rows"])
    return {
        "kind": kind,
        "id": int(sid),
        "n_rows": n_rows,
        "loaded_rows": int(len(df)) if df is not None else 0,
        "fields": fields,
        "dimensions": [c for c in fields if c["role"] == "dimension" and c["name"] not in SKIP_FIELDS],
        "measures": [c for c in fields if c["role"] == "measure" and c["name"] not in SKIP_FIELDS],
        "filters": filters,
    }


# --------------------------------------------------------------------------- #
# 过滤 / 聚合
# --------------------------------------------------------------------------- #
def _is_temporal(values):
    """判断一列是否能按时间解读（用于时间维度的区间/某一天筛选）。"""
    if pd.api.types.is_datetime64_any_dtype(values):
        return True
    if pd.api.types.is_numeric_dtype(values):
        return False
    parsed = _to_datetime(values)
    return pd.notna(parsed).mean() > 0.8


def _only_date(text):
    """判断给定值是否只到「日」粒度（不含时分秒）。"""
    raw = str(text or "").strip()
    if not raw:
        return False
    return not any(ch in raw for ch in (":", "T")) and len(raw) <= 10


def _apply_filters(df, filters):
    out = df
    for flt in filters or []:
        if not isinstance(flt, dict):
            continue
        field = flt.get("field")
        if not field or field not in out.columns:
            continue
        op = (flt.get("op") or flt.get("type") or "eq").lower()
        value = flt.get("value")
        value2 = flt.get("value2")
        if value in (None, "", [], [None, None]):
            continue
        series = out[field]
        temporal = flt.get("kind") == "time" or _is_temporal(series)

        if op == "ondate":
            # 某一天（整天范围）
            day = pd.to_datetime(value, errors="coerce")
            if pd.isna(day):
                continue
            ts = _to_datetime(series)
            out = out[ts.dt.normalize() == day.normalize()]
        elif op in ("daterange",) and isinstance(value, (list, tuple)) and len(value) >= 2:
            ts = _to_datetime(series)
            start = pd.to_datetime(value[0], errors="coerce")
            end = pd.to_datetime(value[1], errors="coerce")
            mask = pd.Series(True, index=out.index)
            if pd.notna(start):
                mask &= ts >= start.normalize()
            if pd.notna(end):
                mask &= ts <= (end.normalize() + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))
            out = out[mask]
        elif op == "month":
            # 某个年月（如 2026-01）
            raw = str(value or "").strip()[:7]
            if not raw:
                continue
            out = out[_to_datetime(series).dt.strftime("%Y-%m") == raw]
        elif op == "between":
            if temporal and not pd.api.types.is_numeric_dtype(series):
                ts = _to_datetime(series)
                lo = pd.to_datetime(value if not isinstance(value, (list, tuple)) else value[0], errors="coerce")
                hi_raw = value2 if value2 not in (None, "") else (
                    value[1] if isinstance(value, (list, tuple)) and len(value) >= 2 else None)
                hi = pd.to_datetime(hi_raw, errors="coerce")
                if pd.isna(lo) or pd.isna(hi):
                    continue
                out = out[(ts >= lo.normalize()) & (ts <= hi.normalize() + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))]
            else:
                num = pd.to_numeric(series, errors="coerce")
                lo = _to_number(value)
                hi = _to_number(value2 if value2 not in (None, "") else (
                    value[1] if isinstance(value, (list, tuple)) and len(value) >= 2 else None))
                if isinstance(value, (list, tuple)) and len(value) >= 2:
                    lo = _to_number(value[0])
                    hi = _to_number(value[1])
                if lo is None or hi is None:
                    continue
                if lo > hi:
                    lo, hi = hi, lo
                out = out[num.between(lo, hi)]
        elif op in ("in", "select", "multiselect"):
            vals = value if isinstance(value, (list, tuple, set)) else [value]
            vals = [str(v) for v in vals if v not in (None, "")]
            if vals:
                if temporal:
                    keys = _to_datetime(series).dt.strftime("%Y-%m-%d")
                    out = out[keys.isin(vals)]
                else:
                    out = out[series.astype(str).isin(vals)]
        elif op in ("gt", "gte", "lt", "lte"):
            if temporal and not pd.api.types.is_numeric_dtype(series):
                ts = _to_datetime(series)
                v = pd.to_datetime(value, errors="coerce")
                if pd.isna(v):
                    continue
                if op == "gt":
                    out = out[ts > v]
                elif op == "gte":
                    out = out[ts >= v.normalize()]
                elif op == "lt":
                    out = out[ts < v.normalize()]
                else:
                    out = out[ts <= v.normalize() + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)]
            else:
                num = pd.to_numeric(series, errors="coerce")
                v = _to_number(value)
                if v is None:
                    continue
                if op == "gt":
                    out = out[num > v]
                elif op == "gte":
                    out = out[num >= v]
                elif op == "lt":
                    out = out[num < v]
                else:
                    out = out[num <= v]
        elif op == "contains":
            out = out[series.astype(str).str.contains(str(value), case=False, na=False, regex=False)]
        elif op == "ne":
            if temporal and _only_date(value):
                out = out[_to_datetime(series).dt.strftime("%Y-%m-%d") != str(value).strip()]
            elif temporal:
                out = out[_to_datetime(series) != pd.to_datetime(value, errors="coerce")]
            else:
                out = out[series.astype(str) != str(value)]
        else:
            if temporal and _only_date(value):
                out = out[_to_datetime(series).dt.strftime("%Y-%m-%d") == str(value).strip()]
            elif temporal:
                target = pd.to_datetime(value, errors="coerce")
                out = out[_to_datetime(series) == target]
            else:
                out = out[series.astype(str) == str(value)]
    return out


def _to_number(value):
    if value is None or value == "":
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _agg_series(s, how):
    how = (how or "avg").lower()
    if how == "sum":
        return s.sum()
    if how == "max":
        return s.max()
    if how == "min":
        return s.min()
    if how == "count":
        return s.count()
    if how == "median":
        return s.median()
    if how == "nunique":
        return s.nunique(dropna=True)
    return s.mean()


# --------------------------------------------------------------------------- #
# 组件查询
# --------------------------------------------------------------------------- #
def _dim_alias(field, used):
    alias = str(field)
    if alias not in used:
        used.add(alias)
        return alias
    idx = 2
    while f"{field}_{idx}" in used:
        idx += 1
    alias = f"{field}_{idx}"
    used.add(alias)
    return alias


def query_widget(widget, grain=None, filters=None, limit=4000):
    widget = normalize_widget(widget or {})
    empty = {"columns": [], "records": [], "n": 0, "kpis": []}
    src = widget.get("source") or {}
    if not src.get("id"):
        return empty
    df = _load_frame(src.get("kind") or "dataset", src["id"])
    if df is None or df.empty:
        return empty
    df, _ts_name = _ensure_time_parts(df)

    dims_cfg = widget.get("dims") or []
    measures = [m for m in (widget.get("measures") or []) if m.get("field")]

    merged_filters = list(filters or []) + list(widget.get("filters") or [])
    for d in dims_cfg:
        dkind = d.get("kind") or "dim"
        for flt in d.get("filters") or []:
            if not isinstance(flt, dict):
                continue
            item = dict(flt)
            item.setdefault("field", d.get("field"))
            item.setdefault("kind", dkind)
            merged_filters.append(item)
    df = _apply_filters(df, merged_filters)

    if "event_type" in df.columns:
        df["event_type"] = df["event_type"].fillna("正常").replace("", "正常")

    wtype = widget.get("type") or "line"
    grain = grain or widget.get("grain")

    # 构建维度列
    group_cols = []
    dim_labels = {}
    used = set()
    for d in dims_cfg:
        field = d.get("field")
        if field not in df.columns:
            continue
        split = d.get("split") or "none"
        alias = _dim_alias(field, used)
        field_zh = label_zh_for(field) or field
        if split in TIME_SPLIT_FORMAT:
            bucket = _to_datetime(df[field]).dt.strftime(TIME_SPLIT_FORMAT[split])
            df[alias] = bucket.fillna("")
            dim_labels[alias] = f"{field_zh}（{TIME_SPLIT_LABEL.get(split, split)}）"
        elif _is_time_field(df, field) and grain:
            df[alias] = _bucket_series(_to_datetime(df[field]), grain)
            dim_labels[alias] = "时间"
        else:
            s = df[field]
            if pd.api.types.is_datetime64_any_dtype(s):
                df[alias] = s.dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                df[alias] = s.astype(str)
            dim_labels[alias] = field_zh
        group_cols.append(alias)

    # KPI（不分组）
    kpis = []
    for m in measures:
        field = m["field"]
        if field not in df.columns:
            continue
        series = pd.to_numeric(df[field], errors="coerce")
        kpis.append({
            "field": field,
            "label": label_zh_for(field) or field,
            "agg": m.get("agg") or "avg",
            "value": json_safe(_agg_series(series, m.get("agg") or "avg")),
        })

    if wtype == "kpi" or (not group_cols and wtype != "scatter" and wtype != "table"):
        return {"columns": [k["field"] for k in kpis], "records": [], "n": int(len(df)), "kpis": kpis}

    if wtype == "scatter":
        cols = [m["field"] for m in measures[:2] if m["field"] in df.columns]
        color = (widget.get("color_field") or None)
        keep = [c for c in cols + ([color] if color and color in df.columns else []) if c]
        sample = df[keep].dropna().head(min(limit, 3000))
        records = [{c: json_safe(row[c]) for c in keep} for _, row in sample.iterrows()]
        return {"columns": keep, "records": records, "n": int(len(sample)), "kpis": kpis}

    if wtype == "table" and not measures:
        cols = [c for c in (group_cols or list(df.columns)[:12]) if c in df.columns][:12]
        sample = df[cols].head(min(limit, 200))
        records = [{c: json_safe(row[c]) for c in cols} for _, row in sample.iterrows()]
        return {"columns": cols, "records": records, "n": int(len(sample)), "kpis": kpis}

    if not measures:
        return {"columns": group_cols, "records": [], "n": int(len(df)), "kpis": []}

    named = {}
    for i, m in enumerate(measures):
        field = m["field"]
        if field not in df.columns:
            continue
        agg = (m.get("agg") or "avg").lower()
        alias = f"{field}__{agg}"
        if alias in named:
            alias = f"{field}__{agg}_{i}"
        df[alias] = pd.to_numeric(df[field], errors="coerce")
        named[alias] = {"field": field, "agg": agg}
    if not named:
        return {"columns": group_cols, "records": [], "n": 0, "kpis": kpis}

    pandas_agg = {a: _PANDAS_AGG.get(named[a]["agg"], "mean") for a in named}
    if group_cols:
        out = df.groupby(group_cols, dropna=False).agg(pandas_agg).reset_index()
    else:
        row = {a: json_safe(_agg_series(df[a], named[a]["agg"])) for a in named}
        out = pd.DataFrame([row])

    sort_col = next(iter(named))
    time_sorted = False
    if group_cols and group_cols[0] in out.columns:
        if wtype in ("line", "area", "combo", "table"):
            out = out.sort_values(group_cols[0])
            time_sorted = True
        else:
            out = out.sort_values(sort_col, ascending=False, na_position="last")
    # 时间趋势保留最近 limit 个点，其余保留前 limit 条
    out = out.tail(limit) if time_sorted else out.head(limit)

    columns = list(out.columns)
    records = []
    for _, row in out.iterrows():
        records.append({c: json_safe(row[c]) for c in columns})
    labels = dict(dim_labels)
    for alias, m in named.items():
        labels[alias] = f"{label_zh_for(m['field']) or m['field']}({m['agg']})"
    return {
        "columns": columns,
        "records": records,
        "n": int(len(out)),
        "kpis": kpis,
        "labels": labels,
        "dim_fields": group_cols,
        "measure_fields": list(named.keys()),
        "raw_measures": [
            {"field": m["field"], "agg": m.get("agg") or "avg", "alias": f"{m['field']}__{m.get('agg') or 'avg'}"}
            for m in measures
        ],
    }


# --------------------------------------------------------------------------- #
# 看板 CRUD
# --------------------------------------------------------------------------- #
def _legacy_layout(board):
    metrics = board.get("metrics") or ["temp_c"]
    source = None
    if board.get("dataset_id"):
        source = {"kind": "dataset", "id": int(board["dataset_id"])}
    elif board.get("binding_id"):
        source = {"kind": "binding", "id": int(board["binding_id"])}
    widgets = [{
        "id": "w_main",
        "type": board.get("chart_type") or "line",
        "title": board.get("name") or "趋势",
        "x": 0, "y": 0, "w": 12, "h": 6,
        "source": source,
        "dims": [_dim("ts", "year_month_day_hour")],
        "measures": [{"field": m, "agg": "avg"} for m in metrics],
        "filters": [],
    }]
    return {
        "theme": "finebi",
        "grain": board.get("grain") or "hour",
        "filters": [],
        "widgets": widgets,
        "default_source": source,
    }


def serialize(row):
    if not row:
        return None
    data = row_to_dict(row)
    data["metrics"] = loads(row.get("metrics_json"), default=["temp_c", "wind_100m", "radiation", "precip_mm"])
    data["horizons"] = loads(row.get("horizons_json"), default=["short_1_3d", "midlong_7_45d"])
    layout = data.get("layout")
    if isinstance(layout, str):
        layout = loads(layout, default=None)
    if not isinstance(layout, dict) or not isinstance(layout.get("widgets"), list):
        layout = _legacy_layout(data)
    layout.setdefault("theme", "finebi")
    layout.setdefault("grain", data.get("grain") or "day")
    layout.setdefault("filters", [])
    layout["widgets"] = [normalize_widget(w) for w in (layout.get("widgets") or [])]
    data["layout"] = layout
    data["widget_count"] = len(layout.get("widgets") or [])
    return data


def list_boards(scenario=None):
    sql = "SELECT * FROM bi_board WHERE status=1"
    args = []
    if scenario:
        sql += " AND (scenario_code=%s OR scenario_code='generic' OR scenario_code IS NULL OR scenario_code='')"
        args.append(scenario)
    sql += " ORDER BY is_template DESC, id DESC"
    return [serialize(r) for r in query(sql, args)]


def get_board(bid):
    return serialize(query("SELECT * FROM bi_board WHERE id=%s", (bid,), one=True))


def save_board(payload, bid=None):
    user = _user()
    layout = payload.get("layout")
    if not isinstance(layout, dict):
        layout = _empty_layout()
    layout["widgets"] = [normalize_widget(w) for w in (layout.get("widgets") or [])]
    layout.setdefault("filters", [])
    src = layout.get("default_source") or {}
    dataset_id = payload.get("dataset_id")
    binding_id = payload.get("binding_id")
    if src.get("kind") in ("dataset", "live") and src.get("id"):
        dataset_id = dataset_id or int(src["id"])
    if src.get("kind") == "binding" and src.get("id"):
        binding_id = binding_id or int(src["id"])
    metrics = payload.get("metrics")
    if not metrics:
        measures = []
        for w in layout.get("widgets") or []:
            for m in w.get("measures") or []:
                if m.get("field"):
                    measures.append(m["field"])
        metrics = list(dict.fromkeys(measures))[:8] or ["temp_c"]
    data = {
        "name": payload.get("name") or "未命名看板",
        "description": payload.get("description") or "",
        "project_id": payload.get("project_id"),
        "dataset_id": dataset_id,
        "binding_id": binding_id,
        "grain": payload.get("grain") or layout.get("grain") or "day",
        "metrics_json": dumps(metrics),
        "horizons_json": dumps(payload.get("horizons") or ["short_1_3d", "midlong_7_45d"]),
        "chart_type": payload.get("chart_type") or "line",
        "layout_json": dumps(layout),
        "scenario_code": payload.get("scenario_code") or "generic",
        "is_template": 1 if payload.get("is_template") else 0,
        "published": 0 if payload.get("published") == 0 else 1,
        "cover_color": payload.get("cover_color") or "#1d6fd8",
        "user_id": payload.get("user_id") or user.get("id"),
        "username": payload.get("username") or user.get("username") or "system",
        "status": 1,
    }
    if bid:
        update("bi_board", data, "id=%s", (bid,))
        return get_board(bid)
    return get_board(insert("bi_board", data))


def delete_board(bid):
    update("bi_board", {"status": 0}, "id=%s", (bid,))


def query_board_layout(bid, grain=None, filters=None, widget_id=None):
    board = get_board(bid)
    if not board:
        raise ValueError("看板不存在")
    layout = board.get("layout") or _empty_layout()
    grain = grain or layout.get("grain") or board.get("grain") or "day"
    global_filters = list(layout.get("filters") or [])
    if filters:
        by_field = {f.get("field"): f for f in global_filters if f.get("field")}
        for flt in filters:
            if flt.get("field") in by_field:
                by_field[flt["field"]]["value"] = flt.get("value")
            else:
                global_filters.append(flt)
    widgets = layout.get("widgets") or []
    if widget_id:
        widgets = [w for w in widgets if w.get("id") == widget_id]
    items = []
    for w in widgets:
        src = w.get("source") or layout.get("default_source")
        widget = dict(w)
        widget["source"] = src
        t0 = time.time()
        try:
            data = query_widget(widget, grain=grain, filters=global_filters)
            err = None
        except Exception as e:
            data = {"columns": [], "records": [], "n": 0, "kpis": []}
            err = str(e)
        items.append({
            "widget": normalize_widget(widget),
            "data": data,
            "error": err,
            "elapsed_ms": int((time.time() - t0) * 1000),
        })
    return {"board": board, "grain": grain, "items": items}


def query_ad_hoc(payload):
    widget = {
        "type": payload.get("type") or "line",
        "source": payload.get("source") or {},
        "dims": payload.get("dims") or payload.get("dimensions") or [],
        "measures": payload.get("measures") or [],
        "filters": payload.get("filters") or [],
        "color_field": payload.get("color_field"),
        "grain": payload.get("grain"),
    }
    return query_widget(widget, grain=payload.get("grain"), filters=payload.get("global_filters"))


# --------------------------------------------------------------------------- #
# 布局模板
# --------------------------------------------------------------------------- #
def recommend_layout(kind, sid, title=None):
    info = describe_source(kind, sid)
    src = {"kind": kind, "id": int(sid)}
    measures = [c["name"] for c in info["measures"]][:6]
    dims = [c["name"] for c in info["dimensions"]]
    derived_time = {"hour", "year", "month", "day", "weekday"}
    time_dim = next((c["name"] for c in info["dimensions"] if c.get("is_time") and c["name"].lower() not in derived_time), None)
    cat_dim = next((d for d in dims if d != time_dim and d.lower() not in TIME_HINTS and d.lower() not in derived_time), None)
    widgets = []
    x = 0
    for m in measures[:4]:
        widgets.append(_widget("kpi", f"平均{label_zh_for(m) or m}", src, [], [{"field": m, "agg": "avg"}], x, 0, 3, 2))
        x += 3
    y = 2
    if time_dim and measures:
        widgets.append(_widget("line", "趋势", src, [_dim(time_dim, "year_month_day_hour")],
                               [{"field": m, "agg": "avg"} for m in measures[:3]], 0, y, 8, 5))
        if cat_dim:
            widgets.append(_widget("bar", "对比", src, [_dim(cat_dim)],
                                   [{"field": measures[0], "agg": "avg"}], 8, y, 4, 5))
        y += 5
    if cat_dim and measures:
        widgets.append(_widget("pie", f"{label_zh_for(cat_dim) or cat_dim}构成", src,
                               [_dim(cat_dim)], [{"field": measures[0], "agg": "sum"}], 0, y, 5, 4))
        widgets.append(_widget("table", "明细", src, [_dim(time_dim, "year_month_day_hour")] if time_dim else [],
                               [{"field": m, "agg": "avg"} for m in measures[:3]], 5, y, 7, 4))
    return {
        "theme": "finebi",
        "grain": "day" if time_dim else None,
        "filters": _default_filters(info),
        "widgets": widgets,
        "default_source": src,
        "title": title or "智能生成看板",
    }


def _default_filters(info):
    out = []
    names = {c["name"] for c in info.get("fields") or []}
    if "site_name" in names:
        out.append({"id": "flt_site", "field": "site_name", "type": "select", "label": "站点", "value": None})
    elif "site" in names:
        out.append({"id": "flt_site", "field": "site", "type": "select", "label": "站点", "value": None})
    if "ts" in names:
        out.append({"id": "flt_ts", "field": "ts", "type": "daterange", "label": "时间", "value": None})
    return out


def power_monitor_layout(source):
    src = {"kind": source["kind"], "id": int(source["id"])}
    return {
        "theme": "finebi",
        "grain": "day",
        "filters": [
            {"id": "flt_site", "field": "site_name", "type": "select", "label": "站点", "value": None},
            {"id": "flt_ts", "field": "ts", "type": "daterange", "label": "时间", "value": None},
        ],
        "default_source": src,
        "widgets": [
            _widget("kpi", "平均气温", src, [], [{"field": "temp_c", "agg": "avg"}], 0, 0, 3, 2, {"unit": "℃"}),
            _widget("kpi", "平均负荷", src, [], [{"field": "load_mw", "agg": "avg"}], 3, 0, 3, 2, {"unit": "MW"}),
            _widget("kpi", "平均风光出力", src, [], [{"field": "renewable_mw", "agg": "avg"}], 6, 0, 3, 2, {"unit": "MW"}),
            _widget("kpi", "平均日前电价", src, [], [{"field": "price_da", "agg": "avg"}], 9, 0, 3, 2, {"unit": "元/MWh"}),
            _widget("combo", "负荷 · 风光出力 · 日前电价（年月日时）", src, [_dim("ts", "year_month_day_hour")], [
                {"field": "load_mw", "agg": "avg"},
                {"field": "renewable_mw", "agg": "avg"},
                {"field": "price_da", "agg": "avg"},
            ], 0, 2, 8, 5, {"secondary": ["price_da"]}),
            _widget("bar", "分站点负荷 / 出力 / 电价", src, [_dim("site_name")], [
                {"field": "load_mw", "agg": "avg"},
                {"field": "renewable_mw", "agg": "avg"},
                {"field": "price_da", "agg": "avg"},
            ], 8, 2, 4, 5),
            _widget("line", "气象驱动层 · 气温 / 风速 / 辐照（年月日）", src, [_dim("ts", "year_month_day")], [
                {"field": "temp_c", "agg": "avg"},
                {"field": "wind_10m", "agg": "avg"},
                {"field": "radiation", "agg": "avg"},
            ], 0, 7, 7, 4),
            _widget("scatter", "残余负荷 vs 日前电价", src, [], [
                {"field": "residual_mw", "agg": "avg"},
                {"field": "price_da", "agg": "avg"},
            ], 7, 7, 5, 4, {"color_field": "event_type"}),
            _widget("heatmap", "电价热力 · 小时 × 星期", src, [_dim("hour"), _dim("weekday")], [
                {"field": "price_da", "agg": "avg"},
            ], 0, 11, 7, 4),
            _widget("pie", "极端事件小时构成", src, [_dim("event_type")], [
                {"field": "load_mw", "agg": "count"},
            ], 7, 11, 5, 4),
        ],
    }


def realtime_layout(source):
    """实时看板：直连 MySQL 活表，刷新即读最新数据。"""
    src = {"kind": source["kind"], "id": int(source["id"])}
    return {
        "theme": "finebi",
        "grain": "hour",
        "realtime": True,
        "filters": [
            {"id": "flt_site", "field": "site_name", "type": "select", "label": "站点", "value": None},
        ],
        "default_source": src,
        "widgets": [
            _widget("kpi", "当前平均负荷", src, [], [{"field": "load_mw", "agg": "avg"}], 0, 0, 3, 2, {"unit": "MW"}),
            _widget("kpi", "当前风光出力", src, [], [{"field": "renewable_mw", "agg": "avg"}], 3, 0, 3, 2, {"unit": "MW"}),
            _widget("kpi", "当前日前电价", src, [], [{"field": "price_da", "agg": "avg"}], 6, 0, 3, 2, {"unit": "元/MWh"}),
            _widget("kpi", "当前气温", src, [], [{"field": "temp_c", "agg": "avg"}], 9, 0, 3, 2, {"unit": "℃"}),
            _widget("combo", "实时负荷 · 风光出力 · 电价（按小时）", src, [_dim("ts", "year_month_day_hour")], [
                {"field": "load_mw", "agg": "avg"},
                {"field": "renewable_mw", "agg": "avg"},
                {"field": "price_da", "agg": "avg"},
            ], 0, 2, 8, 5, {"secondary": ["price_da"]}),
            _widget("bar", "分站点实时负荷", src, [_dim("site_name")], [
                {"field": "load_mw", "agg": "avg"},
                {"field": "renewable_mw", "agg": "avg"},
            ], 8, 2, 4, 5),
            _widget("line", "最近负荷 / 光伏 / 风电（按小时）", src, [_dim("ts", "year_month_day_hour")], [
                {"field": "load_mw", "agg": "avg"},
                {"field": "solar_mw", "agg": "avg"},
                {"field": "wind_mw", "agg": "avg"},
            ], 0, 7, 7, 4),
            _widget("hbar", "站点光伏出力排行", src, [_dim("site_name")], [
                {"field": "solar_mw", "agg": "sum"},
            ], 7, 7, 5, 4),
            _widget("table", "最新小时明细", src, [_dim("ts", "year_month_day_hour"), _dim("site_name")], [
                {"field": "load_mw", "agg": "avg"},
                {"field": "renewable_mw", "agg": "avg"},
                {"field": "price_da", "agg": "avg"},
            ], 0, 11, 12, 4),
        ],
    }


def apply_template(key, source, name=None):
    key = key or "blank"
    if key == "power_monitor":
        layout = power_monitor_layout(source)
    elif key == "realtime":
        layout = realtime_layout(source)
    elif key == "trend":
        layout = recommend_layout(source["kind"], source["id"])
        layout["widgets"] = [w for w in layout["widgets"] if w["type"] in ("kpi", "line", "table")]
    elif key == "composition":
        info = describe_source(source["kind"], source["id"])
        src = {"kind": source["kind"], "id": int(source["id"])}
        measures = [c["name"] for c in info["measures"]][:2]
        cat = next((c["name"] for c in info["dimensions"] if c["name"].lower() not in TIME_HINTS), None)
        widgets = []
        if cat and measures:
            widgets.append(_widget("pie", "构成", src, [_dim(cat)], [{"field": measures[0], "agg": "sum"}], 0, 0, 5, 5))
            widgets.append(_widget("bar", "对比", src, [_dim(cat)], [{"field": measures[0], "agg": "avg"}], 5, 0, 7, 5))
            widgets.append(_widget("hbar", "排行", src, [_dim(cat)], [{"field": measures[0], "agg": "sum"}], 0, 5, 12, 4))
        layout = {"theme": "finebi", "grain": "day", "filters": _default_filters(info), "widgets": widgets, "default_source": src}
    else:
        layout = _empty_layout()
        layout["default_source"] = {"kind": source["kind"], "id": int(source["id"])} if source and source.get("id") else None
        if source and source.get("id"):
            info = describe_source(source["kind"], source["id"])
            layout["filters"] = _default_filters(info)
    return layout


def _find_power_source():
    ds = query(
        "SELECT id, name, project_id FROM dataset WHERE name=%s AND status=1 ORDER BY id DESC",
        ("负荷风光训练宽表",),
        one=True,
    )
    if ds:
        return {"kind": "dataset", "id": ds["id"], "project_id": ds.get("project_id"), "name": ds["name"]}
    bun = query(
        "SELECT id, name, project_id FROM dataset_bundle WHERE name=%s AND status=1 ORDER BY id DESC",
        ("气象 × 负荷 × 风光",),
        one=True,
    )
    if bun:
        return {"kind": "bundle", "id": bun["id"], "project_id": bun.get("project_id"), "name": bun["name"]}
    ds = query(
        "SELECT id, name, project_id FROM dataset WHERE name=%s AND status=1 ORDER BY id DESC",
        ("气象与极端事件",),
        one=True,
    )
    if ds:
        return {"kind": "dataset", "id": ds["id"], "project_id": ds.get("project_id"), "name": ds["name"]}
    return None


def ensure_power_monitor_board():
    source = _find_power_source()
    if not source:
        return None
    layout = power_monitor_layout(source)
    payload = {
        "name": "气象-负荷-出力-电价监测看板",
        "description": "离线气象/负荷/风光/电价四联监测：维度可自由拆分（年/年月/年月日/年月日时）、指标可换聚合、维度可加筛选。",
        "project_id": source.get("project_id"),
        "dataset_id": source["id"] if source["kind"] == "dataset" else None,
        "layout": layout,
        "grain": "day",
        "scenario_code": "power_trading",
        "cover_color": "#0f766e",
        "published": 1,
    }
    row = query("SELECT * FROM bi_board WHERE name=%s AND status=1", (payload["name"],), one=True)
    if row:
        return save_board(payload, row["id"])
    return save_board(payload)


def ensure_realtime_board():
    from services import live_ops
    pack = live_ops.lookup_live_assets()
    ds = (pack or {}).get("dataset") or {}
    if not ds.get("id"):
        return None
    src = {"kind": "dataset", "id": int(ds["id"])}
    layout = realtime_layout(src)
    payload = {
        "name": "电力实时监测看板（实时库表）",
        "description": f"直连 MySQL 实时库 {live_ops.LIVE_DB}.{live_ops.LIVE_TABLE}，每次打开或刷新都会读取当前最新小时数据。",
        "project_id": (pack.get("project") or {}).get("id"),
        "dataset_id": int(ds["id"]),
        "layout": layout,
        "grain": "hour",
        "scenario_code": "power_trading",
        "cover_color": "#0ea5e9",
        "published": 1,
    }
    row = query("SELECT * FROM bi_board WHERE name=%s AND status=1", (payload["name"],), one=True)
    if row:
        return save_board(payload, row["id"])
    return save_board(payload)


def ensure_weather_board(dataset_id, binding_id=None):
    source = {"kind": "binding" if binding_id else "dataset", "id": int(binding_id or dataset_id)}
    if not binding_id:
        source = {"kind": "dataset", "id": int(dataset_id)}
    layout = {
        "theme": "finebi",
        "grain": "hour",
        "filters": [{"id": "flt_ts", "field": "ts", "type": "daterange", "label": "时间", "value": None}],
        "default_source": {"kind": "dataset", "id": int(dataset_id)} if dataset_id else source,
        "widgets": [
            _widget("line", "气象预报", {"kind": "dataset", "id": int(dataset_id)} if dataset_id else source,
                    [_dim("ts", "year_month_day_hour")],
                    [{"field": m, "agg": "avg"} for m in ("temp_c", "wind_100m", "radiation", "precip_mm")],
                    0, 0, 12, 6),
        ],
    }
    payload = {
        "name": "气象预报看板",
        "description": "按小时/天/月查看温度、风速、辐照、降水。",
        "dataset_id": dataset_id,
        "binding_id": binding_id,
        "grain": "hour",
        "metrics": ["temp_c", "wind_100m", "radiation", "precip_mm"],
        "horizons": ["short_1_3d", "midlong_7_45d"],
        "chart_type": "line",
        "layout": layout,
        "scenario_code": "power_trading",
        "cover_color": "#0284c7",
    }
    row = query("SELECT * FROM bi_board WHERE name=%s AND status=1", ("气象预报看板",), one=True)
    if row:
        return save_board(payload, row["id"])
    from services.weather_asset import ensure_weather_space
    space = ensure_weather_space()
    payload["project_id"] = space["id"]
    return save_board(payload)


# --------------------------------------------------------------------------- #
# 旧气象看板折线接口
# --------------------------------------------------------------------------- #
def _expand_horizons(keys):
    out = []
    for k in keys or []:
        if k == "midlong_7_45d":
            out.extend(["medium_7_16d", "long_17_45d"])
        else:
            out.append(k)
    return list(dict.fromkeys(out))


def query_board(bid, grain=None, metrics=None, horizons=None):
    """兼容旧气象看板折线接口。"""
    board = get_board(bid)
    if not board:
        raise ValueError("看板不存在")
    grain = grain or board.get("grain") or "hour"
    metrics = metrics or board.get("metrics") or []
    horizons = horizons or board.get("horizons") or []
    df = _load_board_frame(board)
    if df is None or df.empty:
        return {"board": board, "points": [], "grain": grain, "metrics": metrics, "horizons": horizons}

    if "ts" in df.columns:
        df["ts"] = _to_datetime(df["ts"])
        df = df.dropna(subset=["ts"])
    hz_ok = _expand_horizons(horizons)
    if hz_ok and "horizon" in df.columns:
        df = df[df["horizon"].isin(hz_ok)]

    if grain == "month":
        df["bucket"] = df["ts"].dt.strftime("%Y-%m")
    elif grain == "day":
        df["bucket"] = df["ts"].dt.strftime("%Y-%m-%d")
    else:
        df["bucket"] = df["ts"].dt.strftime("%Y-%m-%d %H:00")

    use_cols = [c for c in metrics if c in df.columns]
    if not use_cols:
        return {"board": board, "points": [], "grain": grain, "metrics": metrics, "horizons": horizons}
    grouped = df.groupby("bucket", as_index=False)[use_cols].mean(numeric_only=True)
    grouped = grouped.sort_values("bucket")
    points = []
    for _, row in grouped.iterrows():
        item = {"t": row["bucket"]}
        for c in use_cols:
            val = row[c]
            item[c] = None if pd.isna(val) else round(float(val), 3)
        points.append(item)
    return {
        "board": board,
        "points": points,
        "grain": grain,
        "metrics": use_cols,
        "horizons": horizons,
        "catalog": catalog(),
        "n": len(points),
    }
