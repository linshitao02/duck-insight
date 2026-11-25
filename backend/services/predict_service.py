# -*- coding: utf-8 -*-
from datetime import datetime
from io import BytesIO

import joblib
import numpy as np
import pandas as pd
from openpyxl import Workbook

from config import get_user_dir, to_abs, to_rel
from services import dataset_service, model_service
from utils.cleaner import CleanEngine
from utils.db import delete, insert, query, update
from utils.io import read_table, save_dataframe
from utils.jsonx import dumps, json_safe, loads, row_to_dict
from utils.joiner import apply_joins


def _actor():
    """当前登录用户；定时/后台任务没有请求上下文时返回空。"""
    try:
        from flask import g, has_request_context
        if has_request_context():
            return getattr(g, "user", None) or {}
    except Exception:
        pass
    return {}


def _actor_or_admin():
    """DAG / 定时任务没有登录态时归属到 admin，保证记录在列表里可见。"""
    user = _actor()
    if user.get("id"):
        return user
    row = query("SELECT id, username FROM sys_user WHERE role='admin' ORDER BY id LIMIT 1", one=True)
    return row or {}


def serialize_pred(row):
    if not row:
        return None
    data = row_to_dict(row)
    data["input"] = loads(row.get("input_json"), default=[])
    data["result"] = loads(row.get("result_json"), default=[])
    data["rag"] = loads(row.get("rag_context"), default=[])
    data["n_rows"] = len(data["result"] or [])
    data["has_llm"] = bool((row.get("llm_analysis") or "").strip())
    return data


def serialize_pred_brief(row):
    """列表用的轻量结构：不带 input/result 大字段。"""
    data = row_to_dict(row)
    result = loads(row.get("result_json"), default=[]) or []
    return {
        "id": data.get("id"),
        "name": data.get("name"),
        "train_job_id": data.get("train_job_id"),
        "train_name": data.get("train_name"),
        "target_col": data.get("target_col"),
        "model_type": data.get("model_type"),
        "input_type": data.get("input_type"),
        "use_llm": data.get("use_llm"),
        "use_rag": data.get("use_rag"),
        "llm_config_id": data.get("llm_config_id"),
        "llm_config_name": data.get("llm_config_name"),
        "prompt_id": data.get("prompt_id"),
        "llm_question": data.get("llm_question"),
        "has_llm": bool((row.get("llm_analysis") or "").strip()),
        "n_rows": len(result),
        "result_path": data.get("result_path"),
        "username": data.get("username"),
        "create_time": data.get("create_time"),
    }


def list_preds(keyword=None, train_job_id=None, llm_only=False):
    user = _actor()
    sql = (
        "SELECT p.*, j.name AS train_name, j.target_col, j.model_type, "
        "c.name AS llm_config_name "
        "FROM predict_job p "
        "LEFT JOIN train_job j ON j.id = p.train_job_id "
        "LEFT JOIN llm_config c ON c.id = p.llm_config_id "
        "WHERE 1=1"
    )
    args = []
    if user.get("role") != "admin":
        sql += " AND p.user_id=%s"
        args.append(user.get("id"))
    if keyword:
        sql += " AND (p.name LIKE %s OR j.name LIKE %s)"
        like = f"%{keyword}%"
        args += [like, like]
    if train_job_id:
        sql += " AND p.train_job_id=%s"
        args.append(int(train_job_id))
    if llm_only:
        sql += " AND p.use_llm=1"
    sql += " ORDER BY p.id DESC"
    return [serialize_pred_brief(r) for r in query(sql, args)]


def get_pred(pid):
    user = _actor()
    sql = (
        "SELECT p.*, j.name AS train_name, j.target_col, j.model_type, "
        "c.name AS llm_config_name "
        "FROM predict_job p "
        "LEFT JOIN train_job j ON j.id = p.train_job_id "
        "LEFT JOIN llm_config c ON c.id = p.llm_config_id "
        "WHERE p.id=%s"
    )
    row = query(sql, (pid,), one=True)
    if row and user.get("role") != "admin" and row.get("user_id") != user.get("id"):
        return None
    return serialize_pred(row)


def delete_pred(pid):
    row = get_pred(pid)
    if not row:
        raise ValueError("预测记录不存在")
    delete("predict_job", "id=%s", (pid,))
    return True


def delete_preds(ids):
    user = _actor()
    n = 0
    for pid in ids or []:
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            continue
        row = query("SELECT id, user_id FROM predict_job WHERE id=%s", (pid,), one=True)
        if not row:
            continue
        if user.get("role") != "admin" and row.get("user_id") != user.get("id"):
            continue
        n += int(delete("predict_job", "id=%s", (pid,)) or 0)
    return {"deleted": n}


