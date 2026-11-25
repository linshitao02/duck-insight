# -*- coding: utf-8 -*-
"""字段英文名 → 中文释义。未知列返回空字符串，可由用户手工填写。"""

FIELD_ZH = {
    "row_key": "行关联键",
    "ts": "时间",
    "site": "站点编码",
    "site_name": "站点名称",
    "lat": "纬度",
    "lon": "经度",
    "temp_c": "气温",
    "humidity": "相对湿度",
    "precip_mm": "降水量",
    "wind_10m": "10米风速",
    "wind_100m": "100米风速",
    "wind_gust": "阵风",
    "radiation": "短波辐射",
    "weather_code": "天气代码",
    "is_cold_wave": "寒潮标记",
    "is_heat_wave": "热浪标记",
    "is_typhoon": "台风标记",
    "is_convection": "强对流标记",
    "event_type": "极端事件类型",
    "weather_source": "气象来源",
    "load_mw": "用电负荷",
    "wind_mw": "风电出力",
    "solar_mw": "光伏出力",
    "renewable_mw": "风光出力",
    "residual_mw": "残余负荷",
    "congestion": "阻塞指数",
    "price_da": "日前电价",
    "price_rt": "实时电价",
    "year": "年",
    "month": "月",
    "day": "日",
    "hour": "小时",
    "minute": "分钟",
    "second": "秒",
    "weekday": "星期",
    "week": "周序号",
    "quarter": "季度",
    "Store": "门店",
    "DayOfWeek": "星期",
    "Date": "日期",
    "Sales": "销售额",
    "Customers": "客流量",
    "Open": "是否营业",
    "Promo": "促销",
    "StateHoliday": "法定假日",
    "SchoolHoliday": "学校假期",
    "StoreType": "门店类型",
    "Assortment": "商品组合",
    "CompetitionDistance": "竞品距离",
    "CompetitionOpenSinceMonth": "竞品开业月",
    "CompetitionOpenSinceYear": "竞品开业年",
    "Promo2": "持续促销",
    "Promo2SinceWeek": "持续促销起始周",
    "Promo2SinceYear": "持续促销起始年",
    "PromoInterval": "促销间隔",
}


def label_zh_for(name):
    raw = str(name or "")
    if raw in FIELD_ZH:
        return FIELD_ZH[raw]
    base = raw.split("__")[0]
    return FIELD_ZH.get(base, "")


def parse_join_col(name):
    raw = str(name or "")
    if "__d" in raw:
        base, _, suffix = raw.rpartition("__d")
        if base and suffix.isdigit():
            return base, int(suffix)
    return raw, None


def _dataset_cols(ds):
    schema = ds.get("schema") or []
    names = []
    for c in schema:
        names.append(c if isinstance(c, str) else (c or {}).get("name"))
    if names:
        return [n for n in names if n]
    cols = ((ds.get("profile") or {}).get("columns") or [])
    return [c.get("name") for c in cols if c.get("name")]


def feature_tick(col):
    """特征重要性轴/导出：字段名(中文释义)。"""
    raw = str(col or "").strip()
    if not raw:
        return ""
    name, _ = parse_join_col(raw)
    zh = label_zh_for(name)
    return f"{raw}({zh})" if zh else raw


def header_for_column(col, datasets=None, fact_id=None):
    """英文字段 + 中文释义；无释义不加括号。多表同名时再带来源表。"""
    name, ds_id = parse_join_col(col)
    zh = label_zh_for(name)
    table = ""
    datasets = datasets or []
    by_id = {int(d["id"]): d for d in datasets if d.get("id") is not None}
    owners = [d for d in datasets if name in _dataset_cols(d)]
    if ds_id and ds_id in by_id:
        table = by_id[ds_id].get("name") or ""
    elif fact_id is not None and int(fact_id) in by_id and name in _dataset_cols(by_id[int(fact_id)]):
        table = by_id[int(fact_id)].get("name") or ""
    elif len(owners) == 1:
        table = owners[0].get("name") or ""
    if not zh:
        return name
    bits = [zh]
    if (ds_id or len(owners) > 1) and table and table != zh:
        bits.append(table)
    return f"{name}（{' · '.join(bits)}）"
