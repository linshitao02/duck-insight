# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import threading
import time
import traceback
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
from flask import g
from sklearn.base import clone
from sklearn.metrics import (
    accuracy_score, f1_score, mean_absolute_error, mean_squared_error,
    precision_score, r2_score, recall_score, roc_auc_score,
)
from sklearn.model_selection import train_test_split


from config import get_user_dir, to_abs, to_rel
from services import clean_service, dataset_service
from trainers.zoo import build_estimator, coerce_task_type, list_zoo, native_importance, perm_importance
from utils.cleaner import CleanEngine
from utils.db import delete, insert, query, update
from utils.jsonx import dumps, json_safe, loads, row_to_dict


PENDING_FRAMES = {}


def _split_params(raw):
    params = dict(raw or {})
    preset = params.pop("_preset", None) or params.pop("param_preset", None)
    return params, preset


def _generated_feature_cols(steps):
    """返回清洗规则生成的数值特征，确保日期拆解列真正进入模型。"""
    out = []
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        if step.get("op") == "parse_date":
            extracts = step.get("extract")
            if extracts is None:
                extracts = ["year", "month", "day", "weekday", "hour", "minute", "second"]
            for name in extracts:
                if name and name not in out:
                    out.append(name)
        elif step.get("op") == "split_flags":
            prefix = step.get("prefix") or str(step.get("column") or "").lower()
            for token in step.get("tokens") or []:
                name = f"{prefix}{str(token).lower()}"
                if name and name not in out:
                    out.append(name)
    return out


def serialize_job(row):
    if not row:
        return None
    data = row_to_dict(row)
    params, preset = _split_params(loads(row.get("params_json"), default={}))
    data["params"] = params
    data["param_preset"] = preset
    data["feature_cols"] = loads(row.get("feature_cols_json"), default=[])
    data["metrics"] = loads(row.get("metrics_json"), default={})
    data["importance"] = loads(row.get("importance_json"), default=[])
    data["curves"] = loads(row.get("curves_json"), default={})
    return data


def list_jobs(keyword=None, status=None):
    sql = "SELECT * FROM train_job WHERE 1=1"
    args = []
    user = getattr(g, "user", {}) or {}
    if user.get("role") != "admin":
        sql += " AND user_id=%s"
        args.append(user.get("id"))
    if status:
        sql += " AND status=%s"
        args.append(status)
    if keyword:
        like = f"%{keyword.strip()}%"
        sql += " AND (name LIKE %s OR model_type LIKE %s OR IFNULL(target_col,'') LIKE %s)"
        args.extend([like, like, like])
    sql += " ORDER BY create_time DESC, id DESC"
    return [serialize_job(r) for r in query(sql, args)]


def get_job(job_id):
    data = serialize_job(query("SELECT * FROM train_job WHERE id=%s", (job_id,), one=True))
    if not data:
        return None
    ins = query(
        "SELECT id, title, content FROM insight_report WHERE train_job_id=%s ORDER BY id DESC",
        (job_id,), one=True,
    )
    data["insight"] = (ins or {}).get("content") or ""
    data["insight_title"] = (ins or {}).get("title") or ""
    data["insight_id"] = (ins or {}).get("id")
    return data


def delete_job(job_id):
    job = get_job(job_id)
    if not job:
        raise ValueError("任务不存在")
    for key in ("model_path", "artifact_path"):
        path = to_abs(job.get(key))
        if path and os.path.exists(path) and os.path.isfile(path):
            try:
                os.remove(path)
            except Exception:
                pass
    delete("train_job", "id=%s", (job_id,))
    return True


def _parse_ids(raw, limit=200):
    out, seen = [], set()
    for item in raw or []:
        try:
            value = int(item)
        except (TypeError, ValueError):
            continue
        if value <= 0 or value in seen:
            continue
        seen.add(value)
        out.append(value)
        if len(out) >= limit:
            break
    return out


def delete_jobs(job_ids):
    ids = _parse_ids(job_ids)
    deleted, missing = [], []
    for job_id in ids:
        if not get_job(job_id):
            missing.append(job_id)
            continue
        delete_job(job_id)
        deleted.append(job_id)
    return {"deleted": len(deleted), "ids": deleted, "missing": missing}


def _append_log(job_id, line):
    row = query("SELECT log_text FROM train_job WHERE id=%s", (job_id,), one=True)
    text = (row.get("log_text") or "") + line + "\n"
    update("train_job", {"log_text": text}, "id=%s", (job_id,))


def rmspe(y_true, y_pred):
    y_true = np.array(y_true, dtype=float)
    y_pred = np.array(y_pred, dtype=float)
    mask = y_true != 0
    if mask.sum() == 0:
        return None
    return float(np.sqrt(np.mean(((y_true[mask] - y_pred[mask]) / y_true[mask]) ** 2)))


def mape(y_true, y_pred):
    y_true = np.array(y_true, dtype=float)
    y_pred = np.array(y_pred, dtype=float)
    mask = y_true != 0
    if mask.sum() == 0:
        return None
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])))