def analyze_pred(pid, payload=None):
    """对已存在的预测记录补跑 / 重跑 LLM 分析。"""
    payload = payload or {}
    row = get_pred(pid)
    if not row:
        raise ValueError("预测记录不存在")
    records = row.get("result") or []
    if not records:
        raise ValueError("该记录没有预测结果，无法做 LLM 分析")
    from services.llm_service import LLMService

    use_rag = bool(payload.get("use_rag", row.get("use_rag", 1)))
    question = payload.get("question")
    if question is None:
        question = row.get("llm_question")
    question = (question or "").strip()
    llm_config_id = payload.get("llm_config_id") or row.get("llm_config_id")
    prompt_id = payload.get("prompt_id") or row.get("prompt_id")
    analysis, snippets = LLMService.analyze_predictions(
        records,
        llm_config_id=int(llm_config_id) if llm_config_id else None,
        prompt_id=int(prompt_id) if prompt_id else None,
        use_rag=use_rag,
        question=question,
        system_prompt=payload.get("system_prompt"),
    )
    patch = {
        "use_llm": 1,
        "use_rag": 1 if use_rag else 0,
        "llm_analysis": analysis,
        "rag_context": dumps(snippets),
    }
    if llm_config_id:
        patch["llm_config_id"] = int(llm_config_id)
    if prompt_id:
        patch["prompt_id"] = int(prompt_id)
    if question:
        patch["llm_question"] = question
    update("predict_job", patch, "id=%s", (pid,))
    return get_pred(pid)


def _load_artifact(job):
    model = joblib.load(to_abs(job["model_path"]))
    artifact = joblib.load(to_abs(job["artifact_path"]))
    _prefer_cpu_predict(model)
    return model, artifact


def _prefer_cpu_predict(model):
    """XGBoost 用 GPU 训练后，对内存里的表格预测会报设备不一致。预测改走 CPU。"""
    getter = getattr(model, "get_booster", None)
    if not callable(getter):
        return
    try:
        getter().set_param({"device": "cpu"})
    except Exception:
        pass


def template_columns(job):
    """预测模板用原始列。清洗里拆出来的年、月、编码列由引擎在预测时生成。"""
    target = (job or {}).get("target_col")
    try:
        df, _ = dataset_service.load_source_frame(job["target_type"], job["target_id"], nrows=2)
        cols = [c for c in df.columns if c != target]
        if cols:
            return cols
    except Exception:
        pass
    artifact = joblib.load(to_abs(job["artifact_path"]))
    return list(artifact.get("feature_cols") or [])


def build_template_excel(job):
    cols = template_columns(job)
    wb = Workbook()
    ws = wb.active
    ws.title = "predict"
    ws.append(cols)
    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio, f"predict_template_{job['id']}.xlsx"


def _artifact_can_transform(artifact):
    artifact = artifact or {}
    state = artifact.get("engine_state") or {}
    if state.get("encoders") or state.get("scaler") or state.get("fill_values"):
        return True
    return bool(artifact.get("steps"))


def decode_prediction(pred, artifact):
    """把模型输出还原成业务原值：log1p → expm1；旧模型若只标准化了 y 则再 inverse。"""
    pred = np.asarray(pred, dtype=float).reshape(-1)
    artifact = artifact or {}
    if artifact.get("log_target"):
        pred = np.clip(np.expm1(pred), 0, None)
    if artifact.get("target_restored"):
        return pred
    # 旧模型：目标被 StandardScaler 进了清洗，但没做 log 时可以 inverse
    if artifact.get("log_target"):
        return pred
    state = artifact.get("engine_state") or {}
    scaler = state.get("scaler")
    cols = state.get("scale_cols") or []
    target = artifact.get("target_col")
    if scaler is None or not target or target not in cols:
        return pred
    idx = cols.index(target)
    dummy = np.zeros((len(pred), len(cols)))
    dummy[:, idx] = pred
    return scaler.inverse_transform(dummy)[:, idx]


def _align_features(raw_df, artifact):
    engine = CleanEngine()
    engine.load_state(artifact.get("engine_state") or {})
    steps = artifact.get("steps") or []
    df = raw_df.copy()
    if steps or engine.has_preprocess():
        df = engine.transform(df, steps)
    feature_cols = artifact.get("feature_cols") or []
    for c in feature_cols:
        if c not in df.columns:
            df[c] = 0
    X = df[feature_cols].apply(pd.to_numeric, errors="coerce").fillna(0).values
    return df, X


def predict_on_frame(job, raw_df, feature_overrides=None, already_clean=False):
    """对已有 DataFrame 跑训练好的模型，返回一维预测。

    already_clean 仅表示训练矩阵当时已洗过；只要产物里存了 LabelEncoder/Scaler，
    预测仍会对原始输入做 transform（手填中文站点名等）。
    """
    if not job or job.get("status") != "success":
        raise ValueError("请选择已训练成功的模型")
    model, artifact = _load_artifact(job)
    work = raw_df.copy()
    for k, v in (feature_overrides or {}).items():
        if k and v is not None and v != "":
            work[k] = v
    feature_cols = artifact.get("feature_cols") or []
    if already_clean and not _artifact_can_transform(artifact):
        for c in feature_cols:
            if c not in work.columns:
                work[c] = 0
        X = work[feature_cols].apply(pd.to_numeric, errors="coerce").fillna(0).values
    else:
        _prepared, X = _align_features(work, artifact)
    pred = model.predict(X)
    pred = decode_prediction(pred, artifact)
    return pred


