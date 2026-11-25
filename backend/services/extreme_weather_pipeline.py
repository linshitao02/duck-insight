# -*- coding: utf-8 -*-
"""把极端天气负荷/风光数据集导入数据空间，配置清洗规则，并启动两个独立训练任务。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
from flask import g

from services import clean_service, dataset_service, model_service, project_service
from trainers.zoo import OPTIONAL
from utils.db import query
from utils.jsonx import dumps
from utils.power_features import LABEL_COLS, feature_cols_for_target

ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = ROOT / "dataset"
if str(DATASET_DIR) not in sys.path:
    sys.path.insert(0, str(DATASET_DIR))

PROJECT_NAME = "极端天气负荷与风光出力"
RULE_NAME = "极端天气电力质控"
LIVE_RULE_NAME = "极端天气电力质控-实时"
SCENARIO = "power_trading"

WEATHER_TABLE = "气象与极端事件"
LOAD_TABLE = "用电负荷"
RENEWABLE_TABLE = "风光出力"
PRICE_TABLE = "日前电价"
WIDE_TABLE = "负荷风光训练宽表"
BUNDLE_NAME = "气象 × 负荷 × 风光"

LABEL_LOAD = "load_mw"
LABEL_RENEWABLE = "renewable_mw"
LABEL_WIND = "wind_mw"
LABEL_SOLAR = "solar_mw"
LABEL_PRICE = "price_da"
JOB_LOAD = "极端天气-用电负荷预测"
JOB_RENEWABLE = "极端天气-风光出力预测"
JOB_WIND = "极端天气-风电出力预测"
JOB_SOLAR = "极端天气-光伏出力预测"
JOB_PRICE = "日前电价预测"
LEAK_COLS = set(LABEL_COLS)


def _admin_user():
    user = getattr(g, "user", None) or {}
    if user.get("id"):
        return user
    row = query("SELECT * FROM sys_user WHERE username=%s", ("admin",), one=True) or {}
    g.user = row
    return row


def _steps():
    nodes = [
        {"id": "ew1", "op": "parse_date", "column": "ts", "extract": ["year", "month", "day", "weekday", "hour", "minute", "second"]},
        {"id": "ew2", "op": "clip_outlier", "method": "range", "ranges": [
            {"columns": ["temp_c"], "method": "range", "low": -30, "high": 48},
            {"columns": ["wind_10m", "wind_100m", "wind_gust"], "method": "range", "low": 0, "high": 55},
            {"columns": ["precip_mm", "radiation"], "method": "range", "low": 0, "high": 1200},
        ]},
        {"id": "ew5", "op": "fill_missing", "strategy": "auto", "overrides": []},
        {"id": "ew6", "op": "drop_duplicates", "columns": ["row_key"]},
        {"id": "ew7", "op": "drop_columns", "columns": ["ts", "row_key", "site_name", "weather_source", "event_type"]},
        {"id": "ew8", "op": "label_encode", "columns": ["site"], "auto_mode": False},
    ]
    edges = [{"from": nodes[i]["id"], "to": nodes[i + 1]["id"]} for i in range(len(nodes) - 1)]
    return nodes, edges


def ensure_files(force=False):
    from build_extreme_weather_dataset import build
    return build(force=force)


def ensure_project():
    _admin_user()
    row = query(
        "SELECT * FROM data_project WHERE name=%s AND scenario_code=%s AND status=1",
        (PROJECT_NAME, SCENARIO),
        one=True,
    )
    if row:
        return project_service.get_project(row["id"])
    return project_service.create_project({
        "name": PROJECT_NAME,
        "description": "寒潮/热浪/台风/强对流对用电负荷与风光出力的影响。负荷与风光是两个独立标签，分别训练模型。",
        "scenario_code": SCENARIO,
    })


def _upsert_csv(project_id, name, path, remark, target_col=None):
    df = pd.read_csv(path)
    ds = dataset_service.upsert_dataframe(
        project_id, name, df, scenario=SCENARIO, remark=remark, filename=Path(path).name,
        username=(_admin_user().get("username") or "admin"),
    )
    dataset_service.fill_zh_labels(ds["id"], overwrite=False)
    ds = dataset_service.get_dataset(ds["id"])
    if target_col:
        cols = (ds.get("profile") or {}).get("columns") or []
        for c in cols:
            if c.get("name") == target_col:
                c["role"] = "target"
            elif c.get("name") in LEAK_COLS:
                c["role"] = "leakage"
                c["included"] = False
        dataset_service.update_field_schema(ds["id"], cols)
        from utils.db import update as db_update
        fresh = dataset_service.get_dataset(ds["id"])
        profile = fresh.get("profile") or {}
        profile["meta"] = {**(profile.get("meta") or {}), "target_col": target_col}
        db_update("dataset", {"profile_json": dumps(profile)}, "id=%s", (ds["id"],))
        ds = dataset_service.get_dataset(ds["id"])
    return ds


def _rule_source_for_dataset(name):
    row = query(
        "SELECT id, project_id FROM dataset WHERE name=%s AND status=1 ORDER BY id DESC",
        (name,),
        one=True,
    )
    if not row:
        return {}
    return {
        "project_id": row.get("project_id"),
        "target_type": "dataset",
        "target_id": row.get("id"),
    }


def ensure_rule():
    steps, edges = _steps()
    payload = {
        "name": RULE_NAME,
        "scenario_code": SCENARIO,
        "description": "拆解小时特征、物理阈值裁剪、缺失填充、去掉原始时间戳，站点标签编码。不删除负荷/风光标签。",
        "steps": steps,
        "edges": edges,
        "source": _rule_source_for_dataset(WIDE_TABLE),
        "is_preset": 1,
    }
    row = query("SELECT * FROM clean_rule WHERE name=%s AND status=1", (RULE_NAME,), one=True)
    if row:
        return clean_service.save_rule(payload, row["id"])
    return clean_service.save_rule(payload)


def ensure_live_rule():
    """复制极端天气质控流程，绑定电力小时活表，供实时 DAG 使用。"""
    from services import live_ops

    pack = live_ops.lookup_live_assets()
    ds = (pack or {}).get("dataset") or {}
    project = (pack or {}).get("project") or {}
    source = {}
    if ds.get("id"):
        source = {
            "project_id": project.get("id") or ds.get("project_id"),
            "target_type": "dataset",
            "target_id": ds.get("id"),
        }
    else:
        source = _rule_source_for_dataset(live_ops.DATASET_NAME)
    steps, edges = _steps()
    payload = {
        "name": LIVE_RULE_NAME,
        "scenario_code": SCENARIO,
        "description": "实时活表：拆解小时特征、物理阈值裁剪、缺失填充、去重、去掉原始时间戳，站点标签编码。",
        "steps": steps,
        "edges": edges,
        "source": source,
        "is_preset": 0,
    }
    row = query("SELECT * FROM clean_rule WHERE name=%s AND status=1", (LIVE_RULE_NAME,), one=True)
    if row:
        return clean_service.save_rule(payload, row["id"])
    return clean_service.save_rule(payload)


def _feature_cols(columns, target):
    return feature_cols_for_target(columns, target)


def _model_choice():
    if "lightgbm" in OPTIONAL:
        return "lightgbm", {
            "n_estimators": 400, "learning_rate": 0.05, "num_leaves": 48,
            "subsample": 0.8, "colsample_bytree": 0.8,
        }
    if "xgboost" in OPTIONAL:
        return "xgboost", {
            "n_estimators": 400, "max_depth": 8, "learning_rate": 0.05,
            "min_child_weight": 3, "subsample": 0.9, "colsample_bytree": 0.7,
        }
    return "random_forest", {"n_estimators": 160, "max_depth": 12, "min_samples_leaf": 2}


def import_assets(force_rebuild=False, project_id=None):
    files = ensure_files(force=force_rebuild)
    if project_id:
        project = project_service.get_project(int(project_id))
        if not project:
            raise ValueError("数据集配置不存在")
    else:
        project = ensure_project()
    pid = project["id"]
    from build_extreme_weather_dataset import ensure_price_files
    files = dict(files)
    files.update(ensure_price_files(force=False))
    weather_ds = _upsert_csv(pid, WEATHER_TABLE, files["weather"], "ERA5/气候态气象 + 寒潮热浪台风强对流标记")
    load_ds = _upsert_csv(pid, LOAD_TABLE, files["load"], "用电负荷小时序列（标签 load_mw）", LABEL_LOAD)
    re_ds = _upsert_csv(pid, RENEWABLE_TABLE, files["renewable"], "风电+光伏出力（标签 wind_mw / solar_mw）", LABEL_RENEWABLE)
    price_ds = _upsert_csv(pid, PRICE_TABLE, files["price"], "日前/实时电价（标签 price_da，离线构造）", LABEL_PRICE)
    wide_ds = _upsert_csv(pid, WIDE_TABLE, files["wide"], "训练宽表：气象特征 + 负荷/风电/光伏/电价", LABEL_LOAD)

    existing = query(
        "SELECT * FROM dataset_bundle WHERE project_id=%s AND name=%s AND status=1",
        (pid, BUNDLE_NAME),
        one=True,
    )
    joins = [
        {
            "left_dataset_id": weather_ds["id"],
            "right_dataset_id": load_ds["id"],
            "how": "left",
            "left_key": "row_key",
            "right_key": "row_key",
            "keys": [
                {"left_key": "row_key", "right_key": "row_key"},
                {"left_key": "ts", "right_key": "ts"},
                {"left_key": "site", "right_key": "site"},
            ],
        },
        {
            "left_dataset_id": weather_ds["id"],
            "right_dataset_id": re_ds["id"],
            "how": "left",
            "left_key": "row_key",
            "right_key": "row_key",
            "keys": [
                {"left_key": "row_key", "right_key": "row_key"},
                {"left_key": "ts", "right_key": "ts"},
                {"left_key": "site", "right_key": "site"},
            ],
        },
        {
            "left_dataset_id": weather_ds["id"],
            "right_dataset_id": price_ds["id"],
            "how": "left",
            "left_key": "row_key",
            "right_key": "row_key",
            "keys": [
                {"left_key": "row_key", "right_key": "row_key"},
                {"left_key": "ts", "right_key": "ts"},
                {"left_key": "site", "right_key": "site"},
            ],
        },
    ]
    dataset_ids = [weather_ds["id"], load_ds["id"], re_ds["id"], price_ds["id"]]
    if existing:
        bundle = dataset_service.rebuild_bundle(
            existing["id"],
            name=BUNDLE_NAME,
            dataset_ids=dataset_ids,
            joins=joins,
            fact_dataset_id=weather_ds["id"],
            remark="按 row_key AND ts AND site 关联气象、负荷、风光、电价",
            selected_fields=[],
        )
    else:
        bundle = dataset_service.create_bundle(
            BUNDLE_NAME,
            dataset_ids,
            joins,
            fact_dataset_id=weather_ds["id"],
            scenario=SCENARIO,
            remark="按 row_key AND ts AND site 关联气象、负荷、风光、电价",
            project_id=pid,
        )
    rule = ensure_rule()
    binding = clean_service.bind_and_materialize("bundle", bundle["id"], rule["id"], name=f"{BUNDLE_NAME}-{RULE_NAME}")
    return {
        "project": project,
        "datasets": {
            "weather": weather_ds,
            "load": load_ds,
            "renewable": re_ds,
            "price": price_ds,
            "wide": wide_ds,
        },
        "bundle": bundle,
        "rule": rule,
        "binding": binding,
    }


def latest_success_job(name, target_col=None):
    sql = "SELECT * FROM train_job WHERE name=%s AND status='success'"
    args = [name]
    if target_col:
        sql += " AND target_col=%s"
        args.append(target_col)
    sql += " ORDER BY id DESC"
    row = query(sql, args, one=True)
    return model_service.serialize_job(row) if row else None


def start_models(imported, reuse=True):
    binding = imported["binding"]
    schema = binding.get("schema") or []
    if isinstance(schema, str):
        from utils.jsonx import loads
        schema = loads(schema, default=[])
    columns = list(schema)
    if not columns:
        df, *_ = model_service.prepare_frame("bundle", imported["bundle"]["id"], binding_id=binding["id"])
        columns = list(df.columns)
    model_type, params = _model_choice()
    jobs = []
    for name, target in (
        (JOB_LOAD, LABEL_LOAD),
        (JOB_RENEWABLE, LABEL_RENEWABLE),
        (JOB_WIND, LABEL_WIND),
        (JOB_SOLAR, LABEL_SOLAR),
    ):
        if reuse:
            existing = latest_success_job(name, target)
            if existing:
                jobs.append(existing)
                continue
        feats = _feature_cols(columns, target)
        job = model_service.create_and_run({
            "name": name,
            "scenario_code": SCENARIO,
            "target_type": "bundle",
            "target_id": imported["bundle"]["id"],
            "binding_id": binding["id"],
            "rule_id": None,
            "target_col": target,
            "feature_cols": feats,
            "task_type": "regression",
            "model_type": model_type,
            "params": params,
            "sample_rows": 0,
            "test_size": 0.2,
            "random_state": 42,
            "log_target": False,
        })
        jobs.append(job)
    return jobs


def wait_jobs(jobs, timeout=600):
    ids = [j["id"] for j in jobs]
    deadline = time.time() + timeout
    latest = []
    while time.time() < deadline:
        latest = [model_service.get_job(i) for i in ids]
        if all((j or {}).get("status") in ("success", "failed") for j in latest):
            return latest
        time.sleep(3)
    return latest or [model_service.get_job(i) for i in ids]


def sync(force_rebuild=False, train=True, wait=True):
    _admin_user()
    imported = import_assets(force_rebuild=force_rebuild)
    result = {"import": {
        "project_id": imported["project"]["id"],
        "dataset_ids": {k: v["id"] for k, v in imported["datasets"].items()},
        "bundle_id": imported["bundle"]["id"],
        "rule_id": imported["rule"]["id"],
        "binding_id": imported["binding"]["id"],
        "binding_rows": imported["binding"].get("n_rows"),
    }}
    if train:
        jobs = start_models(imported)
        result["jobs"] = [{"id": j["id"], "name": j["name"], "status": j["status"]} for j in jobs]
        if wait:
            done = wait_jobs(jobs)
            result["jobs"] = [{
                "id": j["id"],
                "name": j["name"],
                "status": j["status"],
                "target_col": j.get("target_col"),
                "model_type": j.get("model_type"),
                "metrics": j.get("metrics"),
                "log_tail": (j.get("log_text") or "")[-400:],
            } for j in done]
    try:
        from services.graph_service import ensure_extreme_weather_dags
        dags = ensure_extreme_weather_dags()
        result["dags"] = [{"id": g.get("id"), "name": g.get("name")} for g in (dags or [])]
    except Exception as e:
        result["dags_error"] = str(e)
    return result