def prepare_frame(target_type, target_id, rule_id=None, binding_id=None, sample_rows=0):
    engine = CleanEngine()
    steps = []
    if str(target_type or "") in ("live", "source", "mysql", "mysql_live"):
        target_type = "dataset"
    source_type, source_id = target_type, target_id
    if binding_id:
        binding = clean_service.get_binding(binding_id)
        if not binding:
            raise ValueError("绑定不存在")
        source_type = binding.get("target_type") or target_type
        source_id = binding.get("target_id") or target_id
        rule = binding.get("rule") or {}
        steps = clean_service.ordered_steps(rule.get("steps") or [], rule.get("edges"))
        restored = _load_binding_engine(binding)
        if restored is not None:
            df, engine = restored
            if sample_rows and sample_rows > 0 and len(df) > sample_rows:
                df = df.sample(n=int(sample_rows), random_state=42)
            return df, engine, steps, True
    elif rule_id:
        rule = clean_service.get_rule(rule_id)
        if not rule:
            raise ValueError("清洗规则不存在")
        steps = clean_service.ordered_steps(rule.get("steps") or [], rule.get("edges"))
    df, _ = dataset_service.load_source_frame(source_type, source_id)
    if steps:
        df = engine.fit_transform(df, steps)
    if sample_rows and sample_rows > 0 and len(df) > sample_rows:
        df = df.sample(n=int(sample_rows), random_state=42)
    return df, engine, steps, False


def _load_binding_engine(binding):
    engine_path = binding.get("engine_path")
    snap = binding.get("snapshot_path")
    if not engine_path or not snap:
        return None
    from utils.io import load_dataframe
    abs_engine = to_abs(engine_path)
    abs_snap = to_abs(snap)
    if not os.path.exists(abs_engine) or not os.path.exists(abs_snap):
        return None
    engine = CleanEngine()
    engine.load_state(joblib.load(abs_engine))
    df = load_dataframe(abs_snap)
    return df, engine


def guess_target(columns):
    for name in columns:
        low = str(name).lower()
        if low in ("sales", "target", "label", "y", "销量", "销售额", "load_mw", "load", "负荷", "renewable_mw", "wind_mw", "solar_mw", "price_da"):
            return str(name)
    return str(columns[-1]) if columns else None


def _normalize_target_type(tt):
    tt = tt or "bundle"
    if str(tt) in ("live", "source", "mysql", "mysql_live"):
        return "dataset"
    return tt


def _job_row_fields(payload, user, extra=None):
    name = payload.get("name") or f"{payload.get('model_type')}-{datetime.now().strftime('%m%d%H%M')}"
    params = dict(payload.get("params") or {})
    params.pop("_preset", None)
    preset = payload.get("param_preset") or payload.get("preset")
    if preset:
        params["_preset"] = str(preset)
    tt = _normalize_target_type(payload.get("target_type") or "bundle")
    model_type = payload.get("model_type") or "random_forest"
    task_type = coerce_task_type(model_type, payload.get("task_type") or "regression")
    fields = {
        "name": name,
        "scenario_code": payload.get("scenario_code") or "store_sales",
        "target_type": tt,
        "target_id": payload.get("target_id"),
        "rule_id": payload.get("rule_id"),
        "binding_id": payload.get("binding_id"),
        "model_type": model_type,
        "task_type": task_type,
        "params_json": dumps(params),
        "feature_cols_json": dumps(payload.get("feature_cols") or []),
        "target_col": payload.get("target_col"),
        "sample_rows": 0 if str(preset or "").lower() == "accurate" else (payload.get("sample_rows") or 0),
        "test_size": payload.get("test_size") or 0.2,
        "random_state": payload.get("random_state") or 42,
        "log_target": 0 if task_type == "classification" else (1 if payload.get("log_target") else 0),
        "status": "pending",
        "progress": 0,
        "user_id": user.get("id"),
        "username": user.get("username"),
    }
    if extra:
        fields.update(extra)
    return fields


def create_and_run(payload, wait=False, frame=None, engine_state=None, steps=None):
    user = getattr(g, "user", {}) or {}
    fields = _job_row_fields(payload, user)
    job_id = insert("train_job", fields)
    if frame is not None:
        PENDING_FRAMES[int(job_id)] = {
            "frame": frame,
            "engine_state": engine_state,
            "steps": steps or [],
        }
    thread = threading.Thread(target=_run_job, args=(job_id,), daemon=True)
    thread.start()
    if wait:
        job = wait_job(job_id)
        if (job or {}).get("status") == "failed":
            raise ValueError((job or {}).get("error_message") or f"训练失败 #{job_id}")
        return job
    return get_job(job_id)


def wait_job(job_id, timeout=900):
    deadline = time.time() + timeout
    latest = None
    while time.time() < deadline:
        latest = get_job(job_id)
        if (latest or {}).get("status") in ("success", "failed"):
            return latest
        time.sleep(2)
    raise TimeoutError(f"训练任务 #{job_id} 等待超时")


