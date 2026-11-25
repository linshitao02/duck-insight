# -*- coding: utf-8 -*-
"""电力场景标签与特征列约定：训练时去掉其它 label，只留特征。"""

LABEL_COLS = {
    "load_mw",
    "renewable_mw",
    "wind_mw",
    "solar_mw",
    "price_da",
    "price_rt",
}

# 日前电价可以把上游模型的负荷/风电/光伏/风光合计预测当作特征
PRICE_INPUT_LABELS = {"load_mw", "wind_mw", "solar_mw", "renewable_mw"}

ID_COLS = {
    "ts",
    "row_key",
    "site_name",
    "weather_source",
    "event_type",
    "residual_mw",
    "congestion",
}


def feature_cols_for_target(columns, target):
    skip = set(LABEL_COLS) | set(ID_COLS) | {target}
    if target == "price_da":
        skip -= PRICE_INPUT_LABELS
    cols = []
    for item in columns or []:
        name = item.get("name") if isinstance(item, dict) else item
        if name and name not in skip:
            cols.append(name)
    return cols
