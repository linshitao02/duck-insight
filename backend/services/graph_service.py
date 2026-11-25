# -*- coding: utf-8 -*-
import re
import time

from services import power_engine
from services.scenario_service import ensure_scenario
from utils.db import insert, query, update
from utils.jsonx import dumps, loads, row_to_dict


def _current_user():
    try:
        from flask import g, has_request_context
        if has_request_context():
            return getattr(g, "user", None) or {}
    except Exception:
        pass
    return {}


def _as_int(value):
    """把画布上存下来的 llm_config_id 之类转成 int，无效（含「自定义/默认」）返回 None。"""
    if value is None or value == "":
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


COMPONENTS = [
    {"type": "asset.dataset", "label": "数据表", "category": "source", "color": "#0ea5e9",
     "desc": "选择数据集配置中的一张原始表", "ports_in": [], "ports_out": ["table"]},
    {"type": "asset.bundle", "label": "逻辑数据集", "category": "source", "color": "#0284c7",
     "desc": "选择已配置关联的逻辑数据集", "ports_in": [], "ports_out": ["table"]},
    {"type": "asset.export_weather", "label": "导入数据空间", "category": "source", "color": "#0ea5e9",
     "desc": "写入「华东气象数据空间」小时表，供清洗与 BI 使用", "ports_in": ["table"], "ports_out": ["table"]},
    {"type": "source.file", "label": "文件数据源", "category": "source", "color": "#64748b",
     "desc": "CSV / Excel（零售等通用场景）", "ports_in": [], "ports_out": ["table"]},
    {"type": "source.mysql", "label": "数据源接入", "category": "source", "color": "#0284c7",
     "desc": "接入已配置的 MySQL 库表，每次运行读当前数据", "ports_in": [], "ports_out": ["table"]},
    {"type": "clean.qc_ts", "label": "时序质控", "category": "clean", "color": "#14b8a6",
     "desc": "物理阈值、缺口、单位标准化", "ports_in": ["table"], "ports_out": ["table"]},
    {"type": "clean.apply_rule", "label": "清洗规则", "category": "clean", "color": "#14b8a6",
     "desc": "套用已保存的清洗规则并物化快照", "ports_in": ["table"], "ports_out": ["table"]},
    {"type": "table.join", "label": "多表关联", "category": "clean", "color": "#14b8a6",
     "desc": "星型 / 链式 Join", "ports_in": ["table"], "ports_out": ["table"]},
    {"type": "feat.shared", "label": "共用特征值", "category": "feature", "color": "#16a34a",
     "desc": "配置一组共同手填特征，拉线到模型预测后自动填入同名字段（仅手填生效）",
     "ports_in": [], "ports_out": ["features"]},
    {"type": "model.train", "label": "模型训练", "category": "model", "color": "#8b5cf6",
     "desc": "对接模型训练任务（目标列 / 算法）", "ports_in": ["table", "featureset"], "ports_out": ["model"]},
    {"type": "model.predict", "label": "模型预测", "category": "model", "color": "#7c3aed",
     "desc": "用已训练模型做推理。可接数据表/数据集/清洗，或单独手填；可接手填共用特征值",
     "ports_in": ["table", "features"], "ports_out": ["table"]},
    {"type": "llm.report", "label": "LLM 模型洞察", "category": "llm", "color": "#6366f1",
     "desc": "训练指标与特征重要性生成洞察报告并写入洞察报告列表；用户短问题召回知识库，系统提示词控制文风", "ports_in": ["forecast", "text", "model"], "ports_out": ["text"]},
    {"type": "llm.risk", "label": "LLM 风险预警报告", "category": "llm", "color": "#4f46e5",
     "desc": "对模型预测结果结合知识库 RAG 做风险分析与预警", "ports_in": ["table", "forecast"], "ports_out": ["text"]},
]

CATEGORY_LABELS = {
    "source": "接入",
    "clean": "治理",
    "feature": "特征",
    "model": "模型",
    "llm": "智能体",
}


def serialize_graph(row):
    if not row:
        return None
    data = row_to_dict(row)
    graph = loads(row.get("graph_json"), default={"nodes": [], "edges": []}) or {"nodes": [], "edges": []}
    data["graph"] = graph
    data["node_count"] = len(graph.get("nodes") or [])
    data["edge_count"] = len(graph.get("edges") or [])
    last = query(
        "SELECT id, status, duration_sec, trigger_source, create_time, error_message FROM if_graph_run "
        "WHERE graph_id=%s ORDER BY id DESC",
        (row["id"],),
        one=True,
    )
    data["last_run"] = row_to_dict(last) if last else None
    return data


def list_graphs(scenario=None, keyword=None):
    sql = "SELECT * FROM if_graph WHERE status=1"
    args = []
    if scenario:
        sql += " AND (scenario_code=%s OR scenario_code='generic')"
        args.append(scenario)
    if keyword:
        like = f"%{str(keyword).strip()}%"
        sql += " AND (name LIKE %s OR IFNULL(description,'') LIKE %s OR IFNULL(scenario_code,'') LIKE %s)"
        args.extend([like, like, like])
    sql += " ORDER BY create_time DESC, id DESC"
    return [serialize_graph(r) for r in query(sql, args)]


def get_graph(gid):
    return serialize_graph(query("SELECT * FROM if_graph WHERE id=%s", (gid,), one=True))


def save_graph(payload, gid=None):
    user = _current_user()
    scene = ensure_scenario(payload.get("scenario_code") or payload.get("scenario_name") or "generic")
    data = {
        "name": payload.get("name") or "未命名流程",
        "scenario_code": scene.get("code") or "generic",
        "description": payload.get("description") or "",
        "graph_json": dumps(payload.get("graph") or {"nodes": [], "edges": []}),
        "is_template": payload.get("is_template") or 0,
        "schedule_kind": payload.get("schedule_kind") or "none",
        "schedule_enabled": 1 if payload.get("schedule_enabled") else 0,
        "user_id": payload.get("user_id") or user.get("id"),
        "username": payload.get("username") or user.get("username") or "system",
        "status": 1,
    }
    if gid:
        # 前端保存画布时不认识 seed_key，这里保留原值，避免「改名/改画布」
        # 把种子身份抹掉、导致下次启动又被当成缺失的种子重建一份。
        data["seed_key"] = payload.get("seed_key")
        if not data["seed_key"]:
            cur = query("SELECT seed_key FROM if_graph WHERE id=%s", (gid,), one=True)
            data["seed_key"] = (cur or {}).get("seed_key")
        update("if_graph", data, "id=%s", (gid,))
        return get_graph(gid)
    if payload.get("seed_key"):
        data["seed_key"] = payload["seed_key"]
    return get_graph(insert("if_graph", data))


def clone_graph(gid, payload=None):
    payload = payload or {}
    src = get_graph(gid)
    if not src:
        raise ValueError("流程不存在")
    name = (payload.get("name") or "").strip() or f"{src.get('name') or '未命名流程'} 副本"
    description = payload.get("description")
    if description is None:
        description = src.get("description") or ""
    scenario_code = (payload.get("scenario_code") or payload.get("scenario_name") or src.get("scenario_code") or "generic")
    return save_graph({
        "name": name,
        "description": description,
        "scenario_code": scenario_code,
        "graph": src.get("graph") or {"nodes": [], "edges": []},
        "is_template": 0,
        "schedule_kind": "none",
        "schedule_enabled": 0,
    })


def _topo(nodes, edges):
    ids = [n["id"] for n in nodes]
    indeg = {i: 0 for i in ids}
    nxt = {i: [] for i in ids}
    for e in edges or []:
        if e.get("from") in indeg and e.get("to") in indeg:
            nxt[e["from"]].append(e["to"])
            indeg[e["to"]] += 1
    q = [i for i, d in indeg.items() if d == 0]
    order = []
    while q:
        cur = q.pop(0)
        order.append(cur)
        for t in nxt[cur]:
            indeg[t] -= 1
            if indeg[t] == 0:
                q.append(t)
    if len(order) != len(ids):
        raise ValueError("DAG 存在环，无法执行")
    return order


def _bind_admin_user():
    user = _current_user()
    if user.get("id"):
        return user
    row = query("SELECT * FROM sys_user WHERE username=%s", ("admin",), one=True) or {}
    try:
        from flask import g, has_app_context
        if has_app_context() and row:
            g.user = row
    except Exception:
        pass
    return row


def _resolve_rule_id(cfg):
    rid = cfg.get("rule_id")
    if rid:
        return int(rid)
    name = cfg.get("rule_name")
    if not name:
        return None
    row = query("SELECT id FROM clean_rule WHERE name=%s AND status=1", (name,), one=True)
    return row["id"] if row else None


def _resolve_dataset_id(cfg):
    did = cfg.get("dataset_id")
    if did:
        return int(did)
    name = cfg.get("dataset_name")
    if not name:
        return None
    project = cfg.get("project_name")
    if project:
        row = query(
            "SELECT d.id FROM dataset d JOIN data_project p ON p.id=d.project_id "
            "WHERE d.name=%s AND p.name=%s AND d.status=1 ORDER BY d.id DESC",
            (name, project),
            one=True,
        )
        if row:
            return row["id"]
    row = query("SELECT id FROM dataset WHERE name=%s AND status=1 ORDER BY id DESC", (name,), one=True)
    return row["id"] if row else None


def _resolve_bundle_id(cfg):
    bid = cfg.get("bundle_id")
    if bid:
        return int(bid)
    name = cfg.get("bundle_name")
    if not name:
        return None
    project = cfg.get("project_name")
    if project:
        row = query(
            "SELECT b.id FROM dataset_bundle b JOIN data_project p ON p.id=b.project_id "
            "WHERE b.name=%s AND p.name=%s AND b.status=1 ORDER BY b.id DESC",
            (name, project),
            one=True,
        )
        if row:
            return row["id"]
    row = query("SELECT id FROM dataset_bundle WHERE name=%s AND status=1 ORDER BY id DESC", (name,), one=True)
    return row["id"] if row else None


def _feature_cols_from_schema(schema, target_col):
    from utils.power_features import feature_cols_for_target
    return feature_cols_for_target(schema, target_col)


def _resolve_train_job(cfg):
    from services import model_service
    jid = cfg.get("job_id")
    if jid:
        job = model_service.get_job(int(jid))
        if job:
            return job
    name = cfg.get("job_name")
    target = cfg.get("target_col") or cfg.get("output_col")
    sql = "SELECT * FROM train_job WHERE status='success'"
    args = []
    if name:
        sql += " AND name=%s"
        args.append(name)
    elif target:
        sql += " AND target_col=%s"
        args.append(target)
    else:
        raise ValueError("模型预测未选择已训练成功的模型")
    sql += " ORDER BY id DESC"
    row = query(sql, args, one=True)
    if not row:
        raise ValueError(f"找不到已训练成功的模型「{name or target}」")
    from services import model_service as ms
    return ms.serialize_job(row)


def _feature_row_map(rows):
    data = {}
    for row in rows or []:
        col = (row or {}).get("col")
        if not col:
            continue
        val = (row or {}).get("value")
        if val is None or val == "":
            continue
        data[col] = val
    return data


