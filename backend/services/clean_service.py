# -*- coding: utf-8 -*-
import os
import re
from datetime import datetime

from flask import g

from config import get_user_dir, to_abs, to_rel
from services import dataset_service as ds_svc
from utils.cleaner import CATEGORY_LABELS, CleanEngine, OPS, discover_tokens
from utils.db import delete, insert, query, update
from utils.io import save_dataframe
from utils.jsonx import dumps, loads, row_to_dict
from utils.profiler import preview_records, profile_dataframe


def parse_steps_payload(raw):
    data = loads(raw, default=[]) if not isinstance(raw, (list, dict)) else raw
    if isinstance(data, dict):
        steps = data.get("steps") or []
        edges = data["edges"] if "edges" in data else None
        source = data.get("source") if isinstance(data.get("source"), dict) else {}
        return steps, edges, source
    return data or [], None, {}


def _as_int(value):
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_source(raw):
    if not isinstance(raw, dict):
        return {}
    project_id = _as_int(raw.get("project_id"))
    target_id = _as_int(raw.get("target_id"))
    if not project_id and not target_id:
        return {}
    target_type = (raw.get("target_type") or "dataset").strip() or "dataset"
    if target_type not in ("dataset", "bundle"):
        target_type = "dataset"
    return {
        "project_id": project_id,
        "target_type": target_type,
        "target_id": target_id,
    }