def _run_job(job_id):
    started = time.time()
    try:
        update("train_job", {"status": "running", "progress": 5, "log_text": "开始准备数据\n"}, "id=%s", (job_id,))
        job = query("SELECT * FROM train_job WHERE id=%s", (job_id,), one=True)
        frame = PENDING_FRAMES.pop(int(job_id), None)
        if frame is not None:
            pack = frame
            if isinstance(pack, dict) and pack.get("frame") is not None:
                df = pack["frame"].copy()
                engine = CleanEngine()
                if pack.get("engine_state"):
                    engine.load_state(pack["engine_state"])
                steps = pack.get("steps") or []
            else:
                df = pack.copy()
                engine = CleanEngine()
                steps = []
            sample_rows = int(job.get("sample_rows") or 0)
            if sample_rows and sample_rows > 0 and len(df) > sample_rows:
                df = df.sample(n=sample_rows, random_state=int(job.get("random_state") or 42))
            if not engine.has_preprocess() and job.get("binding_id"):
                binding = clean_service.get_binding(job["binding_id"]) or {}
                restored = _load_binding_engine(binding)
                if restored is not None:
                    _snap, engine = restored
                    if not steps:
                        rule = binding.get("rule") or {}
                        steps = clean_service.ordered_steps(rule.get("steps") or [], rule.get("edges"))
            already_clean = True
            _append_log(
                job_id,
                f"使用 DAG 注入数据 {df.shape}，编码器 {len(engine.encoders)} 列，标准化={'是' if engine.scaler is not None else '否'}",
            )
        else:
            df, engine, steps, already_clean = prepare_frame(
                job["target_type"], job["target_id"], job.get("rule_id"), job.get("binding_id"),
                int(job.get("sample_rows") or 0),
            )
        _append_log(job_id, f"数据形状 {df.shape}")
        update("train_job", {"progress": 25}, "id=%s", (job_id,))

        target_col = job.get("target_col") or guess_target(df.columns)
        if target_col not in df.columns:
            raise ValueError(f"目标列不存在: {target_col}")
        feature_cols = loads(job.get("feature_cols_json"), default=[]) or [
            c for c in df.columns if c != target_col and pd.api.types.is_numeric_dtype(df[c])
        ]
        feature_cols = [c for c in feature_cols if c in df.columns and c != target_col]
        seen = set()
        feature_cols = [c for c in feature_cols if not (c in seen or seen.add(c))]
        try:
            from utils.power_features import feature_cols_for_target
            allowed = set(feature_cols_for_target(list(df.columns), target_col))
            if allowed:
                feature_cols = [c for c in feature_cols if c in allowed] or list(allowed)
        except Exception:
            pass
        if not feature_cols:
            # 把非目标列尽量转数值
            work = df.copy()
            for c in work.columns:
                if c == target_col:
                    continue
                if not pd.api.types.is_numeric_dtype(work[c]):
                    work[c] = pd.factorize(work[c].astype(str))[0]
            df = work
            feature_cols = [c for c in df.columns if c != target_col]
        seen = set()
        feature_cols = [c for c in feature_cols if not (c in seen or seen.add(c))]
        generated_cols = [
            c for c in _generated_feature_cols(steps)
            if c in df.columns and c != target_col and pd.api.types.is_numeric_dtype(df[c])
        ]
        for col in generated_cols:
            if col not in feature_cols:
                feature_cols.append(col)
        if generated_cols:
            _append_log(job_id, f"自动加入清洗生成特征：{', '.join(generated_cols)}")
        # 清洗可能扫过全部数值列；训练只对勾选特征重新标准化
        df = engine.restrict_scaler_to_features(df, feature_cols, exclude={target_col})
        target_restored = target_col not in (engine.scale_cols or [])
        _append_log(
            job_id,
            f"标准化交集 {len(engine.scale_cols or [])} 列：{', '.join(engine.scale_cols or []) or '无'}",
        )
        X = df[feature_cols].apply(pd.to_numeric, errors="coerce").fillna(0).values
        y = pd.to_numeric(df[target_col], errors="coerce").fillna(0).values
        log_target = int(job.get("log_target") or 0)
        if log_target:
            y_model = np.log1p(np.clip(y, 0, None))
        else:
            y_model = y
        test_size = float(job.get("test_size") or 0.2)
        X_train, X_valid, y_train, y_valid, y_raw_train, y_raw_valid = train_test_split(
            X, y_model, y, test_size=test_size, random_state=int(job.get("random_state") or 42)
        )
        _append_log(job_id, f"训练 {len(X_train)} / 验证 {len(X_valid)}，特征 {len(feature_cols)}")
        update("train_job", {"progress": 40, "feature_cols_json": dumps(feature_cols), "target_col": target_col}, "id=%s", (job_id,))

        params, _preset = _split_params(loads(job.get("params_json"), default={}) or {})
        model = build_estimator(job["model_type"], job.get("task_type") or "regression", params)
        _append_log(job_id, "开始拟合模型")
        history = _fit_model(
            model, X_train, y_train, job_id, job.get("model_type"), params,
            X_valid=X_valid, y_valid=y_valid, task=job.get("task_type") or "regression",
        ) or {}
        update("train_job", {"progress": 82}, "id=%s", (job_id,))
        pred_model = model.predict(X_valid)
        if log_target:
            pred = np.clip(np.expm1(pred_model), 0, None)
            y_eval = y_raw_valid
        else:
            pred = pred_model
            y_eval = y_raw_valid if not log_target else y_valid

        task = job.get("task_type") or "regression"
        if task == "classification":
            pred_label = np.round(pred).astype(int) if pred.dtype != int else pred
            metrics = {
                "accuracy": float(accuracy_score(y_eval, pred_label)),
                "precision": float(precision_score(y_eval, pred_label, average="weighted", zero_division=0)),
                "recall": float(recall_score(y_eval, pred_label, average="weighted", zero_division=0)),
                "f1": float(f1_score(y_eval, pred_label, average="weighted", zero_division=0)),
            }
            try:
                if hasattr(model, "predict_proba"):
                    proba = model.predict_proba(X_valid)
                    if proba.shape[1] == 2:
                        metrics["auc"] = float(roc_auc_score(y_eval, proba[:, 1]))
            except Exception:
                pass
        else:
            metrics = {
                "rmse": float(np.sqrt(mean_squared_error(y_eval, pred))),
                "mae": float(mean_absolute_error(y_eval, pred)),
                "r2": float(r2_score(y_eval, pred)),
                "mape": mape(y_eval, pred),
                "rmspe": rmspe(y_eval, pred),
            }

        importance = native_importance(model, feature_cols)
        if not importance:
            try:
                n_max = 160 if str(job.get("model_type") or "").lower() == "bert" else 2500
                n_rep = 1 if n_max <= 160 else 3
                importance = perm_importance(model, X_valid, y_valid, feature_cols, n_repeats=n_rep, n_max=n_max)
            except Exception:
                importance = []

        user_name = job.get("username") or "admin"
        folder = get_user_dir(user_name, "models")
        model_path = os.path.join(folder, f"job_{job_id}.pkl")
        artifact_path = os.path.join(folder, f"job_{job_id}_artifact.pkl")
        artifact = {
            "engine_state": engine.state(),
            "steps": steps,
            "already_clean": already_clean,
            "feature_cols": feature_cols,
            "target_col": target_col,
            "log_target": log_target,
            "target_restored": bool(target_restored),
            "task_type": task,
            "model_type": job["model_type"],
            "target_type": job["target_type"],
            "target_id": job["target_id"],
            "binding_id": job.get("binding_id"),
            "rule_id": job.get("rule_id"),
        }
        joblib.dump(model, model_path)
        joblib.dump(artifact, artifact_path)

        sample_idx = np.linspace(0, len(y_eval) - 1, num=min(80, len(y_eval))).astype(int)
        residuals = np.array(pred, dtype=float) - np.array(y_eval, dtype=float)
        n_bins = int(min(30, max(8, np.sqrt(max(len(residuals), 1)))))
        counts, bins = np.histogram(residuals, bins=n_bins)
        n_rounds = max(len(history.get("train") or []), len(history.get("valid") or []))
        if n_rounds:
            _append_log(job_id, f"已记录训练过程 {n_rounds} 点（指标 {history.get('metric') or 'rmse'}）")
        hist_pack = _pack_history_series(history)
        curves = {
            "actual": [json_safe(v) for v in np.array(y_eval)[sample_idx]],
            "pred": [json_safe(v) for v in np.array(pred)[sample_idx]],
            "history": {
                "metric": history.get("metric") or ("logloss" if task == "classification" else "rmse"),
                "train": hist_pack["train"],
                "valid": hist_pack["valid"],
                "x": hist_pack["x"],
                "x_name": history.get("x_name") or "iteration",
                "space": "log1p" if log_target else "raw",
            },
            "residuals": _subsample_series(residuals, 800),
            "residual_hist": {
                "bins": [json_safe(v) for v in bins],
                "counts": [int(v) for v in counts],
            },
        }
        duration = round(time.time() - started, 2)
        update("train_job", {
            "status": "success",
            "progress": 100,
            "metrics_json": dumps(metrics),
            "importance_json": dumps(importance[:40]),
            "curves_json": dumps(curves),
            "model_path": to_rel(model_path),
            "artifact_path": to_rel(artifact_path),
            "duration_sec": duration,
        }, "id=%s", (job_id,))
        _append_log(job_id, f"训练完成，耗时 {duration}s，指标 {metrics}")
    except Exception as e:
        update("train_job", {
            "status": "failed",
            "error_message": str(e),
        }, "id=%s", (job_id,))
        _append_log(job_id, "训练失败: " + str(e))
        _append_log(job_id, traceback.format_exc())