def _merge_manual_features(cfg, shared):
    own = _feature_row_map(cfg.get("feature_rows"))
    merged = dict(shared or {})
    merged.update(own)
    merged.update(_override_map(cfg))
    out = dict(cfg or {})
    out["feature_rows"] = [{"col": k, "value": v} for k, v in merged.items()]
    return out


def _publish_predict_output(ctx, node_id, work, output_col):
    """把模型预测节点的输出发布给下游节点，供其手填特征引用。

    与 feat.shared 节点共用同一套「上游字段袋」：下游手填节点通过
    _shared_features_for() 汇集所有入边节点的字段，因此电价预测可以直接
    引用上游光伏/风电/负荷预测出来的 solar_mw / wind_mw / load_mw。

    袋子是「单行标量」语义，多行预测无法用扁平字典表达，故只在单行时发布。
    """
    if not node_id or not output_col or len(work) != 1:
        return
    from utils.jsonx import json_safe
    value = json_safe(work.iloc[0][output_col])
    if value is None:
        return
    ctx.setdefault("shared_feature_packs", {}).setdefault(node_id, {})[output_col] = value


def _shared_features_for(node_id, ctx):
    if not node_id:
        return {}
    packs = ctx.get("shared_feature_packs") or {}
    merged = {}
    for e in ctx.get("edges") or []:
        if e.get("to") != node_id:
            continue
        pack = packs.get(e.get("from"))
        if pack:
            merged.update(pack)
    return merged


def _override_map(cfg):
    overrides = dict(cfg.get("feature_overrides") or {})
    for row in cfg.get("override_rows") or []:
        col = (row or {}).get("col")
        if col:
            overrides[col] = (row or {}).get("value")
    return {k: v for k, v in overrides.items() if k and v is not None and v != ""}


def _as_frame_target(target_type):
    if str(target_type or "") in ("live", "source", "mysql", "mysql_live"):
        return "dataset"
    return target_type


def _ensure_ctx_frame(ctx, cfg=None):
    cfg = cfg or {}
    if ctx.get("frame") is not None:
        return ctx["frame"]
    from services import model_service
    target_type = _as_frame_target(cfg.get("target_type") or ctx.get("target_type"))
    target_id = cfg.get("target_id") or ctx.get("target_id")
    binding_id = cfg.get("binding_id") or ctx.get("binding_id")
    rule_id = cfg.get("rule_id") or ctx.get("rule_id")
    if not target_type or not target_id:
        raise ValueError("模型预测缺少上游数据表或数据集，无法取数。可改为手填特征值")
    df, engine, steps, _ = model_service.prepare_frame(
        target_type, int(target_id), rule_id=rule_id, binding_id=binding_id,
    )
    ctx["frame"] = df
    ctx["frame_engine"] = engine
    ctx["frame_steps"] = steps
    return df


def _raw_frame_for_predict(ctx, cfg, job):
    """有训练编码器时用原始表/手填原值，避免上游清洗重新 fit 打乱编号。"""
    if ctx.get("raw_frame") is not None:
        return ctx["raw_frame"].copy()
    from services import dataset_service, predict_service
    artifact = None
    try:
        _model, artifact = predict_service._load_artifact(job)
    except Exception:
        artifact = None
    if artifact and predict_service._artifact_can_transform(artifact):
        target_type = job.get("target_type") or cfg.get("target_type") or ctx.get("target_type")
        target_id = job.get("target_id") or cfg.get("target_id") or ctx.get("target_id")
        if target_type and target_id:
            df, _ = dataset_service.load_source_frame(target_type, int(target_id))
            return df
    return _ensure_ctx_frame(ctx, cfg)


def _preview_rows(df, cols, n=8):
    from utils.jsonx import json_safe
    work = df.loc[:, ~df.columns.duplicated()]
    use = []
    seen = set()
    for c in cols:
        if c in work.columns and c not in seen:
            use.append(c)
            seen.add(c)
    if not use:
        return []
    tail = work[use].tail(n)
    return [{k: json_safe(v) for k, v in rec.items()} for rec in tail.to_dict(orient="records")]


def _has_ctx_data(ctx, cfg=None):
    cfg = cfg or {}
    return ctx.get("frame") is not None or bool(cfg.get("target_id") or ctx.get("target_id"))


def _manual_feature_frame(cfg):
    import pandas as pd
    samples = cfg.get("manual_samples")
    if isinstance(samples, list) and samples:
        first = samples[0]
        if isinstance(first, dict) and "col" not in first:
            return pd.DataFrame(samples)
    data = {}
    for row in cfg.get("feature_rows") or []:
        col = (row or {}).get("col")
        if not col:
            continue
        val = (row or {}).get("value")
        if val is None or val == "":
            continue
        data[col] = val
    data.update(_override_map(cfg))
    if not data:
        raise ValueError("单节点预测请手填特征列的值")
    return pd.DataFrame([data])


def _run_model_predict(cfg, ctx, node_id=None):
    import numpy as np
    from services import predict_service
    from utils.jsonx import json_safe

    job = _resolve_train_job(cfg)
    output_col = cfg.get("output_col") or job.get("target_col") or "prediction"
    mode = cfg.get("input_mode") or ""
    if mode in ("model", "hybrid"):
        mode = "upstream"
    has_up = _has_ctx_data(ctx, cfg)
    if mode not in ("upstream", "manual"):
        mode = "upstream" if has_up else "manual"
    use_manual = mode == "manual"
    shared = _shared_features_for(node_id, ctx) if use_manual or mode == "manual" else {}
    if not has_up:
        merged = _merge_manual_features(cfg, shared)
        filled = bool(merged.get("feature_rows") or cfg.get("manual_samples") or _override_map(cfg) or shared)
        if filled:
            use_manual = True
            cfg = merged
        else:
            raise ValueError("模型预测请连接数据表 / 逻辑数据集 / 清洗规则，或切手填特征值")
    elif use_manual:
        cfg = _merge_manual_features(cfg, shared)
    if use_manual:
        df = _manual_feature_frame(cfg)
        input_type = "form"
        mode_label = "manual"
    else:
        df = _raw_frame_for_predict(ctx, cfg, job)
        extra = _override_map(cfg)
        if extra:
            for k, v in extra.items():
                df[k] = v
        input_type = "dag"
        mode_label = "upstream"
    preds = predict_service.predict_on_frame(job, df, already_clean=False)
    work = df.copy()
    work[output_col] = preds
    if output_col != "prediction":
        work["prediction"] = preds
    _publish_predict_output(ctx, node_id, work, output_col)
    rec = predict_service.record_from_frame(
        job, work, name=cfg.get("name") or f"DAG预测-{job.get('name')}", input_type=input_type,
    )
    ctx["frame"] = work
    ctx["predict_job_id"] = rec.get("id")
    ctx.setdefault("predict_job_ids", []).append(rec.get("id"))
    summary = {
        "job_id": job.get("id"),
        "job_name": job.get("name"),
        "target_col": job.get("target_col"),
        "output_col": output_col,
        "input_mode": mode_label,
        "n_rows": int(len(work)),
        "pred_mean": round(float(np.mean(preds)), 4),
        "pred_min": round(float(np.min(preds)), 4),
        "pred_max": round(float(np.max(preds)), 4),
    }
    missing = [c for c in (job.get("feature_cols") or []) if c not in df.columns]
    if missing:
        summary["missing_features"] = missing
    ctx["predict_summary"] = {k: json_safe(v) for k, v in summary.items()}
    ctx.setdefault("applied_models", []).append(summary)
    preview_cols = [
        "year", "month", "day", "hour", "site", "temp_c",
        "load_mw", "wind_mw", "solar_mw", "renewable_mw", "price_da", output_col, "prediction",
    ]
    ctx["predictions"] = _preview_rows(work, preview_cols, n=12)
    ctx["predict_preview"] = ctx["predictions"]
    warn = f"（注意：{len(missing)} 个特征没取到值，已按 0 参与预测 → {', '.join(missing)}）" if missing else ""
    return (
        f"预测完成 #{rec.get('id')} {job.get('name')} → {output_col} "
        f"{summary['n_rows']} 行，均值 {summary['pred_mean']}{warn}"
    )


def _run_model_apply(cfg, ctx):
    return _run_model_predict(cfg, ctx)


def _job_brief(job):
    if not job:
        return None
    return {
        "id": job.get("id"),
        "name": job.get("name"),
        "target_col": job.get("target_col"),
        "model_type": job.get("model_type"),
        "status": job.get("status"),
        "metrics": job.get("metrics"),
        "params": job.get("params"),
        "feature_cols": job.get("feature_cols"),
        "importance": (job.get("importance") or [])[:20],
        "duration_sec": job.get("duration_sec"),
    }


def _format_importance(jobs):
    lines = []
    for job in jobs or []:
        lines.append(f"## {job.get('name')}（目标 {job.get('target_col')} / {job.get('model_type')}）")
        metrics = job.get("metrics") or {}
        if metrics:
            bits = [f"{k}={round(float(v), 4) if isinstance(v, (int, float)) else v}" for k, v in metrics.items() if v is not None]
            lines.append("评估：" + "，".join(bits))
        feats = job.get("importance") or []
        if not feats:
            lines.append("（无特征重要性）")
            continue
        for i, item in enumerate(feats[:15], 1):
            if isinstance(item, dict):
                name = item.get("feature") or item.get("name") or item.get("col") or "-"
                score = item.get("importance") or item.get("score") or item.get("weight")
                lines.append(f"{i}. {name}：{score}")
            else:
                lines.append(f"{i}. {item}")
    return "\n".join(lines) or "（无训练任务）"


DEFAULT_PRICE_QUESTION = "根据日前电价模型的评估指标和特征重要性，给出报价策略、套利窗口与风险对冲建议。"

# 数字口径的统一约束：本地小模型容易把「特征重要性」读成概率、把知识库读成阈值表，
# 所有默认提示词共用这一段，避免 LLM 模型洞察环节编造数字。
NUMERIC_GUARD = (
    "【数字口径】只引用【评估指标】【特征重要性】【预测切片】里出现过的数字，并说明来自哪一块；"
    "【特征重要性】是该特征对模型输出的依赖程度，不是概率、不是发生率、不是预警阈值；"
    "知识库片段只给规则口径、不含具体数值，禁止虚构「知识库阈值 / 历史分位 / 预计涨跌幅 / 发生概率」。"
    "缺数据支撑时只做定性描述，不要补数字。"
    "禁止预测具体价位、禁止给出历史波动区间或未来价格点位，只描述「方向 + 触发条件 + 需人工复核」。\n"
)


def _with_numeric_guard(text):
    """把数字口径插到「禁止编造。」之后，作为默认提示词的共用约束。"""
    marker = "禁止编造。\n"
    if marker in text:
        return text.replace(marker, marker + NUMERIC_GUARD, 1)
    return text + NUMERIC_GUARD


# 系统提示词是节点的唯一指令来源：可写 {metrics}/{importance}/{predictions}/{context}/{question}
# 占位符，运行时自动填充；也可由用户整段替换成自定义文风（此时平台会自动补数据块）。
# _LEGACY_* 是「含偏差考核 / 合规注意」的旧版默认文案，仅用于启动时识别并就地升级，勿直接使用。
_PRICE_ROLE = "你是电力交易分析岗"
_RISK_ROLE = "你是电力交易风险分析岗"
_TRAIN_ROLE = "你是电力现货市场的气象驱动预测分析岗"

