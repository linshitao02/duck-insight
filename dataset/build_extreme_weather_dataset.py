# -*- coding: utf-8 -*-
"""构建「极端天气 × 负荷 / 风光出力」小时数据集。

气象优先拉取 Open-Meteo ERA5 再分析（真实温度、风速、辐照、降水）。
电网侧公开数据无法同时覆盖寒潮/热浪/台风/强对流标签，因此负荷与风光出力
按能源工程常用响应函数由气象驱动生成，并写入极端事件标记。
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
START = "2023-01-01"
END = "2024-12-31"

SITES = [
    {"site": "SH", "site_name": "华东负荷中心-上海", "role": "load", "lat": 31.2304, "lon": 121.4737,
     "load_base": 28500, "wind_cap": 4200, "solar_cap": 3800},
    {"site": "JS", "site_name": "江苏沿海风电", "role": "wind", "lat": 32.9940, "lon": 121.5000,
     "load_base": 16200, "wind_cap": 8600, "solar_cap": 2100},
    {"site": "XZ", "site_name": "苏北光伏-徐州", "role": "solar", "lat": 34.2050, "lon": 117.2840,
     "load_base": 9800, "wind_cap": 2400, "solar_cap": 7200},
]

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


def _get(url, params, timeout=90):
    last = None
    for _ in range(3):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last = e
            time.sleep(1.5)
    raise last


def fetch_era5(site):
    payload = _get(ARCHIVE_URL, {
        "latitude": site["lat"],
        "longitude": site["lon"],
        "start_date": START,
        "end_date": END,
        "hourly": HOURLY_VARS,
        "timezone": "Asia/Shanghai",
        "wind_speed_unit": "ms",
    })
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    rows = []
    for i, t in enumerate(times):
        rows.append({
            "ts": str(t).replace("T", " ")[:19],
            "site": site["site"],
            "site_name": site["site_name"],
            "lat": site["lat"],
            "lon": site["lon"],
            "temp_c": _at(hourly, "temperature_2m", i),
            "humidity": _at(hourly, "relative_humidity_2m", i),
            "precip_mm": _at(hourly, "precipitation", i),
            "wind_10m": _at(hourly, "wind_speed_10m", i),
            "wind_100m": _at(hourly, "wind_speed_80m", i),
            "wind_gust": _at(hourly, "wind_gusts_10m", i),
            "radiation": _at(hourly, "shortwave_radiation", i),
            "weather_code": _at(hourly, "weather_code", i),
            "weather_source": "open-meteo-era5",
        })
    if len(rows) < 24 * 30:
        raise ValueError(f"{site['site']} ERA5 行数过少: {len(rows)}")
    return pd.DataFrame(rows)


def _at(hourly, key, i):
    arr = hourly.get(key) or []
    if i >= len(arr) or arr[i] is None:
        return np.nan
    return float(arr[i])


def synth_weather(site, hours):
    """气候态合成：用于 Open-Meteo 不可达时的兜底。"""
    rng = np.random.default_rng(abs(hash(site["site"])) % (2**32))
    lat = site["lat"]
    rows = []
    for ts in hours:
        doy = ts.dayofyear
        hour = ts.hour
        month = ts.month
        seasonal = 16 + 13 * math.sin(2 * math.pi * (doy - 200) / 365.0) - 0.25 * (lat - 31)
        diurnal = 4.2 * math.sin(2 * math.pi * (hour - 9) / 24.0)
        temp = seasonal + diurnal + float(rng.normal(0, 1.4))
        humidity = float(np.clip(72 - 1.1 * (temp - 18) + rng.normal(0, 8), 25, 99))
        wind = float(np.clip(abs(rng.normal(4.8, 2.2)), 0.2, 28))
        gust = wind * float(rng.uniform(1.25, 1.7))
        rad = 0.0
        if 6 <= hour <= 18:
            solar_ang = math.cos(math.pi * (hour - 13) / 14.0)
            rad = max(0.0, 850 * max(solar_ang, 0) * (1 - 0.35 * math.sin(2 * math.pi * doy / 365)))
        precip = 0.0
        if rng.random() < 0.08:
            precip = float(abs(rng.gamma(1.4, 2.2)))
        # planted extremes
        if month in (7, 8) and 12 <= hour <= 17 and rng.random() < 0.04:
            temp = max(temp, 36.5 + rng.random() * 4)
        if month in (1, 2) and rng.random() < 0.03:
            temp = min(temp, -1.5 - rng.random() * 6)
        if month in (8, 9) and rng.random() < 0.012:
            wind = 16 + rng.random() * 12
            gust = wind * 1.55
            precip = 12 + rng.random() * 28
            rad *= 0.15
        if month in (5, 6, 7) and rng.random() < 0.02:
            precip = 10 + rng.random() * 22
            gust = max(gust, 14)
            humidity = 90
            rad *= 0.2
        rows.append({
            "ts": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "site": site["site"],
            "site_name": site["site_name"],
            "lat": site["lat"],
            "lon": site["lon"],
            "temp_c": round(temp, 2),
            "humidity": round(humidity, 1),
            "precip_mm": round(precip, 2),
            "wind_10m": round(wind, 2),
            "wind_100m": round(wind * 1.28, 2),
            "wind_gust": round(gust, 2),
            "radiation": round(rad, 1),
            "weather_code": 0,
            "weather_source": "synthetic-climatology",
        })
    return pd.DataFrame(rows)


def load_weather():
    frames = []
    sources = []
    for site in SITES:
        try:
            print(f"[气象] 拉取 ERA5 {site['site_name']} {START}~{END}")
            df = fetch_era5(site)
            sources.append(f"ERA5 {site['site']}")
            print(f"  -> {len(df)} 行")
        except Exception as e:
            print(f"[气象] Open-Meteo 失败，改用气候态合成: {e}")
            hours = pd.date_range(f"{START} 00:00:00", f"{END} 23:00:00", freq="h")
            df = synth_weather(site, hours)
            sources.append(f"synthetic {site['site']}")
        frames.append(df)
    weather = pd.concat(frames, ignore_index=True)
    weather["ts"] = pd.to_datetime(weather["ts"])
    weather = weather.sort_values(["site", "ts"]).reset_index(drop=True)
    return weather, sources


def mark_events(weather: pd.DataFrame) -> pd.DataFrame:
    df = weather.copy()
    df["date"] = df["ts"].dt.floor("D")
    daily = df.groupby(["site", "date"], as_index=False).agg(
        tmin=("temp_c", "min"),
        tmax=("temp_c", "max"),
        tmean=("temp_c", "mean"),
        rain=("precip_mm", "sum"),
        gust=("wind_gust", "max"),
        wind=("wind_10m", "max"),
    )
    daily = daily.sort_values(["site", "date"])
    daily["tmean_prev"] = daily.groupby("site")["tmean"].shift(1)
    daily["drop_24h"] = daily["tmean_prev"] - daily["tmean"]

    heat_day = (daily["tmax"] >= 35) | ((daily["tmax"] >= 33) & (daily["tmean"] >= 30))
    cold_day = (daily["tmin"] <= 0) | ((daily["drop_24h"] >= 8) & (daily["tmean"] <= 6))
    typhoon_day = (daily["date"].dt.month.isin([7, 8, 9, 10])) & (
        ((daily["gust"] >= 17.2) & (daily["rain"] >= 15)) | (daily["wind"] >= 14) | ((daily["gust"] >= 15) & (daily["rain"] >= 8))
    )
    conv_day = daily["date"].dt.month.isin([4, 5, 6, 7, 8, 9]) & (daily["rain"] >= 20) & (daily["gust"] >= 11)

    flags = daily[["site", "date"]].copy()
    flags["is_heat_wave"] = heat_day.astype(int)
    flags["is_cold_wave"] = cold_day.astype(int)
    flags["is_typhoon"] = typhoon_day.astype(int)
    flags["is_convection"] = conv_day.astype(int)
    # 热浪/寒潮要连续 2 天才算过程
    for col in ("is_heat_wave", "is_cold_wave"):
        flags[col] = (
            flags.groupby("site")[col].transform(lambda s: ((s + s.shift(1).fillna(0) + s.shift(-1).fillna(0)) >= 2).astype(int))
            | flags[col]
        ).astype(int)

    out = df.merge(flags, on=["site", "date"], how="left")
    for col in ("is_heat_wave", "is_cold_wave", "is_typhoon", "is_convection"):
        out[col] = out[col].fillna(0).astype(int)
    out["event_type"] = np.select(
        [out["is_typhoon"] == 1, out["is_heat_wave"] == 1, out["is_cold_wave"] == 1, out["is_convection"] == 1],
        ["台风", "热浪", "寒潮", "强对流"],
        default="正常",
    )
    return out.drop(columns=["date"])


def wind_power(wind_ms, cap_mw, typhoon):
    v = np.asarray(wind_ms, dtype=float)
    cf = np.zeros_like(v)
    rated = (v >= 12) & (v < 25)
    ramp = (v >= 3) & (v < 12)
    cf[ramp] = ((v[ramp] - 3) / 9.0) ** 3
    cf[rated] = 1.0
    # 台风超切出风速停机
    cf[v >= 25] = 0.0
    cf = np.clip(cf, 0, 1)
    power = cap_mw * cf
    power = np.where(typhoon == 1, power * 0.35, power)
    return power


def solar_power(rad, temp, precip, cap_mw, typhoon, convection):
    rad = np.asarray(rad, dtype=float)
    temp = np.asarray(temp, dtype=float)
    precip = np.asarray(precip, dtype=float)
    derate = 1.0 - 0.0045 * np.clip(temp - 25.0, 0, None)
    cloud = np.clip(1.0 - 0.045 * precip, 0.15, 1.0)
    power = cap_mw * np.clip(rad / 1000.0, 0, 1.15) * derate * cloud
    power = np.where(typhoon == 1, power * 0.25, power)
    power = np.where(convection == 1, power * 0.45, power)
    return np.clip(power, 0, None)


def load_mw(df, site_meta):
    ts = pd.to_datetime(df["ts"])
    hour = ts.dt.hour.to_numpy()
    weekday = ts.dt.dayofweek.to_numpy()
    month = ts.dt.month.to_numpy()
    temp = df["temp_c"].to_numpy(dtype=float)
    base = site_meta["load_base"]
    tod = 0.78 + 0.22 * np.sin(2 * np.pi * (hour - 8) / 24.0) + 0.12 * ((hour >= 18) & (hour <= 21))
    tod = np.where((hour <= 5) | (hour >= 23), tod * 0.82, tod)
    week = np.where(weekday >= 5, 0.91, 1.0)
    hdd = np.clip(16.0 - temp, 0, None)
    cdd = np.clip(temp - 24.0, 0, None)
    weather_load = 1.0 + 0.011 * hdd + 0.016 * cdd
    weather_load = np.where(df["is_heat_wave"].to_numpy() == 1, weather_load * 1.12, weather_load)
    weather_load = np.where(df["is_cold_wave"].to_numpy() == 1, weather_load * 1.09, weather_load)
    # 台风：工业停产拉低，居民抽水/应急略升，净效应下降
    weather_load = np.where(df["is_typhoon"].to_numpy() == 1, weather_load * 0.88, weather_load)
    weather_load = np.where(df["is_convection"].to_numpy() == 1, weather_load * 1.03, weather_load)
    month_k = np.where(np.isin(month, [7, 8]), 1.06, np.where(np.isin(month, [1, 2]), 1.04, 1.0))
    noise = np.random.default_rng(7).normal(1.0, 0.018, size=len(df))
    return np.clip(base * tod * week * weather_load * month_k * noise, 800, None)


def attach_price(wide: pd.DataFrame) -> pd.DataFrame:
    """由负荷与风光构造日前/实时电价（离线、可学习，不接实时行情）。"""
    df = wide.copy()
    ts = pd.to_datetime(df["ts"])
    hour = ts.dt.hour.to_numpy()
    load = pd.to_numeric(df["load_mw"], errors="coerce").fillna(0).to_numpy()
    wind = pd.to_numeric(df["wind_mw"], errors="coerce").fillna(0).to_numpy()
    solar = pd.to_numeric(df["solar_mw"], errors="coerce").fillna(0).to_numpy()
    residual = np.clip(load - wind - solar, 200.0, None)
    peak = np.where(
        np.isin(hour, [8, 9, 10, 17, 18, 19, 20]),
        85.0,
        np.where(np.isin(hour, [11, 12, 13, 14, 15, 16]), 25.0, 0.0),
    )
    share = np.divide(residual, np.clip(load, 1.0, None))
    congestion = np.clip((share - 0.55) / 0.40, 0.0, 1.0)
    heat = df["is_heat_wave"].fillna(0).to_numpy() if "is_heat_wave" in df.columns else 0
    cold = df["is_cold_wave"].fillna(0).to_numpy() if "is_cold_wave" in df.columns else 0
    typhoon = df["is_typhoon"].fillna(0).to_numpy() if "is_typhoon" in df.columns else 0
    rng = np.random.default_rng(2026)
    noise = rng.normal(1.0, 0.022, size=len(df))
    price = (
        365.0
        + residual * 0.011
        + peak
        + congestion * 95
        + 38 * (np.asarray(heat) == 1)
        + 28 * (np.asarray(cold) == 1)
        + 22 * (np.asarray(typhoon) == 1)
    ) * noise
    gust = pd.to_numeric(df["wind_gust"], errors="coerce").fillna(0).to_numpy() if "wind_gust" in df.columns else 0
    wind10 = pd.to_numeric(df["wind_10m"], errors="coerce").fillna(0).to_numpy() if "wind_10m" in df.columns else 0
    rt_k = np.where(np.abs(np.asarray(gust) - np.asarray(wind10)) > 4, 1.028, 1.008)
    df["residual_mw"] = np.round(residual, 2)
    df["congestion"] = np.round(congestion, 4)
    df["price_da"] = np.round(np.clip(price, 80, None), 2)
    df["price_rt"] = np.round(df["price_da"].to_numpy() * rt_k, 2)
    return df


def ensure_price_files(force=False):
    """在已有宽表上补日前电价，不重新拉气象。"""
    wide_path = ROOT / "training_wide.csv"
    price_path = ROOT / "price_hourly.csv"
    if not wide_path.exists():
        build(force=False)
    wide = pd.read_csv(wide_path)
    if "price_da" in wide.columns and price_path.exists() and not force:
        return {"wide": wide_path, "price": price_path, "rows": int(len(wide)), "skipped": True}
    wide = attach_price(wide)
    if "row_key" not in wide.columns:
        wide["row_key"] = wide["ts"].astype(str) + "|" + wide["site"].astype(str)
    wide.to_csv(wide_path, index=False, encoding="utf-8-sig")
    price_cols = ["row_key", "ts", "site", "residual_mw", "congestion", "price_da", "price_rt"]
    wide[price_cols].to_csv(price_path, index=False, encoding="utf-8-sig")
    return {"wide": wide_path, "price": price_path, "rows": int(len(wide)), "skipped": False}


def inject_missing(df, cols, frac=0.012, seed=21):
    rng = np.random.default_rng(seed)
    out = df.copy()
    n = len(out)
    k = max(1, int(n * frac))
    for c in cols:
        idx = rng.choice(n, size=k, replace=False)
        out.loc[idx, c] = np.nan
    return out


def event_log(df):
    rows = []
    for site, g in df.groupby("site"):
        g = g.sort_values("ts")
        for etype, flag in [
            ("寒潮", "is_cold_wave"),
            ("热浪", "is_heat_wave"),
            ("台风", "is_typhoon"),
            ("强对流", "is_convection"),
        ]:
            on = g[flag].eq(1).to_numpy()
            if not on.any():
                continue
            start = None
            times = g["ts"].to_numpy()
            loads = g["load_mw"].to_numpy()
            rews = g["renewable_mw"].to_numpy()
            for i, flag_i in enumerate(on):
                if flag_i and start is None:
                    start = i
                if (not flag_i or i == len(on) - 1) and start is not None:
                    end = i if flag_i and i == len(on) - 1 else i - 1
                    sl = slice(start, end + 1)
                    rows.append({
                        "site": site,
                        "event_type": etype,
                        "start_ts": pd.Timestamp(times[start]).strftime("%Y-%m-%d %H:%M:%S"),
                        "end_ts": pd.Timestamp(times[end]).strftime("%Y-%m-%d %H:%M:%S"),
                        "hours": int(end - start + 1),
                        "load_mw_mean": round(float(np.nanmean(loads[sl])), 1),
                        "renewable_mw_mean": round(float(np.nanmean(rews[sl])), 1),
                    })
                    start = None
    return pd.DataFrame(rows)


def build(force=False):
    wide_path = ROOT / "training_wide.csv"
    if wide_path.exists() and not force:
        print(f"[跳过] 已存在 {wide_path}，传入 force=True 可重建")
        price_info = ensure_price_files(force=False)
        return {
            "weather": ROOT / "weather_hourly.csv",
            "load": ROOT / "load_hourly.csv",
            "renewable": ROOT / "renewable_hourly.csv",
            "price": price_info["price"],
            "events": ROOT / "extreme_events.csv",
            "wide": wide_path,
        }

    weather, sources = load_weather()
    weather = mark_events(weather)
    meta = {s["site"]: s for s in SITES}
    parts = []
    for site, g in weather.groupby("site", sort=False):
        g = g.copy()
        m = meta[site]
        g["wind_mw"] = wind_power(g["wind_100m"].fillna(g["wind_10m"] * 1.25), m["wind_cap"], g["is_typhoon"])
        g["solar_mw"] = solar_power(g["radiation"], g["temp_c"], g["precip_mm"], m["solar_cap"], g["is_typhoon"], g["is_convection"])
        rng = np.random.default_rng(11)
        g["wind_mw"] = np.clip(g["wind_mw"] * rng.normal(1.0, 0.03, len(g)), 0, None).round(2)
        g["solar_mw"] = np.clip(g["solar_mw"] * rng.normal(1.0, 0.03, len(g)), 0, None).round(2)
        g["renewable_mw"] = (g["wind_mw"] + g["solar_mw"]).round(2)
        g["load_mw"] = load_mw(g, m).round(2)
        parts.append(g)
    wide = pd.concat(parts, ignore_index=True)
    wide = attach_price(wide)
    wide["row_key"] = wide["ts"].dt.strftime("%Y-%m-%d %H:%M:%S") + "|" + wide["site"]
    wide["ts"] = wide["ts"].dt.strftime("%Y-%m-%d %H:%M:%S")

    miss_cols = ["temp_c", "humidity", "precip_mm", "wind_10m", "wind_100m", "radiation", "load_mw", "renewable_mw"]
    wide_dirty = inject_missing(wide, miss_cols)

    weather_out = wide_dirty[[
        "row_key", "ts", "site", "site_name", "lat", "lon",
        "temp_c", "humidity", "precip_mm", "wind_10m", "wind_100m", "wind_gust",
        "radiation", "weather_code", "is_cold_wave", "is_heat_wave", "is_typhoon",
        "is_convection", "event_type", "weather_source",
    ]]
    load_out = wide_dirty[["row_key", "ts", "site", "load_mw"]]
    re_out = wide_dirty[["row_key", "ts", "site", "wind_mw", "solar_mw", "renewable_mw"]]
    price_out = wide_dirty[["row_key", "ts", "site", "residual_mw", "congestion", "price_da", "price_rt"]]
    events = event_log(wide)

    weather_out.to_csv(ROOT / "weather_hourly.csv", index=False, encoding="utf-8-sig")
    load_out.to_csv(ROOT / "load_hourly.csv", index=False, encoding="utf-8-sig")
    re_out.to_csv(ROOT / "renewable_hourly.csv", index=False, encoding="utf-8-sig")
    price_out.to_csv(ROOT / "price_hourly.csv", index=False, encoding="utf-8-sig")
    events.to_csv(ROOT / "extreme_events.csv", index=False, encoding="utf-8-sig")
    wide_dirty.to_csv(wide_path, index=False, encoding="utf-8-sig")

    summary = {
        "rows": int(len(wide_dirty)),
        "sites": [s["site"] for s in SITES],
        "start": START,
        "end": END,
        "weather_source": sources,
        "event_hours": {
            "寒潮": int(wide["is_cold_wave"].sum()),
            "热浪": int(wide["is_heat_wave"].sum()),
            "台风": int(wide["is_typhoon"].sum()),
            "强对流": int(wide["is_convection"].sum()),
        },
        "event_episodes": int(len(events)),
        "labels": ["load_mw", "renewable_mw", "wind_mw", "solar_mw", "price_da"],
    }
    (ROOT / "SOURCES.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "SOURCES.txt").write_text(
        "极端天气 × 负荷 / 风光出力 数据集说明\n"
        "====================================\n"
        f"时间范围: {START} ~ {END} 逐小时，3 个华东站点，共 {len(wide_dirty)} 行。\n"
        "气象: Open-Meteo Archive ERA5（temperature_2m, wind, radiation, precipitation）。\n"
        "      若接口失败则回退为气候态合成，见 SOURCES.json 的 weather_source。\n"
        "负荷 load_mw: 由小时/工作日曲线 + HDD/CDD + 极端事件冲击生成（MW）。\n"
        "风光 renewable_mw = wind_mw + solar_mw，风机功率曲线含台风切出，光伏含辐照/温度/云遮。\n"
        "事件标记: 寒潮 / 热浪 / 台风 / 强对流，阈值基于日最高/最低温、24h 降温、阵风与强降水。\n"
        "负荷 / 风电 / 光伏 / 日前电价是独立标签，训练时不要把其它 label 当特征。\n"
        "日前电价 price_da 由残余负荷、峰谷、阻塞代理与极端天气冲击生成，仅作离线训练。\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return {
        "weather": ROOT / "weather_hourly.csv",
        "load": ROOT / "load_hourly.csv",
        "renewable": ROOT / "renewable_hourly.csv",
        "events": ROOT / "extreme_events.csv",
        "wide": wide_path,
        "price": ROOT / "price_hourly.csv",
        "summary": summary,
    }


if __name__ == "__main__":
    build(force=True)
