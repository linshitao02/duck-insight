# -*- coding: utf-8 -*-
"""从 Open-Meteo 拉取多源气象：ECMWF/GFS 预报 + ERA5 实况/气候态。"""
import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

HOURLY_VARS = ",".join([
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "wind_speed_80m",
    "wind_gusts_10m",
    "shortwave_radiation",
    "weather_code",
])

SITES = {
    "load": {"name": "华东负荷中心-上海", "lat": 31.2304, "lon": 121.4737},
    "wind": {"name": "江苏沿海风电", "lat": 32.9940, "lon": 121.5000},
    "solar": {"name": "苏北光伏-徐州", "lat": 34.2050, "lon": 117.2840},
}


def _get(url, params, timeout=90):
    last = None
    for _ in range(3):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last = e
            time.sleep(1.2)
    raise last


def _hourly_frame(payload: dict) -> List[dict]:
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    rows = []
    for i, t in enumerate(times):
        rows.append({
            "ts": t,
            "temp_c": _at(hourly, "temperature_2m", i),
            "humidity": _at(hourly, "relative_humidity_2m", i),
            "precip_mm": _at(hourly, "precipitation", i),
            "wind_10m": _at(hourly, "wind_speed_10m", i),
            "wind_100m": _at(hourly, "wind_speed_80m", i),
            "wind_gust": _at(hourly, "wind_gusts_10m", i),
            "radiation": _at(hourly, "shortwave_radiation", i),
            "weather_code": _at(hourly, "weather_code", i),
        })
    return rows


def _at(hourly, key, i):
    arr = hourly.get(key) or []
    if i >= len(arr):
        return None
    return arr[i]


def fetch_forecast(lat, lon, forecast_days=16, model: Optional[str] = None) -> List[dict]:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": HOURLY_VARS,
        "forecast_days": int(forecast_days),
        "timezone": "Asia/Shanghai",
        "wind_speed_unit": "ms",
    }
    if model:
        params["models"] = model
    try:
        return _hourly_frame(_get(FORECAST_URL, params))
    except Exception:
        if model:
            params.pop("models", None)
            return _hourly_frame(_get(FORECAST_URL, params))
        raise


def fetch_archive(lat, lon, start: date, end: date) -> List[dict]:
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": HOURLY_VARS,
        "timezone": "Asia/Shanghai",
        "wind_speed_unit": "ms",
    }
    return _hourly_frame(_get(ARCHIVE_URL, params, timeout=90))


def _index_by_ts(rows: List[dict]) -> Dict[str, dict]:
    return {r["ts"]: r for r in rows if r.get("ts")}


def blend_sites(load_rows, wind_rows, solar_rows) -> List[dict]:
    load_map = _index_by_ts(load_rows)
    wind_map = _index_by_ts(wind_rows)
    solar_map = _index_by_ts(solar_rows)
    keys = sorted(set(load_map) | set(wind_map) | set(solar_map))
    out = []
    for ts in keys:
        a = load_map.get(ts) or {}
        w = wind_map.get(ts) or {}
        s = solar_map.get(ts) or {}
        out.append({
            "ts": ts,
            "temp_c": a.get("temp_c"),
            "humidity": a.get("humidity"),
            "precip_mm": a.get("precip_mm"),
            "wind_10m": w.get("wind_10m") if w.get("wind_10m") is not None else a.get("wind_10m"),
            "wind_100m": w.get("wind_100m") if w.get("wind_100m") is not None else a.get("wind_100m"),
            "wind_gust": w.get("wind_gust") if w.get("wind_gust") is not None else a.get("wind_gust"),
            "radiation": s.get("radiation") if s.get("radiation") is not None else a.get("radiation"),
            "weather_code": a.get("weather_code"),
        })
    return out


def fetch_multisource_bundle():
    """
    返回：
      actual: 近 10 天 ERA5 实况
      ecmwf/gfs: 未来 16 天预报
      climate: 去年同期 17–45 天，作为中长期气候态展望
    """
    today = date.today()
    load, wind, solar = SITES["load"], SITES["wind"], SITES["solar"]

    actual = blend_sites(
        fetch_archive(load["lat"], load["lon"], today - timedelta(days=10), today),
        fetch_archive(wind["lat"], wind["lon"], today - timedelta(days=10), today),
        fetch_archive(solar["lat"], solar["lon"], today - timedelta(days=10), today),
    )

    ecmwf = blend_sites(
        fetch_forecast(load["lat"], load["lon"], 16, "ecmwf_ifs025"),
        fetch_forecast(wind["lat"], wind["lon"], 16, "ecmwf_ifs025"),
        fetch_forecast(solar["lat"], solar["lon"], 16, "ecmwf_ifs025"),
    )
    try:
        gfs = blend_sites(
            fetch_forecast(load["lat"], load["lon"], 16, "gfs_seamless"),
            fetch_forecast(wind["lat"], wind["lon"], 16, "gfs_seamless"),
            fetch_forecast(solar["lat"], solar["lon"], 16, "gfs_seamless"),
        )
    except Exception:
        gfs = []

    # 中长期：去年同期气候态（17–45 天）
    start_ly = today.replace(year=today.year - 1) + timedelta(days=16)
    end_ly = today.replace(year=today.year - 1) + timedelta(days=44)
    climate_raw = blend_sites(
        fetch_archive(load["lat"], load["lon"], start_ly, end_ly),
        fetch_archive(wind["lat"], wind["lon"], start_ly, end_ly),
        fetch_archive(solar["lat"], solar["lon"], start_ly, end_ly),
    )
    climate = []
    for row in climate_raw:
        ts = datetime.fromisoformat(row["ts"])
        try:
            shifted = ts.replace(year=ts.year + 1)
        except ValueError:
            shifted = ts + timedelta(days=365)
        item = dict(row)
        item["ts"] = shifted.strftime("%Y-%m-%dT%H:%M")
        climate.append(item)

    return {
        "sites": SITES,
        "actual": actual,
        "ecmwf": ecmwf,
        "gfs": gfs,
        "climate": climate,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }
