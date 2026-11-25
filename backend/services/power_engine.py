# -*- coding: utf-8 -*-
"""气象驱动的华东负荷 / 风光出力 / 电价与交易规则引擎。"""
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean

from services.weather_crawler import fetch_multisource_bundle
from utils.db import execute, insert, query
from utils.jsonx import dumps, loads


LOAD_CAP_MW = 92000.0
WIND_CAP_MW = 28000.0
SOLAR_CAP_MW = 36000.0
BASE_PRICE = 385.0


def _num(v, default=0.0):
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _parse_ts(ts):
    if isinstance(ts, datetime):
        return ts
    text = str(ts).replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt)
        except Exception:
            continue
    return datetime.fromisoformat(text[:19])


def qc_row(row):
    """物理阈值质控 + 单位已在爬虫侧统一为 ℃ / m/s / W/m²。"""
    out = dict(row)
    t = _num(out.get("temp_c"), None) if out.get("temp_c") is not None else None
    if t is not None:
        out["temp_c"] = max(-30, min(48, t))
    for k, lo, hi in (
        ("humidity", 0, 100),
        ("precip_mm", 0, 80),
        ("wind_10m", 0, 45),
        ("wind_100m", 0, 55),
        ("wind_gust", 0, 60),
        ("radiation", 0, 1200),
    ):
        if out.get(k) is not None:
            out[k] = max(lo, min(hi, _num(out[k])))
    return out


def _hourly_load_factor(ts: datetime):
    h = ts.hour
    weekday = ts.weekday()
    shape = [
        0.72, 0.68, 0.66, 0.65, 0.66, 0.70, 0.78, 0.88,
        0.96, 0.99, 0.97, 0.95, 0.93, 0.94, 0.95, 0.96,
        0.98, 1.00, 0.99, 0.96, 0.91, 0.86, 0.80, 0.75,
    ]
    weekend = 0.92 if weekday >= 5 else 1.0
    return shape[h] * weekend


def weather_to_power(row, shock=None):
    shock = shock or {}
    ts = _parse_ts(row["ts"])
    temp = _num(row.get("temp_c"), 20) + _num(shock.get("d_temp"))
    wind = _num(row.get("wind_100m") if row.get("wind_100m") is not None else row.get("wind_10m"), 4)
    wind += _num(shock.get("d_wind"))
    gust = _num(row.get("wind_gust"), wind)
    rad = max(0.0, _num(row.get("radiation")) * _num(shock.get("rad_scale"), 1.0))

    hdd = max(16.0 - temp, 0.0)
    cdd = max(temp - 24.0, 0.0)
    load = LOAD_CAP_MW * _hourly_load_factor(ts) * (1 + 0.011 * cdd + 0.007 * hdd)
    if temp >= 35:
        load *= 1.04
    if temp <= 0:
        load *= 1.03

    # 风电：切入 3m/s，额定 12m/s，切出 25m/s
    if wind < 3 or wind >= 25 or gust >= 28:
        wind_mw = 0.0
    else:
        ratio = min(1.0, ((wind - 3.0) / 9.0) ** 3)
        wind_mw = WIND_CAP_MW * ratio

    solar_mw = SOLAR_CAP_MW * (rad / 1000.0) * max(0.55, 1 - 0.0045 * max(temp - 25.0, 0))
    solar_mw = max(0.0, min(SOLAR_CAP_MW, solar_mw))

    residual = max(8000.0, load - wind_mw - solar_mw)
    peak = 85 if ts.hour in (8, 9, 10, 17, 18, 19, 20) else 0
    congestion = min(1.0, max(0.0, (residual - 55000) / 40000))
    price_da = BASE_PRICE + residual * 0.0048 + peak + congestion * 120
    # 实时：叠加气象不确定性
    price_rt = price_da * (1 + 0.015 * (1 if abs(_num(row.get("wind_gust")) - wind) > 4 else 0.3))
    if shock:
        price_rt *= 1.04
    return {
        **row,
        "ts": ts.strftime("%Y-%m-%d %H:%M:%S"),
        "load_mw": round(load, 2),
        "wind_mw": round(wind_mw, 2),
        "solar_mw": round(solar_mw, 2),
        "residual_mw": round(residual, 2),
        "price_da": round(price_da, 2),
        "price_rt": round(price_rt, 2),
        "congestion": round(congestion, 4),
    }


def _horizon_of(ts: datetime, now: datetime):
    delta_h = (ts - now).total_seconds() / 3600.0
    if delta_h <= 0:
        return "actual"
    if delta_h <= 72:
        return "short_1_3d"
    if delta_h <= 16 * 24:
        return "medium_7_16d"
    return "long_17_45d"


def _merge_forecast(ecmwf, gfs):
    """ECMWF 与 GFS 等权融合，体现多源气象。"""
    gmap = {r["ts"]: r for r in gfs or []}
    merged = []
    for a in ecmwf or []:
        b = gmap.get(a["ts"])
        if not b:
            merged.append(a)
            continue
        item = dict(a)
        for k in ("temp_c", "humidity", "precip_mm", "wind_10m", "wind_100m", "wind_gust", "radiation"):
            va, vb = a.get(k), b.get(k)
            if va is None:
                item[k] = vb
            elif vb is None:
                item[k] = va
            else:
                item[k] = (_num(va) + _num(vb)) / 2.0
        merged.append(item)
    return merged


def ingest_and_materialize():
    raw = fetch_multisource_bundle()
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    forecast = _merge_forecast(raw.get("ecmwf") or [], raw.get("gfs") or [])

    rows = []
    for item in raw.get("actual") or []:
        ts = _parse_ts(item["ts"])
        if ts > now:
            continue
        powered = weather_to_power(qc_row(item))
        powered["horizon"] = "actual"
        powered["source_json"] = "ERA5+OpenMeteo"
        rows.append(powered)

    for item in forecast:
        ts = _parse_ts(item["ts"])
        if ts <= now:
            continue
        powered = weather_to_power(qc_row(item))
        powered["horizon"] = _horizon_of(ts, now)
        powered["source_json"] = "ECMWF+GFS"
        rows.append(powered)

    for item in raw.get("climate") or []:
        ts = _parse_ts(item["ts"])
        if ts <= now + timedelta(days=16):
            continue
        if ts > now + timedelta(days=45):
            continue
        powered = weather_to_power(qc_row(item))
        powered["horizon"] = "long_17_45d"
        powered["source_json"] = "climatology-ERA5"
        rows.append(powered)

    execute("DELETE FROM power_hourly", [])
    seen = set()
    for r in rows:
        key = (r["ts"], r["horizon"])
        if key in seen:
            continue
        seen.add(key)
        insert("power_hourly", {
            "ts": r["ts"],
            "horizon": r["horizon"],
            "temp_c": r.get("temp_c"),
            "humidity": r.get("humidity"),
            "precip_mm": r.get("precip_mm"),
            "wind_10m": r.get("wind_10m"),
            "wind_100m": r.get("wind_100m"),
            "wind_gust": r.get("wind_gust"),
            "radiation": r.get("radiation"),
            "weather_code": r.get("weather_code"),
            "load_mw": r.get("load_mw"),
            "wind_mw": r.get("wind_mw"),
            "solar_mw": r.get("solar_mw"),
            "residual_mw": r.get("residual_mw"),
            "price_da": r.get("price_da"),
            "price_rt": r.get("price_rt"),
            "congestion": r.get("congestion"),
            "source_json": r.get("source_json"),
        })
    alerts = rebuild_alerts()
    return {
        "rows": len(rows),
        "sites": raw.get("sites"),
        "fetched_at": raw.get("fetched_at"),
        "alerts": len(alerts),
        "gfs_available": bool(raw.get("gfs")),
    }


def list_series(limit=800):
    rows = query(
        "SELECT * FROM power_hourly ORDER BY ts ASC LIMIT %s",
        (int(limit),),
    )
    return rows or []


def _f(row, key):
    return _num(row.get(key))


