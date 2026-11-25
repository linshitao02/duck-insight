# -*- coding: utf-8 -*-
"""把气象采集结果导入数据空间，并套用清洗规则。"""
from datetime import datetime, timedelta

import pandas as pd

from utils.db import insert, query
from utils.jsonx import dumps

WEATHER_SPACE = "华东气象数据空间"
WEATHER_TABLE = "气象多源小时序列"
WEATHER_RULE = "气象时序质控"

HORIZON_LABEL = {
    "actual": "实况",
    "short_1_3d": "短期1-3天",
    "medium_7_16d": "中期7-16天",
    "long_17_45d": "中长期17-45天",
}

WEATHER_RULE_STEPS = [
    {"op": "parse_date", "column": "ts", "extract": ["year", "month", "day", "weekday", "hour", "minute", "second"], "skip_if_missing": True},
    {"op": "clip_outlier", "method": "range", "ranges": [
        {"columns": ["temp_c"], "method": "range", "low": -30, "high": 48},
        {"columns": ["wind_10m", "wind_100m", "wind_gust"], "method": "range", "low": 0, "high": 55},
        {"columns": ["precip_mm"], "method": "range", "low": 0, "high": 80},
        {"columns": ["radiation"], "method": "range", "low": 0, "high": 1200},
    ]},
    {"op": "fill_missing", "strategy": "auto"},
    {"op": "drop_duplicates", "columns": ["ts", "horizon"]},
]


def ensure_weather_space():
    row = query("SELECT * FROM data_project WHERE name=%s AND status=1", (WEATHER_SPACE,), one=True)
    if row:
        return row
    pid = insert("data_project", {
        "name": WEATHER_SPACE,
        "description": "Open-Meteo 多源气象（ERA5/ECMWF/GFS/气候态）采集、质控与预报产物。",
        "scenario_code": "power_trading",
        "username": "system",
        "status": 1,
    })
    return query("SELECT * FROM data_project WHERE id=%s", (pid,), one=True)


def ensure_weather_rule():
    row = query("SELECT * FROM clean_rule WHERE name=%s AND status=1", (WEATHER_RULE,), one=True)
    if row:
        from utils.db import update
        update("clean_rule", {
            "scenario_code": "power_trading",
            "description": "物理阈值裁剪、日期拆解到小时、缺失填补。对应气象治理质控。",
            "steps_json": dumps(WEATHER_RULE_STEPS),
            "is_preset": 1,
            "status": 1,
        }, "id=%s", (row["id"],))
        return query("SELECT * FROM clean_rule WHERE id=%s", (row["id"],), one=True)
    rid = insert("clean_rule", {
        "name": WEATHER_RULE,
        "scenario_code": "power_trading",
        "description": "物理阈值裁剪、日期拆解到小时、缺失填补。对应气象治理质控。",
        "steps_json": dumps(WEATHER_RULE_STEPS),
        "is_preset": 1,
        "username": "system",
        "status": 1,
    })
    return query("SELECT * FROM clean_rule WHERE id=%s", (rid,), one=True)


def hourly_frame():
    rows = query("SELECT * FROM power_hourly ORDER BY ts", []) or []
    if not rows:
        return pd.DataFrame()
    records = []
    for r in rows:
        ts = r.get("ts")
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ts, "strftime") else str(ts)[:19]
        hz = r.get("horizon") or "actual"
        records.append({
            "ts": ts_str,
            "horizon": hz,
            "horizon_label": HORIZON_LABEL.get(hz, hz),
            "temp_c": _f(r.get("temp_c")),
            "humidity": _f(r.get("humidity")),
            "precip_mm": _f(r.get("precip_mm")),
            "wind_10m": _f(r.get("wind_10m")),
            "wind_100m": _f(r.get("wind_100m")),
            "wind_gust": _f(r.get("wind_gust")),
            "radiation": _f(r.get("radiation")),
            "weather_code": r.get("weather_code"),
            "source": r.get("source_json"),
        })
    return pd.DataFrame(records)


def _f(v):
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def export_to_space():
    from services import dataset_service as ds_svc
    space = ensure_weather_space()
    df = hourly_frame()
    if df.empty:
        raise ValueError("尚无气象小时序列，请先采集 Open-Meteo")
    ds = ds_svc.upsert_dataframe(
        space["id"],
        WEATHER_TABLE,
        df,
        scenario="power_trading",
        remark="Open-Meteo ERA5/ECMWF/GFS/气候态，逐小时温度、风速、辐照、降水",
        filename="weather_hourly.csv",
    )
    return {"project": space, "dataset": ds}


def apply_weather_clean():
    from services import clean_service
    space = ensure_weather_space()
    rule = ensure_weather_rule()
    ds = query(
        "SELECT * FROM dataset WHERE project_id=%s AND name=%s AND status=1 ORDER BY id DESC",
        (space["id"], WEATHER_TABLE),
        one=True,
    )
    if not ds:
        raise ValueError("请先把气象序列导入数据空间")
    old = query(
        "SELECT id FROM dataset_binding WHERE target_type='dataset' AND target_id=%s AND rule_id=%s",
        (ds["id"], rule["id"]),
        one=True,
    )
    if old:
        from utils.db import delete
        delete("dataset_binding", "id=%s", (old["id"],))
    binding = clean_service.bind_and_materialize(
        "dataset", ds["id"], rule["id"], name=f"{WEATHER_TABLE}-{WEATHER_RULE}"
    )
    return {"dataset": ds, "rule": rule, "binding": binding}


def ingest_if_stale(max_age_minutes=120):
    from services import power_engine
    row = query("SELECT MAX(create_time) AS t FROM power_hourly", one=True) or {}
    latest = row.get("t")
    if latest:
        if not isinstance(latest, datetime):
            try:
                latest = datetime.fromisoformat(str(latest)[:19])
            except Exception:
                latest = None
        if latest and datetime.now() - latest < timedelta(minutes=max_age_minutes):
            n = query("SELECT COUNT(*) AS c FROM power_hourly", one=True) or {}
            return {"skipped": True, "rows": n.get("c") or 0, "reason": "数据仍新鲜"}
    return power_engine.ingest_and_materialize()


def sync_pipeline(do_ingest=True):
    ingest = None
    if do_ingest:
        ingest = ingest_if_stale()
    exported = export_to_space()
    cleaned = apply_weather_clean()
    board = ensure_default_board(exported["dataset"]["id"], (cleaned.get("binding") or {}).get("id"))
    return {
        "ingest": ingest,
        "project_id": exported["project"]["id"],
        "dataset_id": exported["dataset"]["id"],
        "binding_id": (cleaned.get("binding") or {}).get("id"),
        "board_id": board.get("id") if board else None,
        "rows": exported["dataset"].get("n_rows"),
    }


def ensure_default_board(dataset_id, binding_id=None):
    from services import bi_service
    return bi_service.ensure_weather_board(dataset_id, binding_id)