_LEGACY_PRICE_SYSTEM = (
    "你是电力交易分析岗。只输出最终中文正文，禁止思考提纲。"
    "数字必须来自下方【评估指标】和【预测切片】，禁止编造。\n"
    "按 4 节写，每节 3–6 句：\n"
    "1. 本轮 DAG 做了什么（哪些上游模型、是否手填特征）\n"
    "2. 日前电价预测要点（趋势、高峰时段）\n"
    "3. 报价策略、套利建议、风险对冲（须写需交易员确认）\n"
    "4. 偏差考核与后续数据注意点\n\n"
    "【评估指标】\n{metrics}\n\n【特征重要性】\n{importance}\n\n"
    "【预测切片】\n{predictions}\n\n【知识库召回片段】\n{context}"
)
_LEGACY_RISK_SYSTEM = (
    "你是电力交易风险分析岗。只输出最终中文正文，禁止思考提纲。"
    "数字必须来自下方【预测切片】，禁止编造。\n"
    "按 4 节写，每节 3–6 句：\n"
    "1. 预测概况（模型、样本数、预测区间、输入是上游数据还是手填特征）\n"
    "2. 风险预警（高峰、极端值、与知识库规则对照）\n"
    "3. 偏差考核与合规注意\n"
    "4. 处置建议（须写需交易员确认，系统未下单）\n\n"
    "【评估指标】\n{metrics}\n\n【特征重要性】\n{importance}\n\n"
    "【预测切片】\n{predictions}\n\n【知识库召回片段】\n{context}"
)
# 训练段只有第 4 节标题变了，用这一句作判据
_LEGACY_TRAIN_MARK = "4. 偏差考核、负出力裁剪与后续数据注意"

_RAW_PRICE_SYSTEM = (
    "你是电力交易分析岗。只输出最终中文正文，禁止思考提纲。"
    "数字必须来自下方【评估指标】和【预测切片】，禁止编造。\n"
    "按 4 节写，每节 3–6 句：\n"
    "1. 本轮 DAG 做了什么（哪些上游模型、是否手填特征）\n"
    "2. 日前电价预测要点（趋势、高峰时段）\n"
    "3. 报价策略、套利建议、风险对冲（须写需交易员确认）\n"
    "4. 数据质量与后续注意点\n\n"
    "【评估指标】\n{metrics}\n\n【特征重要性】\n{importance}\n\n"
    "【预测切片】\n{predictions}\n\n【知识库召回片段】\n{context}"
)
DEFAULT_PRICE_SYSTEM = _with_numeric_guard(_RAW_PRICE_SYSTEM)
DEFAULT_RISK_QUESTION = "根据本次模型预测结果，结合市场规则给出风险预警与报价注意点。"
_RAW_RISK_SYSTEM = (
    "你是电力交易风险分析岗。只输出最终中文正文，禁止思考提纲。"
    "数字必须来自下方【预测切片】，禁止编造。\n"
    "按 4 节写，每节 3–6 句：\n"
    "1. 预测概况（模型、样本数、预测区间、输入是上游数据还是手填特征）\n"
    "2. 风险预警（高峰、极端值、与知识库规则对照）\n"
    "3. 报价注意点（报价带、高峰时段、申报口径）\n"
    "4. 处置建议（须写需交易员确认，系统未下单）\n\n"
    "【评估指标】\n{metrics}\n\n【特征重要性】\n{importance}\n\n"
    "【预测切片】\n{predictions}\n\n【知识库召回片段】\n{context}"
)
DEFAULT_RISK_SYSTEM = _with_numeric_guard(_RAW_RISK_SYSTEM)
_RAW_TRAIN_SYSTEM_HEAD = (
    "你是电力现货市场的气象驱动预测分析岗。只输出最终中文正文，禁止思考提纲。"
    "数字必须来自下方【评估指标】和【特征重要性】，禁止编造。\n"
)
DEFAULT_TRAIN_SYSTEM_HEAD = _with_numeric_guard(_RAW_TRAIN_SYSTEM_HEAD)
DEFAULT_TRAIN_SYSTEM_TAIL = (
    "按 4 节写，每节 3–6 句：\n"
    "1. 本轮训练做了什么（目标列、算法、关键气象特征）\n"
    "2. 出力或负荷形态与极端天气情景（热浪/寒潮/台风/强对流）\n"
    "3. 对调度与现货交易的影响（须写需人工确认，系统未下单）\n"
    "4. 负出力裁剪与后续数据注意\n\n"
    "【评估指标】\n{metrics}\n\n【特征重要性】\n{importance}\n\n"
    "【预测切片】\n{predictions}\n\n【知识库召回片段】\n{context}"
)


_GUARD_RE = re.compile(r"^【数字口径[^\n]*\n", re.M)


def _core_prompt(text):
    """剥掉已插入的数字口径行，便于与默认文案比对（支持跨版本升级）。"""
    return _GUARD_RE.sub("", text or "").strip()


def _train_system(focus=None):
    mid = f"本轮重点：{focus}\n" if (focus or "").strip() else ""
    return DEFAULT_TRAIN_SYSTEM_HEAD + mid + DEFAULT_TRAIN_SYSTEM_TAIL


DEFAULT_TRAIN_SYSTEM = _train_system()
TARGET_CN = {
    "load_mw": "用电负荷",
    "wind_mw": "风电出力",
    "solar_mw": "光伏出力",
    "renewable_mw": "风光出力",
    "price_da": "日前电价",
}


def _primary_job(jobs):
    jobs = jobs or []
    return next((j for j in jobs if j.get("target_col") == "price_da"), jobs[-1] if jobs else {})


def _target_label(col):
    return TARGET_CN.get(col, col or "模型")


def _fallback_train_report(facts, jobs, importance_text, answer):
    job = _primary_job(jobs)
    col = (job or {}).get("target_col") or ""
    label = _target_label(col)
    metrics = (job or {}).get("metrics") or {}
    applied = facts.get("applied_models") or []
    lines = [
        f"# {label}训练 DAG 结果（{facts.get('graph_name') or ''}）",
        "",
        "> 离线作业。数字来自本轮训练指标，调度/交易建议需人工确认，系统未下单。",
        "",
        "## 1. 本轮训练",
        f"目标列 {col or '-'}（{label}），经气象-负荷-风光逻辑数据集清洗后训练，再由大模型解读指标与特征重要性。",
        "",
        importance_text or "（无特征重要性）",
    ]
    for a in applied:
        lines.append(
            f"- {a.get('job_name')} → {a.get('output_col')}，均值 {a.get('pred_mean')}，区间 {a.get('pred_min')}–{a.get('pred_max')}"
        )
    if facts.get("manual_fills"):
        lines.append(f"手填覆盖：{facts.get('manual_fills')}")
    hint = {
        "solar_mw": "辐照和热浪抬升午间出力，阴雨/强对流压低；关注消纳受阻与午间反调峰。",
        "wind_mw": "100米风速主导出力，台风和大风有切出风险；低风速时段出力接近 0。",
        "renewable_mw": "风光合计高发时残余负荷下降、电价承压；关注消纳与反调峰。",
        "load_mw": "气温与热浪/寒潮驱动负荷，晚高峰与空调负荷是关键窗口。",
        "price_da": "负荷抬升、风光下降时残余负荷增加，日前价格趋势向上；高峰时段应重点看带宽。",
    }.get(col, "结合气象特征解读本轮拟合质量。")
    lines += [
        "",
        f"## 2. {label}要点",
        f"任务「{job.get('name')}」状态 {job.get('status')}，RMSE={metrics.get('rmse')}，MAE={metrics.get('mae')}，R²={metrics.get('r2')}。",
        hint,
        "",
        "## 3. 调度 / 交易影响",
    ]
    if col == "price_da":
        lines += [
            "报价：按日前点预测覆盖高峰负荷小时，避免在新能源高发、残余负荷偏低时段顶格申报。",
            "套利：关注峰谷价差显著且阻塞不高的小时窗口，以模型输出为准。",
            "对冲：热浪/台风等极端情景下优先考虑中长期仓位。以上需交易员确认，系统未下单。",
        ]
    else:
        lines.append("本报告只解读训练指标，不构成报价或下单指令，需调度/交易员确认。")
    lines += [
        "",
        "## 4. 数据质量与后续注意",
        "风电/光伏预测若出现负值应裁剪为 0。系统未接入实时行情，本轮为离线回放。",
    ]
    if answer and len(answer) >= 600:
        lines += ["", "---", f"*{answer[:300]}*"]
    return "\n".join(lines)


# ── DAG 内 LLM 节点统一生成 ──────────────────────────────────────────────
# 节点上的「系统提示词」是唯一指令来源（平台模板或用户自定义），可写
# {metrics}/{importance}/{predictions}/{context}/{question} 占位符；
# 「用户短问题」可选、允许为空，召回也允许为空，都不影响报告输出。


def _dag_rag_query(ctx, label, question):
    """短问题为空时，用图谱名 + 目标列推导检索词；仍为空则放弃召回。"""
    if (question or "").strip():
        return question.strip()
    parts = [str(ctx.get("graph_name") or "").strip(), str(label or "").strip()]
    return " ".join([p for p in parts if p]).strip()


def _dag_llm_generate(ctx, cfg, label, default_system, variables):
    """统一的 DAG LLM 调用。返回 (answer, snippets, question, system_prompt)。"""
    from services.llm_service import LLMService

    cfg = cfg or {}
    question = (cfg.get("question") or "").strip()
    answer, snippets, system, question = LLMService.generate_report(
        cfg.get("system_prompt"),
        question,
        variables,
        llm_config_id=_as_int(cfg.get("llm_config_id")),
        use_rag=cfg.get("use_rag", True),
        top_k=int(cfg.get("rag_top_k") or 6),
        rag_query=_dag_rag_query(ctx, label, question),
        default_system=default_system,
    )
    return answer, snippets, question, system


def _save_insight_report(title, content, snippets, train_job_id=None, predict_job_id=None, cfg=None):
    """把 DAG 生成的洞察写入「洞察报告」列表（insight_report）。"""
    from services import insight_service
    from utils.jsonx import dumps

    cfg = cfg or {}
    # 定时/后台运行时没有 flask g，回落到 admin，保证洞察报告列表里能看到
    user = _bind_admin_user() or {}
    try:
        rid = insight_service.create_raw(
            title=title,
            content=content or "",
            train_job_id=train_job_id,
            predict_job_id=predict_job_id,
            rag_context=dumps([
                {"source": s.get("source"), "idx": s.get("idx"), "text": (s.get("text") or "")[:400]}
                for s in (snippets or [])[:8]
            ]),
            llm_config_id=cfg.get("llm_config_id"),
            prompt_id=cfg.get("system_prompt_id") or cfg.get("prompt_id"),
            user=user,
        )
        return rid
    except Exception:
        return None