def rebuild_alerts():
    execute("DELETE FROM power_alert WHERE status='open'", [])
    rows = query("SELECT * FROM power_hourly WHERE ts >= DATE_SUB(NOW(), INTERVAL 6 HOUR) ORDER BY ts", [])
    future = query(
        "SELECT * FROM power_hourly WHERE ts >= NOW() AND ts < DATE_ADD(NOW(), INTERVAL 72 HOUR) ORDER BY ts",
        [],
    )
    alerts = []

    def push(level, code, title, message, ts, extra=None):
        alerts.append({
            "level": level, "code": code, "title": title, "message": message,
            "ts": ts, "payload": extra or {},
        })

    for r in future or []:
        ts = r["ts"]
        if _f(r, "temp_c") >= 35:
            push("warn", "heatwave", "热浪风险", f"{ts} 气温 {_f(r,'temp_c'):.1f}℃，空调负荷抬升，关注晚高峰电价。", ts)
        if _f(r, "temp_c") <= 0:
            push("warn", "coldwave", "寒潮风险", f"{ts} 气温 {_f(r,'temp_c'):.1f}℃，取暖负荷上升。", ts)
        if _f(r, "wind_gust") >= 20:
            push("danger", "typhoon", "大风/台风型风险", f"{ts} 阵风 {_f(r,'wind_gust'):.1f} m/s，风电可能切出，实时价格易上冲。", ts)
        if _f(r, "precip_mm") >= 15:
            push("info", "storm", "强对流/强降水", f"{ts} 小时降水 {_f(r,'precip_mm'):.1f} mm，光伏出力受抑。", ts)
        if _f(r, "price_da") >= 800:
            push("danger", "price_spike", "日前高价预警", f"{ts} 日前电价 {_f(r,'price_da'):.0f} 元/MWh。", ts)
        if _f(r, "congestion") >= 0.55:
            push("warn", "congestion", "阻塞压力", f"{ts} 阻塞指数 {_f(r,'congestion'):.2f}，分区价差可能拉大。", ts)

    prev = None
    for r in (future or [])[:72]:
        if prev is not None:
            d = abs(_f(r, "load_mw") - _f(prev, "load_mw"))
            if d > 7000:
                push("warn", "ramp", "负荷陡升/陡降", f"{r['ts']} 小时负荷变化 {d:.0f} MW，注意实时平衡与偏差考核。", r["ts"])
        prev = r

    # 去重：同一 code 只留最严重的前 8 条
    seen = defaultdict(int)
    kept = []
    for a in alerts:
        if seen[a["code"]] >= 3:
            continue
        seen[a["code"]] += 1
        kept.append(a)
        insert("power_alert", {
            "level": a["level"],
            "code": a["code"],
            "title": a["title"],
            "message": a["message"],
            "ts": a["ts"],
            "status": "open",
            "payload_json": dumps(a.get("payload") or {}),
        })
    return kept


def list_alerts(limit=40):
    return query("SELECT * FROM power_alert ORDER BY id DESC LIMIT %s", (int(limit),)) or []


def shock_scenario(kind="heatwave"):
    future = query(
        "SELECT * FROM power_hourly WHERE ts >= NOW() AND ts < DATE_ADD(NOW(), INTERVAL 72 HOUR) AND horizon <> 'actual' ORDER BY ts",
        [],
    ) or []
    shock = {"heatwave": {"d_temp": 3.5}, "coldwave": {"d_temp": -6}, "typhoon": {"d_wind": 8}, "storm": {"rad_scale": 0.45}}.get(kind, {})
    out = []
    for r in future:
        base = {
            "ts": r["ts"].isoformat() if hasattr(r["ts"], "isoformat") else str(r["ts"]),
            "temp_c": r.get("temp_c"),
            "wind_10m": r.get("wind_10m"),
            "wind_100m": r.get("wind_100m"),
            "wind_gust": r.get("wind_gust"),
            "radiation": r.get("radiation"),
        }
        powered = weather_to_power(base, shock)
        out.append({
            "ts": powered["ts"],
            "load_mw": powered["load_mw"],
            "wind_mw": powered["wind_mw"],
            "solar_mw": powered["solar_mw"],
            "price_da": powered["price_da"],
            "base_price": _f(r, "price_da"),
            "base_load": _f(r, "load_mw"),
        })
    if not out:
        return {"kind": kind, "delta_load_mw": 0, "delta_price": 0, "points": []}
    d_load = mean(p["load_mw"] - p["base_load"] for p in out)
    d_price = mean(p["price_da"] - p["base_price"] for p in out)
    return {"kind": kind, "delta_load_mw": round(d_load, 1), "delta_price": round(d_price, 2), "points": out[:48]}