def _subsample_series(arr, n=500):
    vals = [json_safe(v) for v in list(arr)]
    if len(vals) <= n:
        return vals
    idx = np.linspace(0, len(vals) - 1, n).astype(int)
    return [vals[i] for i in idx]


def _pack_history_series(history, n=500):
    train = list(history.get("train") or [])
    valid = list(history.get("valid") or [])
    xs = list(history.get("x") or [])
    length = max(len(train), len(valid), len(xs))
    if length <= n:
        return {
            "train": [json_safe(v) for v in train],
            "valid": [json_safe(v) for v in valid],
            "x": [json_safe(v) for v in xs],
        }
    idx = np.linspace(0, length - 1, n).astype(int)

    def take(arr):
        if not arr:
            return []
        return [json_safe(arr[min(int(i), len(arr) - 1)]) for i in idx]

    return {"train": take(train), "valid": take(valid), "x": take(xs)}


def _series_rmse(model, X, y):
    scores = []
    for pred in model.staged_predict(X):
        scores.append(float(np.sqrt(mean_squared_error(y, pred))))
    return scores


def _history_from_evals(raw):
    if not isinstance(raw, dict) or not raw:
        return {}
    train_keys = ("validation_0", "train", "training", "learn", "Learn")
    valid_keys = ("validation_1", "valid", "valid_0", "validation", "Validation")
    train, valid, metric = [], [], ""
    for key in train_keys:
        if key in raw:
            metric, train = _pick_eval_series(raw[key])
            break
    for key in valid_keys:
        if key in raw:
            m2, valid = _pick_eval_series(raw[key])
            metric = metric or m2
            break
    if not train and not valid:
        items = list(raw.items())
        if items:
            metric, train = _pick_eval_series(items[0][1])
        if len(items) > 1:
            m2, valid = _pick_eval_series(items[1][1])
            metric = metric or m2
    if not train and not valid:
        return {}
    return {
        "metric": (metric or "rmse").lower(),
        "train": [float(v) for v in train],
        "valid": [float(v) for v in valid],
        "x_name": "iteration",
    }