def _attach_llm_to_predict(predict_job_id, answer, snippets, cfg, question):
    """把风险预警节点的 LLM 分析回写到对应预测记录，供「模型预测记录」查看。"""
    pid = _as_int(predict_job_id)
    if not pid or not (answer or "").strip():
        return
    from utils.jsonx import dumps as _dumps

    payload = {
        "use_llm": 1,
        "use_rag": 1 if (cfg or {}).get("use_rag", True) else 0,
        "llm_analysis": answer,
        "rag_context": _dumps([
            {"source": s.get("source"), "idx": s.get("idx"), "text": (s.get("text") or "")[:400]}
            for s in (snippets or [])[:8]
        ]),
    }
    llm_id = _as_int((cfg or {}).get("llm_config_id"))
    if llm_id:
        payload["llm_config_id"] = llm_id
    if (question or "").strip():
        payload["llm_question"] = question.strip()
    try:
        update("predict_job", payload, "id=%s", (pid,))
    except Exception:
        pass


def _llm_from_dag_ctx(ctx, cfg=None):
    from services import model_service, power_engine
    from utils.jsonx import dumps

    cfg = cfg or {}
    seen = set()
    jobs = []
    for jid in list(ctx.get("job_ids") or []):
        if jid in seen:
            continue
        seen.add(jid)
        brief = _job_brief(model_service.get_job(jid))
        if brief:
            jobs.append(brief)
    for item in ctx.get("applied_models") or []:
        jid = item.get("job_id")
        if not jid or jid in seen:
            continue
        seen.add(jid)
        brief = _job_brief(model_service.get_job(jid))
        if brief:
            jobs.append(brief)
    facts = {
        "graph_name": ctx.get("graph_name"),
        "offline": True,
        "applied_models": ctx.get("applied_models") or [],
        "manual_fills": ctx.get("manual_fills") or {},
        "jobs": jobs,
    }
    preview = ctx.get("predict_preview") or []
    importance_text = _format_importance(jobs)
    try:
        answer, snippets, question, _ = _dag_llm_generate(
            ctx, cfg, _target_label((_primary_job(jobs) or {}).get("target_col")),
            DEFAULT_PRICE_SYSTEM,
            {
                "metrics": dumps(facts),
                "importance": importance_text,
                "predictions": dumps(preview),
            },
        )
    except Exception as e:
        answer, snippets, question = f"（大模型调用失败：{e}）", [], (cfg.get("question") or "").strip()
    from services.power_service import _is_usable_report, _strip_think
    answer = _strip_think(answer or "")
    if not _is_usable_report(answer):
        answer = _fallback_train_report(facts, jobs, importance_text, answer)
    ctx["rag_snippets"] = [
        {"source": s.get("source"), "idx": s.get("idx"), "score": s.get("score"), "text": (s.get("text") or "")[:400]}
        for s in (snippets or [])[:8]
    ]
    ctx["question"] = question
    job = _primary_job(jobs)
    label = _target_label((job or {}).get("target_col"))
    title = f"{label}模型洞察-{ctx.get('graph_name') or ''}"
    rid = power_engine.save_report(
        title,
        answer or "",
        dumps([{"source": s.get("source"), "text": s.get("text")} for s in (snippets or [])[:8]]),
        _current_user(),
    )
    insight_id = _save_insight_report(
        title, answer or "", snippets,
        train_job_id=(job or {}).get("id"), cfg=cfg,
    )
    ctx["report_id"] = rid
    ctx["insight_report_id"] = insight_id
    ctx["llm_report"] = (answer or "")[:6000]
    if insight_id:
        return f"已生成{label}模型洞察 #{rid}，并写入洞察报告 #{insight_id}"
    return f"已生成{label}模型洞察 #{rid}"


def _llm_risk_from_ctx(ctx, cfg=None):
    from services import model_service
    from services.power_engine import save_report as save_power_report
    from services.power_service import _is_usable_report, _strip_think
    from utils.jsonx import dumps

    cfg = cfg or {}
    preds = ctx.get("predictions") or ctx.get("predict_preview") or []
    if not preds and not ctx.get("predict_job_id"):
        raise ValueError("风险预警报告需要上游模型预测结果")
    summary = ctx.get("predict_summary") or {}
    job_brief = None
    if summary.get("job_id"):
        job_brief = _job_brief(model_service.get_job(summary["job_id"]))
    facts = {
        "graph_name": ctx.get("graph_name"),
        "offline": True,
        "predict_job_id": ctx.get("predict_job_id"),
        "predict_summary": summary,
        "applied_models": ctx.get("applied_models") or [],
        "job": job_brief,
    }
    importance_text = _format_importance([job_brief] if job_brief else [])
    try:
        answer, snippets, question, _ = _dag_llm_generate(
            ctx, cfg, "预测风险预警", DEFAULT_RISK_SYSTEM,
            {
                "metrics": dumps(facts),
                "importance": importance_text,
                "predictions": dumps(preds),
            },
        )
    except Exception as e:
        answer, snippets, question = f"（大模型调用失败：{e}）", [], (cfg.get("question") or "").strip()
    answer = _strip_think(answer or "")
    if not _is_usable_report(answer):
        lines = [
            f"# 预测风险预警（{facts.get('graph_name') or ''}）",
            "",
            "> 离线作业。数字来自本轮模型预测，报价/套利/对冲需交易员确认，系统未下单。",
            "",
            "## 1. 预测概况",
            f"模型「{summary.get('job_name') or (job_brief or {}).get('name') or '-'}」"
            f"输出 {summary.get('output_col') or (job_brief or {}).get('target_col')}，"
            f"样本 {summary.get('n_rows')} 行，均值 {summary.get('pred_mean')}，"
            f"区间 {summary.get('pred_min')}–{summary.get('pred_max')}。",
            f"输入方式：{'手填特征值' if summary.get('input_mode') == 'manual' else '上游数据/清洗结果'}。",
            "",
            "## 2. 风险预警",
            "关注预测高值对应的高峰小时与极端气象时段，避免在新能源高发、残余负荷偏低时顶格申报。",
            "",
            "## 3. 报价注意点",
            "按预测区间准备报价带，避免在新能源高发、残余负荷偏低时顶格申报；高峰时段优先保证电量覆盖。",
            "",
            "## 4. 处置建议",
            "按预测区间准备报价带，热浪/台风等情景优先评估中长期仓位。以上需交易员确认。",
        ]
        if preds:
            lines += ["", "预测切片：", dumps(preds[:8])]
        if answer and len(answer) >= 600:
            lines += ["", "---", f"*{answer[:300]}*"]
        answer = "\n".join(lines)
    ctx["rag_snippets"] = [
        {"source": s.get("source"), "idx": s.get("idx"), "score": s.get("score"), "text": (s.get("text") or "")[:400]}
        for s in (snippets or [])[:8]
    ]
    ctx["question"] = question
    _attach_llm_to_predict(ctx.get("predict_job_id"), answer, snippets, cfg, question)
    rid = save_power_report(
        f"预测风险预警-{ctx.get('graph_name') or ''}",
        answer or "",
        dumps([{"source": s.get("source"), "text": s.get("text")} for s in (snippets or [])[:8]]),
        _current_user(),
    )
    ctx["risk_report_id"] = rid
    ctx["report_id"] = rid
    ctx["llm_report"] = (answer or "")[:6000]
    insight_id = _save_insight_report(
        f"预测风险预警-{ctx.get('graph_name') or ''}",
        answer or "", snippets,
        predict_job_id=ctx.get("predict_job_id"), cfg=cfg,
    )
    if insight_id:
        ctx["insight_report_id"] = insight_id
        return f"已生成风险预警报告 #{rid}，并写入洞察报告 #{insight_id}"
    return f"已生成风险预警报告 #{rid}"