def _maybe_join_raw(raw_df, job):
    if job.get("target_type") != "bundle":
        return raw_df
    bundle = dataset_service.get_bundle(job["target_id"])
    if not bundle:
        return raw_df
    ids = bundle.get("dataset_ids") or []
    fact_id = bundle.get("fact_dataset_id")
    frames = {int(fact_id): raw_df} if fact_id else {}
    for ds_id in ids:
        if int(ds_id) == int(fact_id or 0):
            continue
        ds = dataset_service.get_dataset(ds_id)
        if not ds:
            continue
        from utils.io import load_dataframe
        frames[int(ds_id)] = load_dataframe(to_abs(ds["file_path"]))
    if len(frames) <= 1:
        return raw_df
    try:
        return apply_joins(frames, int(fact_id), bundle.get("joins") or [])
    except Exception:
        return raw_df


def run_predict(payload, excel_file=None):
    user = _actor()
    job = model_service.get_job(payload.get("train_job_id"))
    if not job or job.get("status") != "success":
        raise ValueError("请选择已训练成功的模型")
    model, artifact = _load_artifact(job)

    if excel_file:
        raw = read_table(excel_file, filename=excel_file.filename)
        input_type = "excel"
    else:
        rows = payload.get("rows") or payload.get("input") or []
        if isinstance(rows, dict):
            rows = [rows]
        if not rows:
            raise ValueError("请填写至少一条预测数据")
        raw = pd.DataFrame(rows)
        input_type = "form"

    joined = _maybe_join_raw(raw, job)
    prepared, X = _align_features(joined, artifact)
    pred = model.predict(X)
    pred = decode_prediction(pred, artifact)
    target_col = artifact.get("target_col") or "prediction"
    result_df = raw.copy()
    result_df["prediction"] = pred
    records = [{k: json_safe(v) for k, v in rec.items()} for rec in result_df.to_dict(orient="records")]

    folder = get_user_dir(user.get("username") or "admin", "predicts")
    result_path = os_join(folder, f"pred_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv")
    save_dataframe(result_df, result_path)

    analysis = None
    rag_snips = []
    llm_error = None
    question = (payload.get("question") or "").strip()
    if payload.get("use_llm"):
        from services.llm_service import LLMService
        try:
            analysis, rag_snips = LLMService.analyze_predictions(
                records[:80],
                llm_config_id=payload.get("llm_config_id"),
                prompt_id=payload.get("prompt_id"),
                use_rag=bool(payload.get("use_rag", True)),
                question=question,
                system_prompt=payload.get("system_prompt"),
            )
        except Exception as e:
            # 模型/额度/网络问题不应该连预测结果一起丢掉：结果照常入库，失败原因带回前端
            llm_error = str(e)

    pid = insert("predict_job", {
        "name": payload.get("name") or f"预测-{job['name']}",
        "train_job_id": job["id"],
        "input_type": input_type,
        "input_json": dumps([{k: json_safe(v) for k, v in rec.items()} for rec in raw.head(200).to_dict(orient="records")]),
        "result_json": dumps(records[:500]),
        "result_path": to_rel(result_path),
        "use_llm": 1 if payload.get("use_llm") else 0,
        "use_rag": 1 if payload.get("use_rag", True) else 0,
        "llm_config_id": payload.get("llm_config_id"),
        "prompt_id": payload.get("prompt_id"),
        "llm_question": question or None,
        "llm_analysis": analysis,
        "rag_context": dumps(rag_snips),
        "user_id": user.get("id"),
        "username": user.get("username"),
    })
    row = get_pred(pid)
    if llm_error and isinstance(row, dict):
        row["llm_error"] = llm_error
    return row


def record_from_frame(job, result_df, name=None, input_type="dag"):
    """把 DAG 推理结果写入 predict_job，供列表和风险报告引用。"""
    user = _actor_or_admin()
    sample = result_df.head(500)
    records = [{k: json_safe(v) for k, v in rec.items()} for rec in sample.to_dict(orient="records")]
    folder = get_user_dir(user.get("username") or "admin", "predicts")
    result_path = os_join(folder, f"pred_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv")
    save_dataframe(result_df, result_path)
    pid = insert("predict_job", {
        "name": name or f"DAG预测-{job.get('name')}",
        "train_job_id": job["id"],
        "input_type": input_type or "dag",
        "input_json": dumps(records[:200]),
        "result_json": dumps(records[:500]),
        "result_path": to_rel(result_path),
        "use_llm": 0,
        "use_rag": 0,
        "user_id": user.get("id"),
        "username": user.get("username"),
    })
    return get_pred(pid)


def os_join(folder, name):
    import os
    return os.path.join(folder, name)