def strategy_advice():
    nxt = query(
        """
        SELECT * FROM power_hourly
        WHERE ts >= NOW() AND ts < DATE_ADD(NOW(), INTERVAL 24 HOUR)
        ORDER BY ts
        """,
        [],
    ) or []
    if not nxt:
        return {"summary": "暂无未来 24h 序列，请先同步气象。", "actions": []}
    da = [_f(r, "price_da") for r in nxt]
    rt = [_f(r, "price_rt") for r in nxt]
    residual = [_f(r, "residual_mw") for r in nxt]
    peak_i = max(range(len(da)), key=lambda i: da[i])
    trough_i = min(range(len(da)), key=lambda i: da[i])
    spread = max(da) - min(da)
    rt_premium = mean(rt) - mean(da)
    cong = mean(_f(r, "congestion") for r in nxt)
    actions = []
    actions.append({
        "title": "日前报价带",
        "detail": (
            f"建议申报区间 {min(da)*0.97:.0f}–{max(da)*1.03:.0f} 元/MWh；"
            f"晚高峰参考 {da[peak_i]:.0f}（{str(nxt[peak_i]['ts'])[11:16]}），"
            f"低谷 {da[trough_i]:.0f}。"
        ),
    })
    if spread > 80:
        actions.append({
            "title": "峰谷套利窗口",
            "detail": f"未来 24h 价差约 {spread:.0f} 元/MWh，可考虑低谷买入 / 高峰卖出或移峰填谷，注意阻塞 {cong:.2f}。",
        })
    if rt_premium > 8:
        actions.append({
            "title": "实时偏差风险",
            "detail": f"实时较日前平均升水 {rt_premium:.1f} 元/MWh，新能源预测偏乐观时易产生正偏差考核，建议预留上调空间。",
        })
    else:
        actions.append({
            "title": "偏差考核",
            "detail": "实时与日前贴合较好，仍需按分时计划控制风光联合出力预测误差。",
        })
    if cong > 0.35:
        actions.append({
            "title": "阻塞对冲",
            "detail": "阻塞指数偏高，分区价差可能扩大，中长期合约建议保留位置对冲，避免在受阻断面满送。",
        })
    heat = any(_f(r, "temp_c") >= 33 for r in nxt)
    if heat:
        actions.append({
            "title": "高温应急",
            "detail": "未来 24h 出现高温，负荷晚高峰或超基准，可提前锁定部分高价时段持仓。",
        })
    return {
        "summary": (
            f"未来24h 日前均价 {mean(da):.0f} 元/MWh，峰谷价差 {spread:.0f}，"
            f"平均残余负荷 {mean(residual):.0f} MW。"
        ),
        "peak_hour": str(nxt[peak_i]["ts"]),
        "trough_hour": str(nxt[trough_i]["ts"]),
        "actions": actions,
    }


def cockpit_payload():
    rows = query("SELECT * FROM power_hourly ORDER BY ts", []) or []
    now = datetime.now()
    def dump(r):
        item = dict(r)
        ts = item.get("ts")
        item["ts"] = ts.strftime("%Y-%m-%d %H:%M") if hasattr(ts, "strftime") else str(ts)[:16]
        for k, v in list(item.items()):
            if hasattr(v, "quantize"):
                item[k] = float(v)
        return item

    series = [dump(r) for r in rows]
    future = [r for r in series if r["ts"] >= now.strftime("%Y-%m-%d %H:%M")]
    past = [r for r in series if r["ts"] < now.strftime("%Y-%m-%d %H:%M")]
    cur = (future[0] if future else (past[-1] if past else {}))
    next72 = [r for r in future if r["ts"] < (now + timedelta(hours=72)).strftime("%Y-%m-%d %H:%M")]
    kpis = {
        "temp": _num(cur.get("temp_c")),
        "load": _num(cur.get("load_mw")),
        "wind": _num(cur.get("wind_mw")),
        "solar": _num(cur.get("solar_mw")),
        "price_da": _num(cur.get("price_da")),
        "price_rt": _num(cur.get("price_rt")),
        "congestion": _num(cur.get("congestion")),
        "renew_share": round(100 * (_num(cur.get("wind_mw")) + _num(cur.get("solar_mw"))) / max(_num(cur.get("load_mw")), 1), 1),
    }
    daily = []
    bucket = defaultdict(list)
    for r in series:
        bucket[r["ts"][:10]].append(r)
    for day in sorted(bucket):
        pts = bucket[day]
        daily.append({
            "date": day,
            "temp": round(mean(_num(p.get("temp_c")) for p in pts), 2),
            "load": round(mean(_num(p.get("load_mw")) for p in pts), 1),
            "wind": round(mean(_num(p.get("wind_mw")) for p in pts), 1),
            "solar": round(mean(_num(p.get("solar_mw")) for p in pts), 1),
            "price": round(mean(_num(p.get("price_da")) for p in pts), 1),
            "horizon": pts[0].get("horizon"),
        })
    return {
        "kpis": kpis,
        "current": cur,
        "series": past[-24:] + next72,
        "daily": daily,
        "alerts": [dump(a) for a in list_alerts(30)],
        "strategy": strategy_advice(),
        "shocks": {
            "heatwave": shock_scenario("heatwave"),
            "coldwave": shock_scenario("coldwave"),
            "typhoon": shock_scenario("typhoon"),
            "storm": shock_scenario("storm"),
        },
        "meta": {
            "points": len(series),
            "updated": now.strftime("%Y-%m-%d %H:%M"),
            "sources": "Open-Meteo ERA5 / ECMWF IFS / GFS；电力量为气象驱动物理-统计模型（华东尺度）",
        },
    }


def latest_report():
    return query("SELECT * FROM power_report ORDER BY id DESC LIMIT 1", one=True)


def save_report(title, content, rag_context="", user=None):
    user = user or {}
    return insert("power_report", {
        "title": title,
        "content": content,
        "rag_context": rag_context,
        "user_id": user.get("id"),
        "username": user.get("username"),
    })