def _run_node(node, ctx):
    ntype = (node or {}).get("type") if isinstance(node, dict) else node
    cfg = ((node or {}).get("config") or {}) if isinstance(node, dict) else {}
    if ntype == "asset.dataset":
        from services import dataset_service
        ds_id = _resolve_dataset_id(cfg)
        if not ds_id:
            raise ValueError("数据表节点未选择数据集")
        ds = dataset_service.get_dataset(ds_id)
        if not ds:
            raise ValueError(f"数据表 #{ds_id} 不存在")
        ctx["target_type"] = "dataset"
        ctx["target_id"] = ds_id
        return f"数据表「{ds.get('name')}」{ds.get('n_rows') or 0} 行"
    if ntype == "asset.bundle":
        from services import dataset_service
        bid = _resolve_bundle_id(cfg)
        if not bid:
            raise ValueError("逻辑数据集节点未选择数据集")
        bundle = dataset_service.get_bundle(bid)
        if not bundle:
            raise ValueError(f"逻辑数据集 #{bid} 不存在")
        ctx["target_type"] = "bundle"
        ctx["target_id"] = bid
        return f"逻辑数据集「{bundle.get('name')}」{bundle.get('n_rows') or 0} 行"
    if ntype == "source.mysql":
        from services import source_service
        sid = cfg.get("source_id")
        db = cfg.get("database") or cfg.get("source_db")
        table = cfg.get("table") or cfg.get("source_table")
        if not sid or not db or not table:
            raise ValueError("数据源节点请选择数据源、库和表")
        from services import live_ops
        project_id = cfg.get("project_id") or live_ops.ensure_project()["id"]
        ds = source_service.attach_live_dataset(
            int(sid), project_id, db, table,
            name=cfg.get("dataset_name"),
            remark=cfg.get("remark") or "",
            scenario=cfg.get("scenario_code") or ctx.get("scenario_code") or "generic",
        )
        ctx["target_type"] = "dataset"
        ctx["target_id"] = ds["id"]
        ctx["dataset"] = {"id": ds["id"], "rows": ds.get("n_rows")}
        return f"已接入活表 {db}.{table}，当前 {ds.get('n_rows') or 0} 行"
    if ntype == "asset.export_weather":
        from services import weather_asset
        out = weather_asset.export_to_space()
        ctx["dataset"] = {"id": out["dataset"]["id"], "rows": out["dataset"].get("n_rows")}
        ctx["target_type"] = "dataset"
        ctx["target_id"] = out["dataset"]["id"]
        return f"已写入数据空间「{out['project']['name']}」{out['dataset'].get('n_rows')} 行"
    if ntype == "clean.apply_rule":
        from services import clean_service, weather_asset
        rule_id = _resolve_rule_id(cfg)
        target_type = _as_frame_target(cfg.get("target_type") or ctx.get("target_type"))
        target_id = cfg.get("target_id") or ctx.get("target_id")
        if target_type and target_id and rule_id:
            out = clean_service.bind_and_materialize(
                target_type, int(target_id), int(rule_id), name=cfg.get("binding_name"),
                # 必须先读完整数据再由训练服务按 random_state 随机抽样；
                # 只读前 sample*2 行会让实时表抽样长期偏向旧数据。
                nrows=None, persist=False,
            )
            ctx["binding_id"] = out.get("id")
            ctx["target_type"] = target_type
            ctx["target_id"] = int(target_id)
            engine = out.get("_engine")
            if engine is not None:
                ctx["clean_engine_state"] = engine.state()
                ctx["clean_steps"] = out.get("_steps") or []
                ctx["raw_frame"] = out.get("_raw")
                ctx["frame"] = out.get("_cleaned")
            else:
                try:
                    from services import model_service
                    df, eng, steps, _ = model_service.prepare_frame(
                        target_type, int(target_id), binding_id=out.get("id"),
                    )
                    ctx["frame"] = df
                    ctx["clean_engine_state"] = eng.state()
                    ctx["clean_steps"] = steps
                except Exception:
                    pass
            return f"已套用清洗规则，快照 {out.get('n_rows')} 行"
        out = weather_asset.apply_weather_clean()
        ctx["binding_id"] = (out.get("binding") or {}).get("id")
        return f"已套用清洗规则，快照 {(out.get('binding') or {}).get('n_rows')} 行"
    if ntype == "feat.shared":
        pack = _feature_row_map(cfg.get("feature_rows"))
        ctx.setdefault("shared_feature_packs", {})[node.get("id")] = pack
        return f"共用特征值 {len(pack)} 项已就绪"
    if ntype == "model.train":
        from services import clean_service, model_service
        target_type = _as_frame_target(cfg.get("target_type") or ctx.get("target_type"))
        target_id = cfg.get("target_id") or ctx.get("target_id")
        binding_id = cfg.get("binding_id") or ctx.get("binding_id")
        rule_id = None if binding_id else _resolve_rule_id(cfg)
        if target_type == "binding" and target_id:
            binding = clean_service.get_binding(int(target_id))
            if not binding:
                raise ValueError("清洗快照不存在")
            binding_id = int(target_id)
            target_type = binding.get("target_type") or "bundle"
            target_id = binding.get("target_id")
            rule_id = None
        elif binding_id:
            binding = clean_service.get_binding(int(binding_id))
            if binding:
                target_type = target_type or binding.get("target_type")
                target_id = target_id or binding.get("target_id")
                rule_id = None
        target_col = cfg.get("target_col")
        if not target_type or not target_id:
            raise ValueError("模型训练节点缺少上游数据集")
        if not target_col:
            raise ValueError("模型训练节点未配置目标列")
        feats = cfg.get("feature_cols") or []
        if not feats:
            if ctx.get("frame") is not None:
                feats = _feature_cols_from_schema(list(ctx["frame"].columns), target_col)
            elif binding_id:
                binding = clean_service.get_binding(binding_id) or {}
                feats = _feature_cols_from_schema(binding.get("schema"), target_col)
        engine_state = ctx.get("clean_engine_state")
        if not engine_state and ctx.get("frame_engine") is not None:
            try:
                engine_state = ctx["frame_engine"].state()
            except Exception:
                engine_state = None
        steps = ctx.get("clean_steps") or ctx.get("frame_steps") or []
        if (not engine_state or not steps) and binding_id:
            binding = clean_service.get_binding(int(binding_id)) or {}
            restored = model_service._load_binding_engine(binding)
            if restored is not None:
                _snap, eng = restored
                engine_state = engine_state or eng.state()
            if not steps:
                rule = binding.get("rule") or {}
                steps = clean_service.ordered_steps(rule.get("steps") or [], rule.get("edges"))
        job = model_service.create_and_run({
            "name": cfg.get("name") or f"DAG训练-{target_col}",
            "scenario_code": cfg.get("scenario_code") or ctx.get("scenario_code") or "power_trading",
            "target_type": target_type,
            "target_id": int(target_id),
            "binding_id": binding_id,
            "rule_id": rule_id,
            "target_col": target_col,
            "feature_cols": feats,
            "task_type": cfg.get("task_type") or "regression",
            "model_type": cfg.get("model_type") or "random_forest",
            "params": cfg.get("params") or {},
            "sample_rows": cfg.get("sample_rows") if cfg.get("sample_rows") is not None else 0,
            "test_size": cfg.get("test_size") or 0.2,
            "random_state": cfg.get("random_state") or 42,
            "log_target": bool(cfg.get("log_target")),
            "param_preset": cfg.get("preset") or cfg.get("param_preset"),
        }, wait=True, frame=ctx.get("frame"),
            engine_state=engine_state,
            steps=steps,
        )
        ctx["job_id"] = job.get("id")
        ctx.setdefault("job_ids", []).append(job.get("id"))
        metrics = job.get("metrics") or {}
        return (
            f"训练完成 #{job.get('id')} {job.get('name')}（{job.get('status')}）"
            + (f" RMSE={round(float(metrics['rmse']), 3)}" if metrics.get("rmse") is not None else "")
        )
    if ntype in ("model.predict", "model.apply"):
        return _run_model_predict(cfg, ctx, node_id=node.get("id"))
    if ntype == "clean.qc_ts":
        n = query("SELECT COUNT(*) AS c FROM power_hourly", one=True) or {}
        return f"序列就绪 {n.get('c') or 0} 点"
    if ntype == "llm.risk":
        return _llm_risk_from_ctx(ctx, cfg)
    if ntype == "llm.report":
        if ctx.get("job_ids") or ctx.get("applied_models"):
            return _llm_from_dag_ctx(ctx, cfg)
        try:
            from services.power_service import generate_decision_report
            report = generate_decision_report()
            ctx["report_id"] = report.get("id")
            return "决策报告已生成"
        except Exception as e:
            return f"报告生成失败: {e}"
    if ntype in ("source.file", "table.join"):
        return "通用节点：请在资产中心配置后接入（已跳过执行）"
    return "已执行"


_CTX_SKIP = {
    "shock", "strategy", "frame", "frame_engine", "frame_steps",
    "edges", "nodes", "raw_frame", "clean_engine_state",
    "shared_feature_packs",
}


def _ctx_public(ctx):
    """运行结果只保留可 JSON 的摘要，避开 DataFrame / LabelEncoder。"""
    out = {k: ctx[k] for k in ctx if k not in _CTX_SKIP}
    engine = ctx.get("clean_engine_state") or {}
    if isinstance(engine, dict) and (engine.get("encoders") or engine.get("scale_cols") or engine.get("scaler")):
        encoders = engine.get("encoders") or {}
        out["preprocess"] = {
            "encoders": list(encoders.keys()) if isinstance(encoders, dict) else [],
            "scale_cols": engine.get("scale_cols") or [],
            "has_scaler": engine.get("scaler") is not None,
        }
    raw = ctx.get("raw_frame")
    if raw is not None:
        try:
            out["raw_rows"] = int(len(raw))
        except Exception:
            pass
    return out


def run_graph(gid, trigger="manual"):
    user = _bind_admin_user()
    graph = get_graph(gid)
    if not graph:
        raise ValueError("流程不存在")
    gdef = graph.get("graph") or {}
    nodes = gdef.get("nodes") or []
    edges = gdef.get("edges") or []
    order = _topo(nodes, edges)
    by_id = {n["id"]: n for n in nodes}
    run_id = insert("if_graph_run", {
        "graph_id": gid,
        "status": "running",
        "trigger_source": trigger or "manual",
        "log_text": "开始执行\n",
        "user_id": user.get("id"),
        "username": user.get("username"),
    })
    started = time.time()
    ctx = {
        "scenario_code": graph.get("scenario_code") or "generic",
        "graph_name": graph.get("name"),
        "graph_id": gid,
        "edges": edges,
        "nodes": nodes,
    }
    logs = []
    sample_rows = 0
    for n in nodes:
        if n.get("type") != "model.train":
            continue
        cfg = n.get("config") or {}
        try:
            sample_rows = max(sample_rows, int(cfg.get("sample_rows") or 0))
        except (TypeError, ValueError):
            pass
    ctx["train_sample_rows"] = sample_rows
    try:
        for nid in order:
            node = by_id[nid]
            t0 = time.time()
            msg = _run_node(node, ctx)
            dt = time.time() - t0
            insert("if_node_run", {
                "run_id": run_id,
                "node_id": nid,
                "node_type": node.get("type"),
                "status": "success",
                "message": (msg or "")[:500],
                "duration_sec": round(dt, 2),
            })
            logs.append(f"{nid} {node.get('type')}: {msg}")
        update("if_graph_run", {
            "status": "success",
            "log_text": "\n".join(logs),
            "result_json": dumps(_ctx_public(ctx)),
            "duration_sec": round(time.time() - started, 2),
        }, "id=%s", (run_id,))
    except Exception as e:
        update("if_graph_run", {
            "status": "failed",
            "log_text": "\n".join(logs + [str(e)]),
            "error_message": str(e)[:500],
            "duration_sec": round(time.time() - started, 2),
        }, "id=%s", (run_id,))
        raise
    return get_run(run_id)


def get_run(rid):
    row = query("SELECT * FROM if_graph_run WHERE id=%s", (rid,), one=True)
    if not row:
        return None
    data = row_to_dict(row)
    data["result"] = loads(row.get("result_json"), default={})
    data["nodes"] = [row_to_dict(n) for n in query("SELECT * FROM if_node_run WHERE run_id=%s ORDER BY id", (rid,))]
    return data


def list_runs(graph_id=None, limit=20, page=None, page_size=None):
    sql = "SELECT * FROM if_graph_run WHERE 1=1"
    args = []
    if graph_id:
        sql += " AND graph_id=%s"
        args.append(int(graph_id))
    sql += " ORDER BY id DESC"
    rows = []
    for r in query(sql, args):
        row = row_to_dict(r)
        row["result"] = loads(row.get("result_json"), default={})
        rows.append(row)
    if page is not None:
        from utils.paging import paginate
        return paginate(rows, (page, page_size or 10))
    return rows[:int(limit or 20)]


def delete_graph(gid):
    update("if_graph", {"status": 0, "schedule_enabled": 0}, "id=%s", (gid,))


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


def delete_graphs(gids):
    ids = _parse_ids(gids)
    deleted, missing = [], []
    for gid in ids:
        row = query("SELECT id, status FROM if_graph WHERE id=%s", (gid,), one=True)
        if not row or int(row.get("status") or 0) != 1:
            missing.append(gid)
            continue
        delete_graph(gid)
        deleted.append(gid)
    return {"deleted": len(deleted), "ids": deleted, "missing": missing}


def patch_schedule(gid, payload):
    graph = get_graph(gid)
    if not graph:
        raise ValueError("流程不存在")
    data = {}
    if "schedule_kind" in payload:
        data["schedule_kind"] = payload.get("schedule_kind") or "none"
    if "schedule_enabled" in payload:
        data["schedule_enabled"] = 1 if payload.get("schedule_enabled") else 0
    if data:
        update("if_graph", data, "id=%s", (gid,))
    return get_graph(gid)