def ordered_steps(steps, edges=None):
    steps = [s for s in (steps or []) if isinstance(s, dict) and s.get("op") and not str(s.get("op")).startswith("_")]
    if not steps:
        return []
    if not edges:
        return steps
    by_id = {s["id"]: s for s in steps if s.get("id")}
    if not by_id:
        return steps
    outs = {i: [] for i in by_id}
    indeg = {i: 0 for i in by_id}
    used = set()
    for e in edges:
        a, b = (e or {}).get("from"), (e or {}).get("to")
        if a in by_id and b in by_id:
            outs[a].append(b)
            indeg[b] += 1
            used.add(a)
            used.add(b)
    if not used:
        return steps
    q = [i for i in by_id if indeg[i] == 0]
    order = []
    while q:
        cur = q.pop(0)
        order.append(cur)
        for nxt in outs[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                q.append(nxt)
    for i in by_id:
        if i not in order:
            order.append(i)
    return [by_id[i] for i in order if i in used]


def serialize_rule(row):
    data = row_to_dict(row)
    steps, edges, source = parse_steps_payload(row.get("steps_json"))
    data["steps"] = [s for s in steps if isinstance(s, dict) and s.get("op") and not str(s.get("op")).startswith("_")]
    data["edges"] = edges
    data["source"] = normalize_source(source)
    return data


def list_ops():
    return {"ops": OPS, "categories": CATEGORY_LABELS}


def get_source_schema(target_type, target_id):
    """返回数据源字段列表，供规则编辑页勾选。"""
    from utils.field_labels import label_zh_for

    def with_zh(name, fallback=""):
        text = str(fallback or "").strip()
        return text or label_zh_for(name)

    if target_type == "bundle":
        bundle = ds_svc.get_bundle(target_id)
        if not bundle:
            raise ValueError("逻辑数据集不存在")
        cols = bundle.get("schema") or []
        if not cols and bundle.get("materialized_path"):
            df, _ = ds_svc.load_source_frame(target_type, target_id, nrows=5)
            cols = list(df.columns)
        zh_map = {}
        for ds_id in bundle.get("dataset_ids") or []:
            ds = ds_svc.get_dataset(ds_id)
            if not ds:
                continue
            for item in ds.get("schema") or []:
                if isinstance(item, dict) and item.get("name") and str(item.get("label_zh") or "").strip():
                    zh_map[item["name"]] = str(item["label_zh"]).strip()
        columns = []
        for c in cols:
            name = c if isinstance(c, str) else (c or {}).get("name")
            if not name:
                continue
            base = name.split("__")[0]
            columns.append({
                "name": name,
                "inferred": "unknown",
                "role": "feature",
                "label_zh": with_zh(name, zh_map.get(name) or zh_map.get(base)),
            })
        return {
            "target_type": "bundle",
            "target_id": int(target_id),
            "name": bundle.get("name"),
            "project_id": bundle.get("project_id"),
            "columns": columns,
        }
    ds = ds_svc.get_dataset(target_id)
    if not ds:
        raise ValueError("数据集不存在")
    schema_zh = {}
    for item in ds.get("schema") or []:
        if isinstance(item, dict) and item.get("name"):
            schema_zh[item["name"]] = str(item.get("label_zh") or "").strip()
    profile_cols = (ds.get("profile") or {}).get("columns") or []
    if profile_cols:
        columns = [
            {
                "name": c.get("name"),
                "inferred": c.get("inferred") or "unknown",
                "role": c.get("role") or "feature",
                "null_ratio": c.get("null_ratio"),
                "label_zh": with_zh(c.get("name"), schema_zh.get(c.get("name"))),
            }
            for c in profile_cols if c.get("name")
        ]
    else:
        columns = []
        for c in ds.get("schema") or []:
            name = c if isinstance(c, str) else (c or {}).get("name")
            if not name:
                continue
            columns.append({
                "name": name,
                "inferred": "unknown",
                "role": "feature",
                "label_zh": with_zh(name, schema_zh.get(name)),
            })
    return {
        "target_type": "dataset",
        "target_id": int(target_id),
        "name": ds.get("name"),
        "project_id": ds.get("project_id"),
        "columns": columns,
    }


def list_rules(keyword=None, scenario=None):
    sql = "SELECT * FROM clean_rule WHERE status=1"
    args = []
    if scenario:
        sql += " AND (scenario_code=%s OR scenario_code='generic')"
        args.append(scenario)
    if keyword:
        sql += " AND name LIKE %s"
        args.append(f"%{keyword}%")
    sql += " ORDER BY is_preset DESC, id DESC"
    return [serialize_rule(r) for r in query(sql, args)]


def get_rule(rule_id):
    row = query("SELECT * FROM clean_rule WHERE id=%s", (rule_id,), one=True)
    return serialize_rule(row) if row else None


def save_rule(payload, rule_id=None):
    user = getattr(g, "user", {}) or {}
    existing = get_rule(rule_id) or {} if rule_id else {}
    source = payload.get("source")
    if source is None:
        source = existing.get("source") or {}
    data = {
        "name": payload.get("name"),
        "scenario_code": payload.get("scenario_code") or "store_sales",
        "description": payload.get("description") or "",
        "steps_json": dumps({
            "steps": payload.get("steps") or [],
            "edges": payload.get("edges") if payload.get("edges") is not None else [],
            "source": normalize_source(source),
        }),
        "user_id": user.get("id"),
        "username": user.get("username"),
        "status": payload.get("status", 1),
        "is_preset": payload.get("is_preset", 0),
    }
    if rule_id:
        if "is_preset" not in payload:
            data["is_preset"] = existing.get("is_preset") or 0
        update("clean_rule", data, "id=%s", (rule_id,))
        return get_rule(rule_id)
    return get_rule(insert("clean_rule", data))


def _unique_rule_name(name):
    base = (name or "清洗规则").strip() or "清洗规则"
    if not query("SELECT id FROM clean_rule WHERE name=%s AND status=1", (base,), one=True):
        return base
    i = 2
    while query("SELECT id FROM clean_rule WHERE name=%s AND status=1", (f"{base}{i}",), one=True):
        i += 1
    return f"{base}{i}"


def copy_rule(rule_id, name=None):
    rule = get_rule(rule_id)
    if not rule:
        raise ValueError("规则不存在")
    requested = (name or "").strip()
    new_name = requested or f"{(rule.get('name') or '清洗规则').strip()}-副本"
    new_name = _unique_rule_name(new_name)
    return save_rule({
        "name": new_name,
        "description": rule.get("description") or "",
        "scenario_code": rule.get("scenario_code") or "store_sales",
        "steps": rule.get("steps") or [],
        "edges": rule.get("edges") if rule.get("edges") is not None else [],
        "source": rule.get("source") or {},
        "is_preset": 0,
    })


def delete_rule(rule_id):
    rule = get_rule(rule_id)
    if rule and rule.get("is_preset"):
        raise ValueError("系统预设规则不可删除")
    delete("clean_rule", "id=%s", (rule_id,))


def probe_tokens(target_type, target_id, column, steps=None, max_tokens=40):
    if not column:
        raise ValueError("请选择要探查的文本列")
    df, _ = ds_svc.load_source_frame(target_type, target_id, nrows=8000)
    if steps:
        engine = CleanEngine()
        df = engine.fit_transform(df, steps)
    if column not in df.columns:
        raise ValueError(f"列不存在: {column}")
    series = df[column]
    tokens = discover_tokens(series, max_tokens=max_tokens)
    samples = [str(x) for x in series.dropna().astype(str).unique()[:8]]
    return {
        "column": column,
        "tokens": tokens,
        "n_unique": int(series.nunique(dropna=True)),
        "n_null": int(series.isna().sum()),
        "n_rows": int(len(series)),
        "samples": samples,
    }


def preview_clean(target_type, target_id, steps, n=40):
    df, meta = ds_svc.load_source_frame(target_type, target_id, nrows=8000)
    engine = CleanEngine()
    cleaned = engine.fit_transform(df, steps)
    return {
        "before": {"n_rows": int(len(df)), "n_cols": int(df.shape[1]), "records": preview_records(df, n)},
        "after": {"n_rows": int(len(cleaned)), "n_cols": int(cleaned.shape[1]),
                  "columns": list(cleaned.columns), "records": preview_records(cleaned, n)},
        "logs": engine.logs,
    }


def serialize_binding(row):
    data = row_to_dict(row)
    data["schema"] = loads(row.get("schema_json"), default=[])
    rule = get_rule(row.get("rule_id"))
    data["rule"] = rule
    data["rule_name"] = (rule or {}).get("name")
    data["has_snapshot"] = False
    data["snapshot_size"] = 0
    path = to_abs(row.get("snapshot_path")) if row.get("snapshot_path") else None
    if path and os.path.exists(path):
        data["has_snapshot"] = True
        try:
            data["snapshot_size"] = int(os.path.getsize(path))
        except OSError:
            data["snapshot_size"] = 0
    engine_abs = to_abs(row.get("engine_path")) if row.get("engine_path") else None
    data["has_engine"] = bool(engine_abs and os.path.exists(engine_abs))
    # 流程内临时产物：没落盘 CSV，但留下了清洗引擎状态，可按需现场重算。
    data["is_transient"] = not data["has_snapshot"]
    data["can_rebuild"] = bool(data["is_transient"] and data["has_engine"] and row.get("rule_id"))
    data["can_view"] = bool(data["has_snapshot"] or data["can_rebuild"])
    return data


def _binding_usage():
    """哪些训练任务 / BI 看板正在用这些快照（各一次查询，避免逐行查库）。"""
    train = {}
    for r in query("SELECT id, name, binding_id FROM train_job WHERE binding_id IS NOT NULL"):
        train.setdefault(int(r["binding_id"]), []).append({"id": r["id"], "name": r["name"]})
    board = {}
    for r in query("SELECT id, name, binding_id FROM bi_board WHERE binding_id IS NOT NULL"):
        board.setdefault(int(r["binding_id"]), []).append({"id": r["id"], "name": r["name"]})
    return train, board


def _source_names(target_type, ids):
    """把 target_id 批量换成数据集 / 逻辑数据集的名字。"""
    ids = [int(i) for i in ids if i]
    if not ids:
        return {}
    table = "dataset_bundle" if target_type == "bundle" else "dataset"
    marks = ",".join(["%s"] * len(ids))
    rows = query(f"SELECT id, name FROM {table} WHERE id IN ({marks})", ids)
    return {int(r["id"]): r["name"] for r in rows}


def list_bindings(target_type=None, target_id=None, include_transient=False):
    """列出清洗快照。默认只返回物化过的快照，隐藏流程内临时产物。

    DAG 的 clean.apply_rule 节点每跑一次都会建一条 persist=False 的绑定，
    它们没有 CSV、只是流程中间件，会把列表淹掉，所以默认过滤掉；
    需要排查时用 include_transient=True 打开。
    """
    sql = "SELECT * FROM dataset_binding WHERE 1=1"
    args = []
    if target_type:
        sql += " AND target_type=%s"
        args.append(target_type)
    if target_id:
        sql += " AND target_id=%s"
        args.append(target_id)
    sql += " ORDER BY id DESC"
    rows = query(sql, args)
    train_refs, board_refs = _binding_usage()
    names = {}
    for ttype in {r.get("target_type") for r in rows}:
        names[ttype] = _source_names(ttype, [r.get("target_id") for r in rows if r.get("target_type") == ttype])
    out = []
    for r in rows:
        data = serialize_binding(r)
        if data["is_transient"] and not include_transient:
            continue
        data["source_name"] = names.get(r.get("target_type"), {}).get(int(r.get("target_id") or 0))
        used_by = (train_refs.get(int(r["id"]), []) + board_refs.get(int(r["id"]), []))
        data["used_by"] = used_by
        data["used_count"] = len(used_by)
        out.append(data)
    return out


def get_binding(binding_id):
    row = query("SELECT * FROM dataset_binding WHERE id=%s", (binding_id,), one=True)
    if not row:
        return None
    data = serialize_binding(row)
    data["source_name"] = _source_names(row.get("target_type"), [row.get("target_id")]).get(int(row.get("target_id") or 0))
    train_refs, board_refs = _binding_usage()
    data["used_by"] = train_refs.get(int(row["id"]), []) + board_refs.get(int(row["id"]), [])
    data["used_count"] = len(data["used_by"])
    return data


def _rebuild_frame(binding):
    """没有物化快照时，按 engine_path 冻结的清洗状态现场重放一遍。

    DAG 里的 clean.apply_rule 节点以 persist=False 运行，只留引擎状态、不落 CSV，
    所以这类绑定既不能直接预览也不能下载。这里用同一套规则重放到源数据上，
    结果与当初物化的快照一致（前提是源数据没有变过）。
    """
    engine_path = binding.get("engine_path")
    if not engine_path:
        return None
    abs_engine = to_abs(engine_path)
    if not abs_engine or not os.path.exists(abs_engine):
        return None
    rule = binding.get("rule") or {}
    steps = ordered_steps(rule.get("steps") or [], rule.get("edges"))
    if not steps:
        return None
    df, _ = ds_svc.load_source_frame(binding.get("target_type"), binding.get("target_id"))
    engine = CleanEngine()
    try:
        import joblib
        engine.load_state(joblib.load(abs_engine))
    except Exception:
        # 引擎状态读不出来就用同一套规则重新拟合，结果等价
        engine = CleanEngine()
    return engine.fit_transform(df, steps)


def preview_binding(binding_id, n=50, skip=0):
    """预览快照：优先读物化 CSV，没有就按清洗状态现场重算。"""
    binding = get_binding(binding_id)
    if not binding:
        raise ValueError("清洗快照不存在")
    n = max(1, int(n or 50))
    skip = max(0, int(skip or 0))
    rebuilt = False
    if binding.get("has_snapshot"):
        page, cols, row_nos, total, _ = ds_svc._preview_table(
            binding.get("snapshot_path"), n, skip, None, binding.get("n_rows")
        )
    else:
        df = _rebuild_frame(binding)
        if df is None:
            raise ValueError("这条绑定既没有快照文件，也没有可用的清洗状态，无法预览")
        rebuilt = True
        total = int(len(df))
        page = df.iloc[skip:skip + n]
        cols = list(df.columns)
        row_nos = list(range(skip + 1, skip + 1 + len(page)))
    return {
        "binding": binding,
        "columns": cols,
        "records": preview_records(page, len(page)),
        "n_rows": int(total or binding.get("n_rows") or len(page)),
        "skip": skip,
        "row_nos": row_nos,
        "rebuilt": rebuilt,
    }


def binding_download(binding_id):
    """返回 (绝对路径, 下载文件名)；没有物化快照时现场重算并落一个临时 CSV。"""
    binding = get_binding(binding_id)
    if not binding:
        raise ValueError("清洗快照不存在")
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", str(binding.get("name") or f"binding_{binding_id}"))
    if binding.get("has_snapshot"):
        path = to_abs(binding.get("snapshot_path"))
        if not os.path.exists(path):
            raise ValueError("快照文件已丢失，无法下载")
        return path, f"{safe}_{binding_id}.csv"
    df = _rebuild_frame(binding)
    if df is None:
        raise ValueError("这条绑定既没有快照文件，也没有可用的清洗状态，无法下载")
    folder = get_user_dir(binding.get("username") or "admin", "snapshots")
    path = os_path(folder, f"bind_{binding_id}_regen.csv")
    save_dataframe(df, path)
    return path, f"{safe}_{binding_id}.csv"


def bind_and_materialize(target_type, target_id, rule_id, name=None, nrows=None, persist=True):
    user = getattr(g, "user", {}) or {}
    rule = get_rule(rule_id)
    if not rule:
        raise ValueError("清洗规则不存在")
    df, meta = ds_svc.load_source_frame(target_type, target_id, nrows=nrows)
    engine = CleanEngine()
    steps = ordered_steps(rule.get("steps") or [], rule.get("edges"))
    cleaned = engine.fit_transform(df, steps)
    folder = get_user_dir(user.get("username") or "admin", "snapshots")
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    import joblib
    engine_abs = os_path(folder, f"bind_{stamp}_engine.pkl")
    joblib.dump(engine.state(), engine_abs)
    snapshot_path = None
    if persist:
        path = os_path(folder, f"bind_{stamp}.csv")
        save_dataframe(cleaned, path)
        snapshot_path = to_rel(path)
    profile = profile_dataframe(cleaned.head(5000))
    extra = {}
    try:
        extra["engine_path"] = to_rel(engine_abs)
    except Exception:
        extra["engine_path"] = engine_abs
    payload = {
        "target_type": target_type,
        "target_id": target_id,
        "rule_id": rule_id,
        "name": name or f"{meta.get('name')}-{rule.get('name')}",
        "snapshot_path": snapshot_path,
        "n_rows": int(len(cleaned)),
        "n_cols": int(cleaned.shape[1]),
        "schema_json": dumps(list(cleaned.columns)),
        "status": "ready",
        "message": " | ".join(engine.logs[-6:]),
        "user_id": user.get("id"),
        "username": user.get("username"),
        "engine_path": extra.get("engine_path"),
    }
    try:
        binding_id = insert("dataset_binding", payload)
    except Exception:
        payload.pop("engine_path", None)
        binding_id = insert("dataset_binding", payload)
    row = get_binding(binding_id)
    if row is not None:
        row["_engine"] = engine
        row["_steps"] = steps
        row["_raw"] = df
        row["_cleaned"] = cleaned
    return row


def os_path(folder, name):
    import os
    return os.path.join(folder, name)


def delete_binding(binding_id, force=False):
    """删除快照绑定（连快照文件与清洗引擎状态一起删）。

    被训练任务 / BI 看板引用时默认拒绝，需要 force=True 二次确认后再删。
    """
    row = get_binding(binding_id)
    if not row:
        return
    used = row.get("used_by") or []
    if used and not force:
        names = "、".join(str(u.get("name") or f"#{u.get('id')}") for u in used[:3])
        more = f" 等 {len(used)} 处" if len(used) > 3 else ""
        raise ValueError(f"该快照正被「{names}」{more}引用，删除后这些训练/看板可能读不到数据。确认要删请勾选强制删除。")
    for key in ("snapshot_path", "engine_path"):
        path = to_abs(row.get(key))
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
    delete("dataset_binding", "id=%s", (binding_id,))