def _tree_ensemble_history(model, X, y, X_valid, y_valid, task="regression"):
    estimators = list(getattr(model, "estimators_", None) or [])
    if len(estimators) < 2:
        return {}
    n = len(estimators)
    step = max(1, n // 40)
    y = np.asarray(y)
    yv = np.asarray(y_valid) if y_valid is not None and X_valid is not None else None
    is_clf = str(task) == "classification" or hasattr(model, "classes_")
    xs, train, valid = [], [], []
    acc_tr = None
    acc_va = None
    classes = np.asarray(getattr(model, "classes_", [])) if is_clf else None
    for i, est in enumerate(estimators, 1):
        if is_clf and hasattr(est, "predict_proba"):
            p = np.asarray(est.predict_proba(X), dtype=float)
            acc_tr = p if acc_tr is None else acc_tr + p
            if X_valid is not None:
                pv = np.asarray(est.predict_proba(X_valid), dtype=float)
                acc_va = pv if acc_va is None else acc_va + pv
        else:
            p = np.asarray(est.predict(X), dtype=float)
            acc_tr = p if acc_tr is None else acc_tr + p
            if X_valid is not None:
                pv = np.asarray(est.predict(X_valid), dtype=float)
                acc_va = pv if acc_va is None else acc_va + pv
        if i % step != 0 and i != n:
            continue
        xs.append(i)
        mean_tr = acc_tr / i
        if is_clf and mean_tr.ndim == 2 and classes is not None and len(classes):
            pred = classes[np.argmax(mean_tr, axis=1)]
            train.append(float(np.mean(pred != y)))
            if acc_va is not None and yv is not None:
                pred_v = classes[np.argmax(acc_va / i, axis=1)]
                valid.append(float(np.mean(pred_v != yv)))
        else:
            train.append(float(np.sqrt(np.mean((np.asarray(mean_tr).ravel() - y.ravel()) ** 2))))
            if acc_va is not None and yv is not None:
                valid.append(float(np.sqrt(np.mean((np.asarray(acc_va / i).ravel() - yv.ravel()) ** 2))))
    if not train and not valid:
        return {}
    return {
        "metric": "error" if is_clf else "rmse",
        "train": train,
        "valid": valid,
        "x": xs,
        "x_name": "n_estimators",
    }


def _as_float_array(X):
    if X is None:
        return None
    if hasattr(X, "to_numpy"):
        return np.asarray(X.to_numpy(copy=False), dtype=float)
    return np.asarray(X, dtype=float)


def _dt_nodes_at_depth(tree, X, depth):
    n, n_feat = X.shape
    node = np.zeros(n, dtype=np.intp)
    for _ in range(max(int(depth), 0)):
        feat = tree.feature[node]
        left = tree.children_left[node]
        right = tree.children_right[node]
        leaf = left == -1
        col = np.clip(np.where(feat >= 0, feat, 0), 0, max(n_feat - 1, 0))
        go_left = X[np.arange(n), col] <= tree.threshold[node]
        nxt = np.where(leaf, node, np.where(go_left, left, right))
        if np.array_equal(nxt, node):
            break
        node = nxt
    return node


def _dt_predict_nodes(tree, nodes, classes=None):
    val = tree.value[nodes]
    if val.ndim != 3:
        return np.asarray(val).reshape(len(nodes), -1)[:, 0]
    if val.shape[-1] > 1:
        idx = np.argmax(val[:, 0, :], axis=1)
        if classes is not None and len(classes):
            return np.asarray(classes)[idx]
        return idx
    return val[:, 0, 0]


def _decision_tree_depth_history(model, X, y, X_valid, y_valid, task="regression"):
    tree = getattr(model, "tree_", None)
    if tree is None:
        return {}
    max_d = int(getattr(tree, "max_depth", 0) or 0)
    X = _as_float_array(X)
    Xv = _as_float_array(X_valid) if X_valid is not None else None
    if X is None or X.size == 0:
        return {}
    y = np.asarray(y)
    yv = np.asarray(y_valid) if y_valid is not None and Xv is not None else None
    is_clf = str(task) == "classification" or hasattr(model, "classes_")
    classes = np.asarray(getattr(model, "classes_", [])) if is_clf else None
    xs, train, valid = [], [], []
    for d in range(0, max_d + 1):
        pred = _dt_predict_nodes(tree, _dt_nodes_at_depth(tree, X, d), classes)
        xs.append(d)
        if is_clf:
            train.append(float(np.mean(pred != y)))
            if Xv is not None and yv is not None:
                pv = _dt_predict_nodes(tree, _dt_nodes_at_depth(tree, Xv, d), classes)
                valid.append(float(np.mean(pv != yv)))
        else:
            train.append(float(np.sqrt(np.mean((np.asarray(pred).ravel() - y.ravel()) ** 2))))
            if Xv is not None and yv is not None:
                pv = _dt_predict_nodes(tree, _dt_nodes_at_depth(tree, Xv, d), classes)
                valid.append(float(np.sqrt(np.mean((np.asarray(pv).ravel() - yv.ravel()) ** 2))))
    if not train and not valid:
        return {}
    return {
        "metric": "error" if is_clf else "rmse",
        "train": train,
        "valid": valid,
        "x": xs,
        "x_name": "tree_depth",
    }


def _cap_xy(X, y, n=6000, seed=42):
    X = _as_float_array(X)
    if X is None or y is None or len(X) == 0:
        return X, y
    y = np.asarray(y)
    if len(X) <= n:
        return X, y
    rng = np.random.RandomState(seed)
    idx = rng.choice(len(X), n, replace=False)
    return X[idx], y[idx]


def _pred_metric(est, X, y, is_clf):
    pred = np.asarray(est.predict(X)).ravel()
    yt = np.asarray(y).ravel()
    if is_clf:
        return float(np.mean(pred != yt))
    return float(np.sqrt(np.mean((pred.astype(float) - yt.astype(float)) ** 2)))


def _svm_c_grid(c0):
    c0 = float(c0 or 1.0)
    c0 = min(max(c0, 0.01), 100.0)
    lo = max(c0 / 100.0, 0.01)
    hi = min(c0 * 100.0, 100.0)
    raw = list(np.round(np.geomspace(lo, hi, 7), 6))
    if not any(abs(float(c) - c0) < 1e-9 for c in raw):
        raw.append(c0)
    out = []
    for c in sorted(float(v) for v in raw if float(v) > 0):
        if not out or abs(c - out[-1]) > 1e-9:
            out.append(c)
    return out


def _svm_c_history(model, X, y, X_valid, y_valid, task="regression"):
    params = model.get_params() if hasattr(model, "get_params") else {}
    X, y = _cap_xy(X, y)
    Xv, yv = (None, None)
    if X_valid is not None and y_valid is not None:
        Xv, yv = _cap_xy(X_valid, y_valid, n=4000)
    if X is None or len(X) == 0:
        return {}
    c_key = "C" if "C" in params else next((k for k in params if k.endswith("__C")), "C")
    prob_key = "probability" if "probability" in params else next((k for k in params if k.endswith("__probability")), None)
    is_clf = str(task) == "classification" or bool(params.get(prob_key or "probability")) or hasattr(model, "classes_")
    xs, train, valid = [], [], []
    for c in _svm_c_grid(params.get(c_key) or 1.0):
        try:
            est = clone(model)
            kw = {c_key: c}
            if is_clf and prob_key:
                kw[prob_key] = False
            est.set_params(**kw)
            est.fit(X, y)
            xs.append(c)
            train.append(_pred_metric(est, X, y, is_clf))
            if Xv is not None and yv is not None:
                valid.append(_pred_metric(est, Xv, yv, is_clf))
        except Exception:
            continue
    if not train and not valid:
        return {}
    return {
        "metric": "error" if is_clf else "rmse",
        "train": train,
        "valid": valid,
        "x": xs,
        "x_name": "svm_C",
    }


def _alpha_grid(a0):
    a0 = float(a0 or 1.0)
    a0 = min(max(a0, 1e-6), 1000.0)
    lo = max(a0 / 100.0, 1e-6)
    hi = min(a0 * 100.0, 1000.0)
    raw = list(np.round(np.geomspace(lo, hi, 7), 8))
    if not any(abs(float(a) - a0) < 1e-12 for a in raw):
        raw.append(a0)
    out = []
    for a in sorted(float(v) for v in raw if float(v) > 0):
        if not out or abs(a - out[-1]) > 1e-12:
            out.append(a)
    return out


def _param_path_history(model, X, y, X_valid, y_valid, param, grid, x_name, task="regression"):
    X, y = _cap_xy(X, y)
    Xv, yv = (None, None)
    if X_valid is not None and y_valid is not None:
        Xv, yv = _cap_xy(X_valid, y_valid, n=4000)
    if X is None or len(X) == 0:
        return {}
    is_clf = str(task) == "classification"
    xs, train, valid = [], [], []
    for val in grid:
        try:
            est = clone(model)
            est.set_params(**{param: val})
            est.fit(X, y)
            xs.append(val)
            train.append(_pred_metric(est, X, y, is_clf))
            if Xv is not None and yv is not None:
                valid.append(_pred_metric(est, Xv, yv, is_clf))
        except Exception:
            continue
    if not train and not valid:
        return {}
    return {
        "metric": "error" if is_clf else "rmse",
        "train": train,
        "valid": valid,
        "x": xs,
        "x_name": x_name,
    }


def _sample_size_history(model, X, y, X_valid, y_valid, task="regression"):
    X, y = _cap_xy(X, y, n=8000)
    Xv, yv = (None, None)
    if X_valid is not None and y_valid is not None:
        Xv, yv = _cap_xy(X_valid, y_valid, n=4000)
    if X is None or len(X) < 8:
        return {}
    is_clf = str(task) == "classification"
    rng = np.random.RandomState(42)
    order = rng.permutation(len(X))
    xs, train, valid = [], [], []
    for frac in (0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 1.0):
        n = max(8, int(len(X) * frac))
        idx = order[:n]
        try:
            est = clone(model)
            est.fit(X[idx], y[idx])
            xs.append(n)
            train.append(_pred_metric(est, X[idx], y[idx], is_clf))
            if Xv is not None and yv is not None:
                valid.append(_pred_metric(est, Xv, yv, is_clf))
        except Exception:
            continue
    if not train and not valid:
        return {}
    return {
        "metric": "error" if is_clf else "rmse",
        "train": train,
        "valid": valid,
        "x": xs,
        "x_name": "n_samples",
    }


def _pick_eval_series(bucket):
    if not isinstance(bucket, dict):
        return "", []

    def as_list(val):
        if val is None:
            return []
        if isinstance(val, np.ndarray):
            return [float(v) for v in val.tolist()]
        if isinstance(val, (list, tuple)):
            return [float(v) for v in val]
        try:
            return [float(v) for v in list(val)]
        except (TypeError, ValueError):
            return []

    for key in (
        "rmse", "RMSE", "mae", "MAE", "logloss", "Logloss", "mlogloss",
        "binary_logloss", "multi_logloss", "MultiClass", "loss",
    ):
        if key in bucket:
            series = as_list(bucket[key])
            if series:
                return key, series
    for key, val in bucket.items():
        series = as_list(val)
        if series:
            return str(key), series
    return "", []


def _extract_boosting_history(model, captured=None):
    raw = captured if isinstance(captured, dict) and captured else None
    if not raw and hasattr(model, "evals_result") and callable(model.evals_result):
        try:
            raw = model.evals_result()
        except Exception:
            raw = None
    if not raw:
        raw = getattr(model, "evals_result_", None)
    if not raw and hasattr(model, "get_evals_result"):
        try:
            raw = model.get_evals_result()
        except Exception:
            raw = None
    return _history_from_evals(raw)


def _fit_kwargs_fallback(model, X, y, kwargs):
    current = dict(kwargs or {})
    try:
        model.fit(X, y, **current)
        return current
    except TypeError:
        pass
    if "eval_X" in current or "eval_y" in current:
        x_ev = current.pop("eval_X", None)
        y_ev = current.pop("eval_y", None)
        if x_ev is not None and y_ev is not None:
            current["eval_set"] = [(X, y), (x_ev, y_ev)]
        try:
            model.fit(X, y, **current)
            return current
        except TypeError:
            pass
    for drop in ("callbacks", "eval_metric", "eval_names", "verbose"):
        if drop not in current:
            continue
        current.pop(drop, None)
        try:
            model.fit(X, y, **current)
            return current
        except TypeError:
            continue
    current.pop("eval_set", None)
    model.fit(X, y, **current)
    return current


def _fit_boosting(model, X, y, X_valid, y_valid, mt, n_est, bump, job_id, gpu_params, task="regression"):
    extra = {}
    callbacks = None
    captured = {"log": None}
    if mt == "lightgbm":
        def cb(env):
            total = getattr(env, "end_iteration", None) or n_est
            bump((env.iteration + 1) / max(int(total) or 1, 1))
        callbacks = [cb]
        if X_valid is not None:
            extra = {"eval_X": X_valid, "eval_y": y_valid, "eval_names": ["valid"]}
    elif mt == "xgboost":
        metric = "logloss" if str(task) == "classification" else "rmse"
        try:
            model.set_params(eval_metric=metric)
        except Exception:
            extra["eval_metric"] = metric
        try:
            import xgboost as xgb

            class _Cb(xgb.callback.TrainingCallback):
                def after_iteration(self, model, epoch, evals_log):
                    bump((epoch + 1) / max(n_est, 1))
                    captured["log"] = evals_log
                    return False

            callbacks = [_Cb()]
        except Exception:
            callbacks = None
        if X_valid is not None:
            extra["eval_set"] = [(X, y), (X_valid, y_valid)]
            extra["verbose"] = False
    elif mt == "catboost":
        extra = {"verbose": False}
        if X_valid is not None:
            extra["eval_set"] = (X_valid, y_valid)

    kwargs = dict(extra)
    if callbacks:
        kwargs["callbacks"] = callbacks
    try:
        _fit_kwargs_fallback(model, X, y, kwargs)
        return captured.get("log")
    except Exception as gpu_err:
        switched = False
        if mt == "xgboost" and str((gpu_params or {}).get("device") or "").startswith("cuda"):
            _append_log(job_id, f"GPU 训练失败，改用 CPU: {gpu_err}")
            try:
                model.set_params(device="cpu", tree_method="hist")
            except Exception:
                pass
            switched = True
        elif mt == "lightgbm" and str((gpu_params or {}).get("device") or "").lower() in ("gpu", "cuda"):
            _append_log(job_id, f"GPU 训练失败，改用 CPU: {gpu_err}")
            model.set_params(device="cpu")
            switched = True
        elif mt == "catboost" and str((gpu_params or {}).get("task_type") or "").upper() == "GPU":
            _append_log(job_id, f"GPU 训练失败，改用 CPU: {gpu_err}")
            model.set_params(task_type="CPU")
            switched = True
        if not switched:
            raise
        _fit_kwargs_fallback(model, X, y, kwargs)
        return captured.get("log")


def _fit_model(model, X, y, job_id, model_type, params, X_valid=None, y_valid=None, task="regression"):
    n_est = int(params.get("n_estimators") or params.get("iterations") or 200)
    last = {"p": 40}

    def bump(frac):
        pct = 40 + int(38 * max(0.0, min(1.0, frac)))
        if pct >= last["p"] + 2:
            last["p"] = pct
            update("train_job", {"progress": pct}, "id=%s", (job_id,))

    mt = str(model_type or "").lower()
    fitted = model.get_params() if hasattr(model, "get_params") else {}
    used_dev = getattr(model, "used_device_", None)
    if mt == "xgboost":
        _append_log(job_id, f"训练设备: {fitted.get('device') or 'cpu'}（XGBoost）")
    elif mt == "lightgbm":
        _append_log(job_id, f"训练设备: {fitted.get('device') or 'cpu'}（LightGBM）")
    elif mt == "catboost":
        _append_log(job_id, f"训练设备: {fitted.get('task_type') or 'CPU'}（CatBoost）")
    elif mt == "bert":
        _append_log(job_id, "开始 BERT 拟合（表格行会拼成文本）")
    elif mt == "softmax":
        _append_log(job_id, "开始 Softmax 拟合")
    elif mt in ("linear", "ridge", "lasso", "logistic"):
        _append_log(job_id, f"训练设备: CPU（{mt} 为 sklearn 实现，无 CUDA 接口）")
    else:
        _append_log(job_id, f"训练设备: CPU（{mt or 'sklearn'} 无 CUDA 实现）")

    captured = None
    try:
        if mt in ("xgboost", "lightgbm", "catboost"):
            captured = _fit_boosting(
                model, X, y, X_valid, y_valid, mt, n_est, bump, job_id, fitted, task=task,
            )
        elif mt in ("bert", "softmax") and hasattr(model, "fit"):
            try:
                model.fit(X, y, X_valid=X_valid, y_valid=y_valid, bump=bump)
            except TypeError:
                model.fit(X, y)
                bump(1.0)
            except Exception as gpu_err:
                pref = str(getattr(model, "device", "") or getattr(model, "used_device_", "") or "")
                if "cuda" in pref.lower() or pref.lower() in ("auto", "gpu"):
                    _append_log(job_id, f"GPU 训练失败，改用 CPU: {gpu_err}")
                    try:
                        model.set_params(device="cpu")
                    except Exception:
                        model.device = "cpu"
                    model.fit(X, y, X_valid=X_valid, y_valid=y_valid, bump=bump)
                else:
                    raise
            used_dev = getattr(model, "used_device_", used_dev)
            if used_dev:
                _append_log(job_id, f"训练设备: {used_dev}（{'BERT' if mt == 'bert' else 'Softmax'}）")
            note = getattr(model, "_hf_fallback_", None)
            if note:
                _append_log(job_id, f"预训练 BERT 不可用，已改用 BERT-Tiny：{note}")
        else:
            model.fit(X, y)
            bump(1.0)
    except TypeError:
        model.fit(X, y)
    except Exception:
        try:
            model.fit(X, y)
        except Exception:
            raise

    history = _extract_boosting_history(model, captured)
    if getattr(model, "history_", None):
        packed = model.history_ if isinstance(model.history_, dict) else {}
        if packed.get("train") or packed.get("valid"):
            history = packed
    if not history.get("train") and not history.get("valid"):
        if mt in ("random_forest", "extra_trees"):
            try:
                history = _tree_ensemble_history(model, X, y, X_valid, y_valid, task)
            except Exception:
                history = {}
        elif mt == "decision_tree":
            try:
                history = _decision_tree_depth_history(model, X, y, X_valid, y_valid, task)
            except Exception:
                history = {}
        elif mt == "svm":
            try:
                history = _svm_c_history(model, X, y, X_valid, y_valid, task)
            except Exception:
                history = {}
        elif mt in ("logistic", "softmax"):
            try:
                history = _param_path_history(model, X, y, X_valid, y_valid, "C", _svm_c_grid((params or {}).get("C") or 1.0), "C", task)
            except Exception:
                history = {}
        elif mt in ("ridge", "lasso"):
            try:
                history = _param_path_history(
                    model, X, y, X_valid, y_valid, "alpha",
                    _alpha_grid((params or {}).get("alpha") or (1.0 if mt == "ridge" else 0.001)),
                    "alpha", task,
                )
            except Exception:
                history = {}
        elif mt == "linear":
            try:
                history = _sample_size_history(model, X, y, X_valid, y_valid, task)
            except Exception:
                history = {}
        elif hasattr(model, "staged_predict") and X_valid is not None:
            try:
                history = {
                    "metric": "rmse" if task != "classification" else "error",
                    "train": _series_rmse(model, X, y),
                    "valid": _series_rmse(model, X_valid, y_valid),
                    "x_name": "iteration",
                }
            except Exception:
                history = {}
        elif hasattr(model, "loss_curve_"):
            history = {
                "metric": "loss",
                "train": [float(v) for v in (model.loss_curve_ or [])],
                "valid": [float(v) for v in (getattr(model, "validation_scores_", None) or [])],
                "x_name": "iteration",
            }
    return history or {}


def training_limitations(job):
    curves = job.get("curves") or {}
    history = curves.get("history") or {}
    lines = [
        "本说明由训练任务自动生成，供论文方法节草稿与企业附件使用。系统不执行交易或调度指令。",
        f"- 验证方式：随机 hold-out（test_size={job.get('test_size')}，random_state={job.get('random_state') or 42}），"
        "不是滚动时序交叉验证；电价/负荷等序列可能存在乐观偏差。",
    ]
    if job.get("log_target"):
        lines.append(
            "- 拟合目标使用 log1p，大值被压缩；RMSE/MAE/R2 在还原后的业务量纲上计算。"
            "训练曲线反映优化器看到的目标空间（log1p）。"
        )
    lines.append("- 未做系统化超参搜索或 nested CV；参数来自页面预设或手工填写。")
    n_feat = len(job.get("feature_cols") or [])
    lines.append(
        f"- 输入特征 {n_feat} 列；未选列不进入模型。"
        "标准化为「清洗数值列 ∩ 已选特征」，目标列不缩放。"
    )
    if (job.get("sample_rows") or 0) > 0:
        lines.append(f"- 训练抽样 {job.get('sample_rows')} 行，非全量。")
    if not (history.get("valid") or history.get("train")):
        lines.append("- 本任务未记录训练过程曲线。XGBoost / LightGBM / CatBoost 记 boosting 轮次，随机森林记树数，决策树记深度，支持向量机/逻辑回归记正则 C，岭回归/Lasso 记 alpha，线性回归记样本量，Softmax/BERT 记 epoch；重新训练后可导出。")
    lines.append("- 交易/调度建议须人工确认；本系统未下单。")
    return "\n".join(lines)


def compare_jobs(job_ids):
    jobs = [get_job(i) for i in job_ids]
    jobs = [j for j in jobs if j]
    return {
        "jobs": jobs,
        "metrics": [{
            "id": j["id"],
            "name": j["name"],
            "model_type": j["model_type"],
            **(j.get("metrics") or {}),
        } for j in jobs],
    }