def _upsert_named_graph(spec, refresh_graph=False, overwrite_graph=False):
    """按「稳定标识 seed_key」认领系统种子流程，避免用户改名/删除后被重新造一份。

    匹配顺序：
    1. 有 seed_key 就按 seed_key 找（含已软删的行）；
    2. 老库还没有 seed_key 时，按名称认领一次并回填 seed_key（一次性迁移）；
    3. 谁都没有才新建。

    找不到行 = 从没种过 → 创建；
    找到但 status=0 = 用户主动删过 → 尊重删除，不重建；
    找到且 status=1 = 用户在用的 → 保留其画布，只做结构合并。
    """
    name = spec["name"]
    seed_key = spec.get("seed_key")
    fields = "id, name, is_template, status, schedule_kind, schedule_enabled"
    row = None
    if seed_key:
        row = query(f"SELECT {fields} FROM if_graph WHERE seed_key=%s", (seed_key,), one=True)
    if not row:
        # 老库兜底：按名字认领（优先 active 的那条），并回填 seed_key。
        row = query(
            f"SELECT {fields} FROM if_graph WHERE name=%s ORDER BY status DESC, id DESC LIMIT 1",
            (name,),
            one=True,
        )
        if row and seed_key:
            update("if_graph", {"seed_key": seed_key}, "id=%s", (row["id"],))
    if row and not row.get("status"):
        return None
    payload = {
        "name": name,
        "scenario_code": spec.get("scenario_code") or "power_trading",
        "description": spec.get("description") or "",
        "is_template": spec.get("is_template") or 0,
        "schedule_kind": spec.get("schedule_kind") or "none",
        "schedule_enabled": spec.get("schedule_enabled") or 0,
        "graph": spec.get("graph") or {"nodes": [], "edges": []},
        "seed_key": seed_key,
        "username": "system",
    }
    if row:
        if not refresh_graph:
            return get_graph(row["id"])
        payload["schedule_kind"] = row.get("schedule_kind") or payload["schedule_kind"]
        payload["schedule_enabled"] = row.get("schedule_enabled")
        if not overwrite_graph:
            existing = get_graph(row["id"]) or {}
            payload["graph"] = _merge_graph_keep_user(existing.get("graph"), payload["graph"])
        return save_graph(payload, row["id"])
    return save_graph(payload)


def _merge_graph_keep_user(existing, seeded):
    """结构补齐用种子图，训练节点的算法/超参以用户已保存的为准。"""
    old = existing if isinstance(existing, dict) else {}
    new = seeded if isinstance(seeded, dict) else {}
    old_nodes = {n.get("id"): n for n in (old.get("nodes") or []) if n.get("id")}
    if not old_nodes:
        return new or old
    merged_nodes = []
    for node in new.get("nodes") or old.get("nodes") or []:
        nid = node.get("id")
        prev = old_nodes.get(nid)
        if not prev:
            merged_nodes.append(node)
            continue
        keep = dict(node)
        keep["x"] = prev.get("x", keep.get("x"))
        keep["y"] = prev.get("y", keep.get("y"))
        if (prev.get("type") or "") == "model.train" or (node.get("type") or "") == "model.train":
            keep["config"] = dict(node.get("config") or {})
            keep["config"].update(prev.get("config") or {})
        else:
            cfg = dict(node.get("config") or {})
            cfg.update(prev.get("config") or {})
            keep["config"] = cfg
        merged_nodes.append(keep)
    seen = {n.get("id") for n in merged_nodes}
    for nid, prev in old_nodes.items():
        if nid not in seen:
            merged_nodes.append(prev)
    return {
        "nodes": merged_nodes,
        "edges": old.get("edges") or new.get("edges") or [],
    }


# 仅用于识别历史默认文案（比对用，不发给模型）。这里必须保留旧措辞，
# 否则启动迁移就认不出带「偏差考核 / 合规注意」的老提示词、无法自动升级。
_OLD_PROMPT_MARKERS = (
    "数字必须来自用户消息中的【评估指标】",
    "1) 本轮训练与关键气象特征",
    "按 4 节写：1) 预测概况 2) 风险预警 3) 偏差考核",
    "按 4 节写：1) 本轮训练与关键特征 2) 日前电价要点",
)


def _is_old_seed_prompt(text):
    text = text or ""
    return any(m in text for m in _OLD_PROMPT_MARKERS)


def _looks_like_train_report(text):
    text = text or ""
    return ("气象特征" in text) or ("出力或负荷形态" in text) or ("极端情景" in text)


def _prompt_role(text):
    """识别默认提示词的角色；用户自写文案返回 None。"""
    core = _core_prompt(text or "")
    for role, marker in (("risk", _RISK_ROLE), ("price", _PRICE_ROLE), ("train", _TRAIN_ROLE)):
        if core.startswith(marker):
            return role
    return None


def _train_focus(text):
    """取回用户自定义的「本轮重点：…」那一句（只到行尾），升级时不被冲掉。

    注意：只取本行！早先的实现取「本轮目标是」到文末，会把旧的第 3/4 节
    一起塞进 focus，导致每次迁移都往里追加一份旧章节。
    """
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("本轮重点："):
            return s[len("本轮重点："):].strip()
    return ""


def _upgraded_default_prompt(text, ntype):
    """把旧版默认提示词换成当前版本；用户自写文案或已是最新版时返回 None。

    覆盖两类历史文案：
    - 缺少「数字口径」约束的旧版；
    - 章节里带「偏差考核 / 合规注意」的旧版。
    """
    text = text or ""
    if not text.strip():
        return None
    if _is_old_seed_prompt(text):
        role = "risk" if ntype == "llm.risk" else ("train" if _looks_like_train_report(text) else "price")
    else:
        role = _prompt_role(text)
        if not role:
            return None
        if role == "train" and _LEGACY_TRAIN_MARK not in _core_prompt(text):
            return None
    if ntype == "llm.risk":
        target = DEFAULT_RISK_SYSTEM
    elif role == "train" or _looks_like_train_report(text):
        target = _train_system(_train_focus(text))
    else:
        target = DEFAULT_PRICE_SYSTEM
    return None if target.strip() == text.strip() else target


# 历史种子里「用户短问题」带「偏差考核」的文案 → 现行版本。
# 只按整句精确匹配替换，用户自己改过的问法不动。
_LEGACY_QUESTION_FIXES = (
    (
        "根据本次模型预测结果，结合市场规则给出风险预警、偏差考核与报价注意点。",
        "根据本次模型预测结果，结合市场规则给出风险预警与报价注意点。",
    ),
    (
        "根据本次负荷、风光出力与日前电价预测结果，结合市场规则给出风险预警、偏差考核与报价注意点。",
        "根据本次负荷、风光出力与日前电价预测结果，结合市场规则给出风险预警与报价注意点。",
    ),
    (
        "根据日前电价模型的评估指标和特征重要性，给出报价策略、套利窗口与风险对冲建议，并说明偏差考核风险。",
        "根据日前电价模型的评估指标和特征重要性，给出报价策略、套利窗口与风险对冲建议。",
    ),
    (
        "关注高峰小时电价是否异常偏高，结合新能源出力和负荷预测说明偏差考核风险。",
        "关注高峰小时电价是否异常偏高，结合新能源出力和负荷预测分析高峰时段的价格风险。",
    ),
    (
        "光伏出力训练：辐照、热浪和午间高峰如何影响 solar_mw？消纳受阻与偏差考核要注意什么？",
        "光伏出力训练：辐照、热浪和午间高峰如何影响 solar_mw？消纳受阻要注意什么？",
    ),
    (
        "风电出力训练：10米/100米风速、阵风和台风如何影响 wind_mw？切出风险与偏差考核要注意什么？",
        "风电出力训练：10米/100米风速、阵风和台风如何影响 wind_mw？切出风险要注意什么？",
    ),
    (
        "风光合计出力训练：新能源高发如何挤压残余负荷？消纳、反调峰与偏差考核要注意什么？",
        "风光合计出力训练：新能源高发如何挤压残余负荷？消纳与反调峰要注意什么？",
    ),
    (
        "用电负荷训练：气温、热浪和寒潮如何驱动 load_mw？晚高峰备电与偏差考核要注意什么？",
        "用电负荷训练：气温、热浪和寒潮如何驱动 load_mw？晚高峰备电要注意什么？",
    ),
    (
        "实时光伏出力训练：辐照、热浪和午间高峰如何影响 solar_mw？消纳受阻与偏差考核要注意什么？",
        "实时光伏出力训练：辐照、热浪和午间高峰如何影响 solar_mw？消纳受阻要注意什么？",
    ),
)
_LEGACY_QUESTION_MAP = dict(_LEGACY_QUESTION_FIXES)

# 问询可能被用户在界面上改过，精确匹配兜不住，这里再做一遍短语级清理。
# 只作用于 llm 节点的 question（一句话），不动 system_prompt。
_QUESTION_PHRASE_RULES = (
    ("、偏差考核与", "与"),
    ("，偏差考核与", "，"),
    ("与偏差考核与", "与"),
    ("、偏差考核", ""),
    ("与偏差考核", ""),
    ("，偏差考核", ""),
    ("，并说明偏差考核风险", ""),
    ("说明偏差考核风险", "分析价格风险"),
    ("偏差考核与合规注意", ""),
    ("合规注意", ""),
    ("偏差考核", ""),
)


def _fixed_question(text):
    """把种子遗留的问询换成现行版本；用户改过的问法只做短语清理。"""
    raw = (text or "").strip()
    if not raw:
        return None
    if raw in _LEGACY_QUESTION_MAP:
        return _LEGACY_QUESTION_MAP[raw]
    fixed = raw
    for bad, good in _QUESTION_PHRASE_RULES:
        fixed = fixed.replace(bad, good)
    fixed = re.sub(r"([、，])\1+", r"\1", fixed).strip()
    fixed = re.sub(r"[、，]{2,}", "，", fixed)
    return fixed if fixed != raw else None


def migrate_dag_llm_nodes():
    """启动时把历史流程里的 LLM 节点提示词升级为新版（幂等）。

    旧种子把同一套章节同时写在 prompt_id 模板和 system_prompt 里，运行时重复下发；
    这里统一成「只保留 system_prompt」，换成带占位符的新版文风，
    并清掉文案里的「偏差考核 / 合规注意」章节。
    只对命中默认文案的节点生效，用户自己改写过的提示词不动。
    """
    changed = 0
    rows = query("SELECT id, name, graph_json FROM if_graph WHERE status=1")
    for row in rows or []:
        graph = loads(row.get("graph_json"), default={}) or {}
        nodes = graph.get("nodes") or []
        hit = False
        for n in nodes:
            ntype = n.get("type")
            if ntype not in ("llm.report", "llm.risk"):
                continue
            cfg = n.setdefault("config", {})
            text = cfg.get("system_prompt") or ""
            if cfg.pop("prompt_id", None) is not None:
                hit = True
            if cfg.pop("system_prompt_id", None) is not None:
                hit = True
            target = _upgraded_default_prompt(text, ntype)
            if target:
                cfg["system_prompt"] = target
                hit = True
            new_q = _fixed_question(cfg.get("question"))
            if new_q:
                cfg["question"] = new_q
                hit = True
        if hit:
            update("if_graph", {"graph_json": dumps(graph)}, "id=%s", (row["id"],))
            changed += 1
    return changed


def _ensure_graph_nodes(dag, extra_nodes, extra_edges):
    """在已有画布上补齐缺失的系统节点，不覆盖用户改动。"""
    if not dag:
        return dag
    graph = dag.get("graph") or {}
    if not isinstance(graph, dict):
        return dag
    nodes = list(graph.get("nodes") or [])
    edges = list(graph.get("edges") or [])
    have_ids = {n.get("id") for n in nodes}
    have_edges = {(e.get("from"), e.get("to")) for e in edges}
    added = False
    for node in extra_nodes:
        if node.get("id") not in have_ids:
            nodes.append(node)
            added = True
    for edge in extra_edges:
        if (edge.get("from"), edge.get("to")) not in have_edges:
            edges.append(edge)
            added = True
    if not added:
        return dag
    graph["nodes"] = nodes
    graph["edges"] = edges
    return save_graph({
        "name": dag.get("name"),
        "scenario_code": dag.get("scenario_code"),
        "description": dag.get("description"),
        "is_template": dag.get("is_template"),
        "schedule_kind": dag.get("schedule_kind"),
        "schedule_enabled": dag.get("schedule_enabled"),
        "graph": graph,
        "username": dag.get("username") or "system",
    }, dag.get("id"))


