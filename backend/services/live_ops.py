# -*- coding: utf-8 -*-
"""新建实时业务库 power_ops_live，导入历史 CSV + 2026 小时数据，并登记活表数据源。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pymysql
from pymysql.cursors import DictCursor

from config import DB_CONFIG, ROOT_DIR
from utils.db import insert, query, update

LIVE_DB = "power_ops_live"
LIVE_TABLE = "fact_power_hourly"
DIM_TABLE = "dim_site"
SOURCE_NAME = "电力运行实时库"
PROJECT_NAME = "电力运行实时数据空间"
DATASET_NAME = "电力小时活表"
CSV_PATH = Path(ROOT_DIR) / "dataset" / "training_wide.csv"
END_TS = pd.Timestamp("2026-09-19 23:00:00")
EXTRA_SITES = [
    {"site": "ZJ", "site_name": "浙江沿海风电", "lat": 30.27, "lon": 120.15},
]


def _admin_conn(database=None):
    kwargs = {
        "host": DB_CONFIG.get("host", "127.0.0.1"),
        "user": DB_CONFIG.get("user", "root"),
        "password": DB_CONFIG.get("password", "root"),
        "port": int(DB_CONFIG.get("port", 3306)),
        "charset": "utf8mb4",
        "cursorclass": DictCursor,
        "autocommit": True,
    }
    if database:
        kwargs["database"] = database
    return pymysql.connect(**kwargs)


def ensure_schema():
    conn = _admin_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{LIVE_DB}` "
                "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
            )
            cur.execute(f"USE `{LIVE_DB}`")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS `{DIM_TABLE}` (
                  `site` varchar(16) NOT NULL,
                  `site_name` varchar(64) DEFAULT NULL,
                  `lat` double DEFAULT NULL,
                  `lon` double DEFAULT NULL,
                  PRIMARY KEY (`site`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS `{LIVE_TABLE}` (
                  `ts` datetime NOT NULL,
                  `site` varchar(16) NOT NULL,
                  `site_name` varchar(64) DEFAULT NULL,
                  `lat` double DEFAULT NULL,
                  `lon` double DEFAULT NULL,
                  `temp_c` double DEFAULT NULL,
                  `humidity` double DEFAULT NULL,
                  `precip_mm` double DEFAULT NULL,
                  `wind_10m` double DEFAULT NULL,
                  `wind_100m` double DEFAULT NULL,
                  `wind_gust` double DEFAULT NULL,
                  `radiation` double DEFAULT NULL,
                  `weather_code` double DEFAULT NULL,
                  `weather_source` varchar(64) DEFAULT NULL,
                  `is_heat_wave` tinyint DEFAULT 0,
                  `is_cold_wave` tinyint DEFAULT 0,
                  `is_typhoon` tinyint DEFAULT 0,
                  `is_convection` tinyint DEFAULT 0,
                  `event_type` varchar(32) DEFAULT NULL,
                  `wind_mw` double DEFAULT NULL,
                  `solar_mw` double DEFAULT NULL,
                  `renewable_mw` double DEFAULT NULL,
                  `load_mw` double DEFAULT NULL,
                  `row_key` varchar(80) DEFAULT NULL,
                  `residual_mw` double DEFAULT NULL,
                  `congestion` double DEFAULT NULL,
                  `price_da` double DEFAULT NULL,
                  `price_rt` double DEFAULT NULL,
                  PRIMARY KEY (`ts`, `site`),
                  KEY `idx_site_ts` (`site`, `ts`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
    finally:
        conn.close()


def _load_csv():
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"未找到历史宽表: {CSV_PATH}")
    df = pd.read_csv(CSV_PATH)
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
    df = df.dropna(subset=["ts", "site"])
    df["site"] = df["site"].astype(str)
    return df


def _cycle_template(tmpl: pd.DataFrame, hours: pd.DatetimeIndex, site_meta: dict):
    n = len(hours)
    if tmpl is None or tmpl.empty:
        raise ValueError("缺少可用于外推的历史模板")
    idx = np.arange(n) % len(tmpl)
    out = tmpl.iloc[idx].copy().reset_index(drop=True)
    out["ts"] = hours
    out["site"] = site_meta["site"]
    out["site_name"] = site_meta.get("site_name") or out.get("site_name")
    if site_meta.get("lat") is not None:
        out["lat"] = site_meta["lat"]
    if site_meta.get("lon") is not None:
        out["lon"] = site_meta["lon"]
    doy = hours.dayofyear.to_numpy()
    hour = hours.hour.to_numpy()
    solar_shape = np.clip(np.sin((hour - 6) / 12 * np.pi), 0, 1)
    solar_season = 0.52 + 0.48 * np.sin((doy - 80) / 365.0 * 2 * np.pi)
    hist_solar = float(pd.to_numeric(tmpl.get("solar_mw"), errors="coerce").max() or 800)
    hist_wind = float(pd.to_numeric(tmpl.get("wind_mw"), errors="coerce").max() or 400)
    hist_load = float(pd.to_numeric(tmpl.get("load_mw"), errors="coerce").median() or 8000)
    rng = np.random.default_rng(abs(hash(site_meta["site"])) % (2 ** 32))
    solar = hist_solar * solar_shape * solar_season * (1 + rng.normal(0, 0.08, n))
    wind_shape = 0.35 + 0.65 * ((hour + 3) % 24) / 24.0
    wind = hist_wind * wind_shape * (0.75 + 0.35 * rng.random(n))
    if site_meta["site"] == "SH":
        solar *= 1.15
        wind *= 0.55
        temp_shift = 1.6
    elif site_meta["site"] == "ZJ":
        solar *= 0.85
        wind *= 1.2
        temp_shift = 0.4
    else:
        temp_shift = 0.0
    out["solar_mw"] = np.clip(solar, 0, None).round(3)
    out["wind_mw"] = np.clip(wind, 0, None).round(3)
    out["renewable_mw"] = (out["solar_mw"] + out["wind_mw"]).round(3)
    load = hist_load * (0.92 + 0.12 * np.sin((hour - 8) / 24 * 2 * np.pi))
    load = load * (1.02 if hours[0].year >= 2026 else 1.0)
    out["load_mw"] = np.clip(load + rng.normal(0, 80, n), 500, None).round(2)
    if "temp_c" in out.columns:
        out["temp_c"] = (pd.to_numeric(out["temp_c"], errors="coerce") + temp_shift).round(2)
    out["residual_mw"] = (out["load_mw"] - out["renewable_mw"]).round(2)
    out["row_key"] = pd.to_datetime(out["ts"]).dt.strftime("%Y-%m-%d %H:%M:%S") + "|" + out["site"].astype(str)
    out["weather_source"] = out.get("weather_source", pd.Series(["synthetic-2026"] * n)).fillna("synthetic-2026")
    out.loc[pd.to_datetime(out["ts"]) >= pd.Timestamp("2026-01-01"), "weather_source"] = "synthetic-2026"
    return out


def _fabricate(hist: pd.DataFrame):
    frames = []
    site_rows = hist.drop_duplicates("site")[["site", "site_name", "lat", "lon"]]
    known = {str(r.site): r._asdict() if hasattr(r, "_asdict") else r.to_dict() for r in site_rows.itertuples(index=False)}
    templates = {}
    for site, meta in known.items():
        sdf = hist[hist["site"].astype(str) == site].sort_values("ts")
        templates[site] = sdf.tail(21 * 24) if len(sdf) >= 24 else sdf

    def _append(site_meta, start, end):
        if start > end:
            return
        hours = pd.date_range(start, end, freq="h")
        tmpl_key = site_meta["site"] if site_meta["site"] in templates else next(iter(templates))
        frames.append(_cycle_template(templates[tmpl_key], hours, site_meta))

    # 主站点：从历史最大时间推到 2026-09-19
    for site, meta in known.items():
        sdf = hist[hist["site"].astype(str) == site]
        last = pd.to_datetime(sdf["ts"]).max()
        start = (last + pd.Timedelta(hours=1)) if pd.notna(last) else pd.Timestamp("2023-01-01")
        _append(meta, start, END_TS)

    # 额外站点：整段 2023-01-01 ~ 2026-09-19，用于把实时库做大
    hist_min = pd.to_datetime(hist["ts"]).min()
    begin = hist_min if pd.notna(hist_min) else pd.Timestamp("2023-01-01")
    existing_sites = set(known)
    for extra in EXTRA_SITES:
        if extra["site"] in existing_sites:
            sdf = hist[hist["site"].astype(str) == extra["site"]]
            last = pd.to_datetime(sdf["ts"]).max()
            start = last + pd.Timedelta(hours=1)
        else:
            start = pd.Timestamp("2025-01-01")
        _append(extra, start, END_TS)
    if not frames:
        return pd.DataFrame(columns=hist.columns)
    out = pd.concat(frames, ignore_index=True)
    keep = [c for c in hist.columns if c in out.columns]
    return out[keep]


def _as_sql_row(rec):
    out = []
    for v in rec:
        if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
            out.append(None)
        elif isinstance(v, pd.Timestamp):
            out.append(v.to_pydatetime() if pd.notna(v) else None)
        elif isinstance(v, np.datetime64):
            ts = pd.Timestamp(v)
            out.append(ts.to_pydatetime() if pd.notna(ts) else None)
        elif isinstance(v, datetime):
            out.append(v)
        elif isinstance(v, (np.integer,)):
            out.append(int(v))
        elif isinstance(v, (np.floating,)):
            out.append(None if np.isnan(v) else float(v))
        else:
            out.append(v)
    return out


def _insert_df(conn, table, df, chunk=1500):
    if df is None or df.empty:
        return 0
    cols = list(df.columns)
    placeholders = ", ".join(["%s"] * len(cols))
    col_sql = ", ".join(f"`{c}`" for c in cols)
    sql = f"INSERT IGNORE INTO `{table}` ({col_sql}) VALUES ({placeholders})"
    total = 0
    records = df.where(pd.notnull(df), None).to_numpy().tolist()
    with conn.cursor() as cur:
        for i in range(0, len(records), chunk):
            batch = [_as_sql_row(r) for r in records[i:i + chunk]]
            cur.executemany(sql, batch)
            total += len(batch)
        conn.commit()
    return total


def seed_live_tables():
    ensure_schema()
    conn = _admin_conn(LIVE_DB)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS c, MIN(ts) AS mn, MAX(ts) AS mx FROM `{LIVE_TABLE}`")
            existed = cur.fetchone() or {}
    finally:
        conn.close()
    count = int(existed.get("c") or 0)
    mx = existed.get("mx")
    if count > 1000 and mx and pd.Timestamp(mx) >= END_TS:
        return {
            "skipped": True,
            "table_rows": count,
            "min_ts": str(existed.get("mn") or ""),
            "max_ts": str(mx),
        }
    hist = _load_csv()
    extra = _fabricate(hist)
    sites = pd.concat([
        hist.drop_duplicates("site")[["site", "site_name", "lat", "lon"]],
        pd.DataFrame(EXTRA_SITES),
    ], ignore_index=True).drop_duplicates("site")

    conn = _admin_conn(LIVE_DB)
    try:
        inserted_hist = _insert_df(conn, LIVE_TABLE, hist)
        inserted_extra = _insert_df(conn, LIVE_TABLE, extra)
        _insert_df(conn, DIM_TABLE, sites)
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS c, MIN(ts) AS mn, MAX(ts) AS mx FROM `{LIVE_TABLE}`")
            stat = cur.fetchone() or {}
    finally:
        conn.close()
    return {
        "csv_rows": int(len(hist)),
        "generated_rows": int(len(extra)),
        "inserted_csv": inserted_hist,
        "inserted_generated": inserted_extra,
        "table_rows": int(stat.get("c") or 0),
        "min_ts": str(stat.get("mn") or ""),
        "max_ts": str(stat.get("mx") or ""),
    }


def ensure_source():
    row = query("SELECT * FROM data_source WHERE name=%s AND status=1", (SOURCE_NAME,), one=True)
    payload = {
        "name": SOURCE_NAME,
        "engine": "mysql",
        "host": DB_CONFIG.get("host", "127.0.0.1"),
        "port": int(DB_CONFIG.get("port", 3306)),
        "db_user": DB_CONFIG.get("user", "root"),
        "db_password": DB_CONFIG.get("password", "root"),
        "database_name": LIVE_DB,
        "remark": "实时业务库：历史宽表 + 2026 小时数据，表会持续增长",
        "username": "system",
        "status": 1,
    }
    if row:
        update("data_source", payload, "id=%s", (row["id"],))
        return query("SELECT * FROM data_source WHERE id=%s", (row["id"],), one=True)
    sid = insert("data_source", payload)
    return query("SELECT * FROM data_source WHERE id=%s", (sid,), one=True)


def ensure_project():
    row = query("SELECT * FROM data_project WHERE name=%s AND status=1", (PROJECT_NAME,), one=True)
    if row:
        return row
    admin = query("SELECT id, username FROM sys_user WHERE username=%s", ("admin",), one=True) or {}
    pid = insert("data_project", {
        "name": PROJECT_NAME,
        "description": "挂接 MySQL 实时库表，每天新增小时数据后无需重新上传文件",
        "scenario_code": "power_trading",
        "cover_color": "#0ea5e9",
        "user_id": admin.get("id"),
        "username": admin.get("username") or "admin",
        "status": 1,
    })
    return query("SELECT * FROM data_project WHERE id=%s", (pid,), one=True)


def attach_dataset(source=None, project=None):
    from services.source_service import attach_live_dataset
    source = source or ensure_source()
    project = project or ensure_project()
    return attach_live_dataset(
        source["id"],
        project["id"],
        LIVE_DB,
        LIVE_TABLE,
        name=DATASET_NAME,
        remark="实时挂接 power_ops_live.fact_power_hourly，每天进数后直接读表",
        scenario="power_trading",
    )


def lookup_live_assets():
    project = query("SELECT * FROM data_project WHERE name=%s AND status=1", (PROJECT_NAME,), one=True)
    source = query("SELECT * FROM data_source WHERE name=%s AND status=1", (SOURCE_NAME,), one=True)
    dataset = None
    if project:
        from services.dataset_service import get_dataset
        row = query(
            """
            SELECT id FROM dataset
            WHERE project_id=%s AND origin_type='mysql_live' AND source_table=%s AND status=1
            ORDER BY id DESC
            """,
            (project["id"], LIVE_TABLE),
            one=True,
        ) or query(
            "SELECT id FROM dataset WHERE name=%s AND status=1 ORDER BY id DESC",
            (DATASET_NAME,),
            one=True,
        )
        dataset = get_dataset(row["id"]) if row else None
    return {"project": project, "source": source, "dataset": dataset}


def ensure_live_ops(import_data=True):
    ensure_schema()
    stats = seed_live_tables() if import_data else {}
    source = ensure_source()
    project = ensure_project()
    dataset = None
    try:
        from services.source_service import count_table_rows
        n = count_table_rows(source["id"], LIVE_DB, LIVE_TABLE)
    except Exception:
        n = int((stats or {}).get("table_rows") or 0)
    if n:
        dataset = attach_dataset(source, project)
    return {
        "stats": stats,
        "source": {"id": source["id"], "name": source["name"], "database": LIVE_DB},
        "project": {"id": project["id"], "name": project["name"]},
        "dataset": {"id": dataset["id"], "name": dataset["name"], "n_rows": dataset.get("n_rows")} if dataset else None,
    }