def ensure_extreme_weather_dags():
    from services.extreme_weather_pipeline import (
        BUNDLE_NAME, JOB_LOAD, JOB_PRICE, JOB_RENEWABLE, JOB_SOLAR, JOB_WIND,
        LABEL_LOAD, LABEL_PRICE, LABEL_RENEWABLE, LABEL_SOLAR, LABEL_WIND,
        PROJECT_NAME, RULE_NAME, WEATHER_TABLE, WIDE_TABLE, _model_choice,
    )
    from services.weather_asset import WEATHER_RULE

    project = query("SELECT id FROM data_project WHERE name=%s AND status=1", (PROJECT_NAME,), one=True)
    pid = project["id"] if project else None
    weather_ds = None
    wide_ds = None
    bundle = None
    weather_rule = query("SELECT id FROM clean_rule WHERE name=%s AND status=1", (WEATHER_RULE,), one=True)
    ew_rule = query("SELECT id FROM clean_rule WHERE name=%s AND status=1", (RULE_NAME,), one=True)
    if pid:
        weather_ds = query(
            "SELECT id FROM dataset WHERE project_id=%s AND name=%s AND status=1 ORDER BY id DESC",
            (pid, WEATHER_TABLE),
            one=True,
        )
        wide_ds = query(
            "SELECT id FROM dataset WHERE project_id=%s AND name=%s AND status=1 ORDER BY id DESC",
            (pid, WIDE_TABLE),
            one=True,
        )
        bundle = query(
            "SELECT id FROM dataset_bundle WHERE project_id=%s AND name=%s AND status=1 ORDER BY id DESC",
            (pid, BUNDLE_NAME),
            one=True,
        )
    model_type, params = _model_choice()
    weather_cfg = {
        "dataset_id": weather_ds["id"] if weather_ds else None,
        "dataset_name": WEATHER_TABLE,
        "project_name": PROJECT_NAME,
    }
    wide_cfg = {
        "dataset_id": wide_ds["id"] if wide_ds else None,
        "dataset_name": WIDE_TABLE,
        "project_name": PROJECT_NAME,
    }
    bundle_cfg = {
        "bundle_id": bundle["id"] if bundle else None,
        "bundle_name": BUNDLE_NAME,
        "project_name": PROJECT_NAME,
    }
    rule_cfg = {
        "rule_id": weather_rule["id"] if weather_rule else None,
        "rule_name": WEATHER_RULE,
    }
    ew_rule_cfg = {
        "rule_id": (ew_rule or weather_rule or {}).get("id") if (ew_rule or weather_rule) else None,
        "rule_name": RULE_NAME if ew_rule else WEATHER_RULE,
    }

    def train_cfg(name, target):
        return {
            "name": name,
            "target_col": target,
            "model_type": model_type,
            "params": params,
            "task_type": "regression",
            "log_target": False,
            "sample_rows": 0,
        }

    def predict_node(nid, job_name, output_col, x, y, input_mode="upstream", feature_rows=None):
        return {
            "id": nid,
            "type": "model.predict",
            "x": x,
            "y": y,
            "config": {
                "job_name": job_name,
                "output_col": output_col,
                "input_mode": input_mode,
                "feature_rows": feature_rows or [],
                "override_rows": [],
            },
        }

    risk_cfg = {
        "question": DEFAULT_RISK_QUESTION,
        "system_prompt": DEFAULT_RISK_SYSTEM,
        "use_rag": True,
        "rag_top_k": 6,
    }
    report_cfg = {
        "question": DEFAULT_PRICE_QUESTION,
        "system_prompt": DEFAULT_PRICE_SYSTEM,
        "use_rag": True,
        "rag_top_k": 6,
    }

    def prompt_id(name):
        row = query("SELECT id FROM prompt_template WHERE name=%s AND status=1", (name,), one=True)
        return row["id"] if row else None

    def train_report_cfg(question, focus, qname):
        # 指令集中在 system_prompt（含占位符），不再同时挂 prompt_id，避免同一套章节被写两遍。
        cfg = {
            "question": question,
            "system_prompt": _train_system(focus),
            "use_rag": True,
            "rag_top_k": 6,
        }
        qid = prompt_id(qname)
        if qid:
            cfg["question_prompt_id"] = qid
        return cfg

    solar_report = train_report_cfg(
        "光伏出力训练：辐照、热浪和午间高峰如何影响 solar_mw？消纳受阻要注意什么？",
        "本轮目标是光伏出力 solar_mw，重点写辐照、热浪与午间高峰。",
        "光伏出力训练问询",
    )
    wind_report = train_report_cfg(
        "风电出力训练：10米/100米风速、阵风和台风如何影响 wind_mw？切出风险要注意什么？",
        "本轮目标是风电出力 wind_mw，重点写风速立方、切出与台风。",
        "风电出力训练问询",
    )
    renew_report = train_report_cfg(
        "风光合计出力训练：新能源高发如何挤压残余负荷？消纳与反调峰要注意什么？",
        "本轮目标是风光合计出力 renewable_mw，重点写新能源高发与残余负荷。",
        "风光出力训练问询",
    )
    load_report = train_report_cfg(
        "用电负荷训练：气温、热浪和寒潮如何驱动 load_mw？晚高峰备电要注意什么？",
        "本轮目标是用电负荷 load_mw，重点写气温、热浪/寒潮与晚高峰。",
        "用电负荷训练问询",
    )
    manual_price_features = [
        {"col": "year", "value": 2025},
        {"col": "month", "value": 7},
        {"col": "day", "value": 15},
        {"col": "hour", "value": 14},
        {"col": "weekday", "value": 1},
        {"col": "is_weekend", "value": 0},
        {"col": "temp_c", "value": 36.5},
        {"col": "humidity", "value": 58},
        {"col": "wind_speed", "value": 3.2},
        {"col": "ghi", "value": 780},
        {"col": "precip", "value": 0},
        {"col": "load_mw", "value": 9800},
        {"col": "wind_mw", "value": 420},
        {"col": "solar_mw", "value": 2100},
    ]
    shared_feature_rows = [
        {"col": "year", "value": 2025},
        {"col": "month", "value": 7},
        {"col": "day", "value": 15},
        {"col": "hour", "value": 14},
        {"col": "weekday", "value": 1},
        {"col": "site", "value": 1},
        {"col": "lat", "value": 31.23},
        {"col": "lon", "value": 121.47},
        {"col": "temp_c", "value": 36.5},
        {"col": "humidity", "value": 58},
        {"col": "precip_mm", "value": 0},
        {"col": "wind_10m", "value": 3.2},
        {"col": "wind_100m", "value": 5.8},
        {"col": "wind_gust", "value": 7.1},
        {"col": "radiation", "value": 780},
        {"col": "weather_code", "value": 1},
        {"col": "is_heat_wave", "value": 1},
        {"col": "is_cold_wave", "value": 0},
        {"col": "is_typhoon", "value": 0},
        {"col": "is_convection", "value": 0},
    ]

    specs = [
        {
            "seed_key": "extreme:qc_ts",
            "name": "极端天气-气象时序质控",
            "description": "气象与极端事件表 → 气象时序质控，按天定时物化清洗快照",
            "schedule_kind": "daily",
            "schedule_enabled": 1,
            "graph": {
                "nodes": [
                    {"id": "n1", "type": "asset.dataset", "x": 80, "y": 180, "config": weather_cfg},
                    {"id": "n2", "type": "clean.apply_rule", "x": 380, "y": 180, "config": rule_cfg},
                ],
                "edges": [{"from": "n1", "to": "n2"}],
            },
        },
        {
            "seed_key": "extreme:qc_wide",
            "name": "极端天气-负荷风光质控",
            "description": "气象 × 负荷 × 风光逻辑数据集 → 气象时序质控",
            "schedule_kind": "daily",
            "schedule_enabled": 1,
            "graph": {
                "nodes": [
                    {"id": "n1", "type": "asset.bundle", "x": 80, "y": 180, "config": bundle_cfg},
                    {"id": "n2", "type": "clean.apply_rule", "x": 380, "y": 180, "config": rule_cfg},
                ],
                "edges": [{"from": "n1", "to": "n2"}],
            },
        },
        {
            "seed_key": "extreme:train_load",
            "name": "极端天气-用电负荷训练编排",
            "description": "逻辑数据集 → 清洗 → 用电负荷模型训练 → LLM 模型洞察（气温/热浪驱动与高峰备电）",
            "schedule_kind": "daily",
            "schedule_enabled": 0,
            "graph": {
                "nodes": [
                    {"id": "n1", "type": "asset.bundle", "x": 60, "y": 180, "config": bundle_cfg},
                    {"id": "n2", "type": "clean.apply_rule", "x": 340, "y": 180, "config": ew_rule_cfg},
                    {"id": "n3", "type": "model.train", "x": 640, "y": 180, "config": train_cfg(JOB_LOAD, LABEL_LOAD)},
                    {"id": "n4", "type": "llm.report", "x": 940, "y": 180, "config": load_report},
                ],
                "edges": [
                    {"from": "n1", "to": "n2"},
                    {"from": "n2", "to": "n3"},
                    {"from": "n3", "to": "n4"},
                ],
            },
        },
        {
            "seed_key": "extreme:train_renewable",
            "name": "极端天气-风光出力训练编排",
            "description": "逻辑数据集 → 清洗 → 风光合计出力模型训练 → LLM 模型洞察（新能源高发与残余负荷）",
            "schedule_kind": "daily",
            "schedule_enabled": 0,
            "graph": {
                "nodes": [
                    {"id": "n1", "type": "asset.bundle", "x": 60, "y": 180, "config": bundle_cfg},
                    {"id": "n2", "type": "clean.apply_rule", "x": 340, "y": 180, "config": ew_rule_cfg},
                    {"id": "n3", "type": "model.train", "x": 640, "y": 180, "config": train_cfg(JOB_RENEWABLE, LABEL_RENEWABLE)},
                    {"id": "n4", "type": "llm.report", "x": 940, "y": 180, "config": renew_report},
                ],
                "edges": [
                    {"from": "n1", "to": "n2"},
                    {"from": "n2", "to": "n3"},
                    {"from": "n3", "to": "n4"},
                ],
            },
        },
        {
            "seed_key": "extreme:train_wind",
            "name": "极端天气-风电出力训练编排",
            "description": "逻辑数据集 → 清洗 → 风电出力训练 → LLM 模型洞察（风速/切出与台风情景）",
            "schedule_kind": "none",
            "schedule_enabled": 0,
            "graph": {
                "nodes": [
                    {"id": "n1", "type": "asset.bundle", "x": 60, "y": 180, "config": bundle_cfg},
                    {"id": "n2", "type": "clean.apply_rule", "x": 340, "y": 180, "config": ew_rule_cfg},
                    {"id": "n3", "type": "model.train", "x": 640, "y": 180, "config": train_cfg(JOB_WIND, LABEL_WIND)},
                    {"id": "n4", "type": "llm.report", "x": 940, "y": 180, "config": wind_report},
                ],
                "edges": [
                    {"from": "n1", "to": "n2"},
                    {"from": "n2", "to": "n3"},
                    {"from": "n3", "to": "n4"},
                ],
            },
        },
        {
            "seed_key": "extreme:train_solar",
            "name": "极端天气-光伏出力训练编排",
            "description": "逻辑数据集 → 清洗 → 光伏出力训练 → LLM 模型洞察（辐照/热浪与午间高峰）",
            "schedule_kind": "none",
            "schedule_enabled": 0,
            "graph": {
                "nodes": [
                    {"id": "n1", "type": "asset.bundle", "x": 60, "y": 180, "config": bundle_cfg},
                    {"id": "n2", "type": "clean.apply_rule", "x": 340, "y": 180, "config": ew_rule_cfg},
                    {"id": "n3", "type": "model.train", "x": 640, "y": 180, "config": train_cfg(JOB_SOLAR, LABEL_SOLAR)},
                    {"id": "n4", "type": "llm.report", "x": 940, "y": 180, "config": solar_report},
                ],
                "edges": [
                    {"from": "n1", "to": "n2"},
                    {"from": "n2", "to": "n3"},
                    {"from": "n3", "to": "n4"},
                ],
            },
        },
        {
            "seed_key": "price:train",
            "name": "日前电价训练编排",
            "description": "逻辑数据集 → 清洗 → 训练日前电价模型 → LLM 模型洞察（训练指标 / 特征重要性）",
            "schedule_kind": "none",
            "schedule_enabled": 0,
            "graph": {
                "nodes": [
                    {"id": "n1", "type": "asset.bundle", "x": 40, "y": 180, "config": bundle_cfg},
                    {"id": "n2", "type": "clean.apply_rule", "x": 320, "y": 180, "config": ew_rule_cfg},
                    {"id": "n3", "type": "model.train", "x": 620, "y": 180, "config": train_cfg(JOB_PRICE, LABEL_PRICE)},
                    {"id": "n4", "type": "llm.report", "x": 920, "y": 180, "config": report_cfg},
                ],
                "edges": [
                    {"from": "n1", "to": "n2"},
                    {"from": "n2", "to": "n3"},
                    {"from": "n3", "to": "n4"},
                ],
            },
        },
        {
            "seed_key": "price:predict",
            "name": "日前电价预测编排",
            "description": "数据表 → 清洗；共用特征值拉到四路手填预测 → 日前电价（以上游四路输出为特征）→ LLM 风险预警",
            "schedule_kind": "none",
            "schedule_enabled": 0,
            "graph": {
                "nodes": [
                    {"id": "n1", "type": "asset.dataset", "x": 40, "y": 180, "config": wide_cfg},
                    {"id": "n2", "type": "clean.apply_rule", "x": 280, "y": 180, "config": ew_rule_cfg},
                    {
                        "id": "n_share",
                        "type": "feat.shared",
                        "x": 280,
                        "y": 420,
                        "config": {"feature_rows": shared_feature_rows},
                    },
                    predict_node("p_solar", JOB_SOLAR, LABEL_SOLAR, 560, 40, "manual"),
                    predict_node("p_wind", JOB_WIND, LABEL_WIND, 560, 160, "manual"),
                    predict_node("p_renew", JOB_RENEWABLE, LABEL_RENEWABLE, 560, 280, "manual"),
                    predict_node("p_load", JOB_LOAD, LABEL_LOAD, 560, 400, "manual"),
                    predict_node("p_price", JOB_PRICE, LABEL_PRICE, 860, 220, "upstream"),
                    {"id": "n_risk", "type": "llm.risk", "x": 1160, "y": 220, "config": risk_cfg},
                ],
                "edges": [
                    {"from": "n1", "to": "n2"},
                    {"from": "n2", "to": "p_solar"},
                    {"from": "n2", "to": "p_wind"},
                    {"from": "n2", "to": "p_renew"},
                    {"from": "n2", "to": "p_load"},
                    {"from": "n_share", "to": "p_solar"},
                    {"from": "n_share", "to": "p_wind"},
                    {"from": "n_share", "to": "p_renew"},
                    {"from": "n_share", "to": "p_load"},
                    {"from": "p_solar", "to": "p_price"},
                    {"from": "p_wind", "to": "p_price"},
                    {"from": "p_renew", "to": "p_price"},
                    {"from": "p_load", "to": "p_price"},
                    {"from": "p_price", "to": "n_risk"},
                ],
            },
        },
        {
            "seed_key": "price:predict_manual",
            "name": "日前电价手填预测编排",
            "description": "单独模型预测：手填特征列 → 日前电价推理 → LLM 风险预警报告",
            "schedule_kind": "none",
            "schedule_enabled": 0,
            "graph": {
                "nodes": [
                    predict_node("n1", JOB_PRICE, LABEL_PRICE, 80, 180, "manual", manual_price_features),
                    {"id": "n2", "type": "llm.risk", "x": 420, "y": 180, "config": risk_cfg},
                ],
                "edges": [{"from": "n1", "to": "n2"}],
            },
        },
        {
            "seed_key": "price:predict_shared",
            "name": "日前电价共用特征手填编排",
            "description": "共用特征值 → 光伏/风电/风光/负荷手填预测 → 日前电价（以上游四路输出为特征）→ LLM 风险预警",
            "schedule_kind": "none",
            "schedule_enabled": 0,
            "graph": {
                "nodes": [
                    {
                        "id": "n_share",
                        "type": "feat.shared",
                        "x": 40,
                        "y": 220,
                        "config": {"feature_rows": shared_feature_rows},
                    },
                    predict_node("p_solar", JOB_SOLAR, LABEL_SOLAR, 360, 40, "manual"),
                    predict_node("p_wind", JOB_WIND, LABEL_WIND, 360, 160, "manual"),
                    predict_node("p_renew", JOB_RENEWABLE, LABEL_RENEWABLE, 360, 280, "manual"),
                    predict_node("p_load", JOB_LOAD, LABEL_LOAD, 360, 400, "manual"),
                    predict_node("p_price", JOB_PRICE, LABEL_PRICE, 680, 220, "upstream"),
                    {"id": "n_risk", "type": "llm.risk", "x": 980, "y": 220, "config": risk_cfg},
                ],
                "edges": [
                    {"from": "n_share", "to": "p_solar"},
                    {"from": "n_share", "to": "p_wind"},
                    {"from": "n_share", "to": "p_renew"},
                    {"from": "n_share", "to": "p_load"},
                    {"from": "p_solar", "to": "p_price"},
                    {"from": "p_wind", "to": "p_price"},
                    {"from": "p_renew", "to": "p_price"},
                    {"from": "p_load", "to": "p_price"},
                    {"from": "p_price", "to": "n_risk"},
                ],
            },
        },
    ]
    created = []
    for spec in specs:
        spec["scenario_code"] = "power_trading"
        spec["is_template"] = 1
        created.append(_upsert_named_graph(spec))
    return created


LIVE_DAG_NAME = "实时库表-光伏出力训练"
LIVE_JOB_NAME = "实时库表-光伏出力"


def ensure_live_mysql_dag(refresh_graph=False):
    """数据源接入 → 极端天气电力质控-实时 → 光伏出力训练。"""
    from services import live_ops
    from services.extreme_weather_pipeline import LIVE_RULE_NAME, ensure_live_rule, ensure_rule

    pack = live_ops.lookup_live_assets()
    if not pack.get("source") or not pack.get("dataset"):
        return None
    try:
        ensure_rule()
    except Exception:
        pass
    live_rule = None
    try:
        live_rule = ensure_live_rule()
    except Exception:
        live_rule = None
    rule = None
    if live_rule and live_rule.get("id"):
        rule = {"id": live_rule["id"], "name": live_rule.get("name") or LIVE_RULE_NAME}
    if not rule:
        rule = query("SELECT id, name FROM clean_rule WHERE name=%s AND status=1", (LIVE_RULE_NAME,), one=True)
    if not rule:
        rule = query("SELECT id, name FROM clean_rule WHERE name=%s AND status=1", ("极端天气电力质控",), one=True)
    if not rule:
        return None
    src = pack["source"]
    ds = pack["dataset"]
    spec = {
        "seed_key": "live:pv_train",
        "name": LIVE_DAG_NAME,
        "scenario_code": "power_trading",
        "description": "MySQL 活表 → 极端天气电力质控-实时 → 光伏出力训练 → LLM 模型洞察，运行时读当前库表",
        "schedule_kind": "none",
        "schedule_enabled": 0,
        "is_template": 0,
        "graph": {
            "nodes": [
                {
                    "id": "n1",
                    "type": "source.mysql",
                    "x": 60,
                    "y": 180,
                    "config": {
                        "source_id": src["id"],
                        "database": live_ops.LIVE_DB,
                        "table": live_ops.LIVE_TABLE,
                        "dataset_name": live_ops.DATASET_NAME,
                        "project_id": pack["project"]["id"] if pack.get("project") else None,
                    },
                },
                {
                    "id": "n2",
                    "type": "clean.apply_rule",
                    "x": 360,
                    "y": 180,
                    "config": {"rule_id": rule["id"], "rule_name": rule.get("name") or LIVE_RULE_NAME},
                },
                {
                    "id": "n3",
                    "type": "model.train",
                    "x": 680,
                    "y": 180,
                    "config": {
                        "name": LIVE_JOB_NAME,
                        "target_col": "solar_mw",
                        "feature_cols": [],
                        "model_type": "xgboost",
                        "task_type": "regression",
                        "sample_rows": 18000,
                        "test_size": 0.2,
                        "random_state": 42,
                        "log_target": False,
                        "params": {
                            "n_estimators": 80,
                            "max_depth": 6,
                            "learning_rate": 0.08,
                            "subsample": 0.85,
                            "colsample_bytree": 0.85,
                        },
                    },
                },
                {
                    "id": "n4",
                    "type": "llm.report",
                    "x": 1020,
                    "y": 180,
                    "config": {
                        "question": (
                            "实时光伏出力训练：辐照、热浪和午间高峰如何影响 solar_mw？"
                            "消纳受阻要注意什么？"
                        ),
                        "system_prompt": _train_system(
                            "本轮目标是光伏出力 solar_mw，重点写辐照、热浪与午间高峰；"
                            "数据来自实时库表，注意时段与天气突变。"
                        ),
                        "use_rag": True,
                        "rag_top_k": 6,
                    },
                },
            ],
            "edges": [
                {"from": "n1", "to": "n2"},
                {"from": "n2", "to": "n3"},
                {"from": "n3", "to": "n4"},
            ],
        },
    }
    dag = _upsert_named_graph(spec, refresh_graph=refresh_graph, overwrite_graph=refresh_graph)
    # 已有画布补齐「LLM 模型洞察」节点（不覆盖用户改动）
    return _ensure_graph_nodes(dag, [spec["graph"]["nodes"][-1]], [{"from": "n3", "to": "n4"}])
