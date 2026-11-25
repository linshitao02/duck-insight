# -*- coding: utf-8 -*-
import os
from datetime import datetime

from flask import g, request

from config import get_user_dir, to_abs, to_rel
from utils.db import delete, insert, query, update
from utils.io import excel_sheet_names, load_dataframe, read_table, save_dataframe
from utils.jsonx import dumps, loads, row_to_dict
from utils.joiner import apply_joins, resolve_selected_columns, suggest_joins
from utils.profiler import preview_records, profile_dataframe


def _user():
    return getattr(g, "user", {}) or {}


def serialize_dataset(row):
    data = row_to_dict(row)
    data["schema"] = loads(row.get("schema_json"), default=[])
    data["profile"] = loads(row.get("profile_json"), default={})
    data["roles"] = loads(row.get("role_json"), default={})
    data["origin_type"] = data.get("origin_type") or "file"
    data["is_live"] = data["origin_type"] == "mysql_live"
    return data


def is_live(ds):
    return bool(ds) and (ds.get("origin_type") == "mysql_live" or ds.get("is_live"))


def load_dataset_frame(ds, nrows=None):
    if is_live(ds):
        from services import source_service
        if not ds.get("source_id") or not ds.get("source_table"):
            raise ValueError("活表数据集缺少数据源或表名")
        return source_service.read_live_frame(
            ds.get("source_id"), ds.get("source_db"), ds.get("source_table"), nrows=nrows,
        )
    path = ds.get("file_path")
    if not path:
        raise ValueError("数据集还没有落地文件")
    return load_dataframe(to_abs(path), nrows=nrows)


def serialize_bundle(row):
    data = row_to_dict(row)
    data["dataset_ids"] = loads(row.get("dataset_ids_json"), default=[])
    data["joins"] = loads(row.get("joins_json"), default=[])
    data["schema"] = loads(row.get("schema_json"), default=[])
    data["selected_fields"] = loads(row.get("selected_fields_json"), default=[])
    return data


def list_datasets(keyword=None, scenario=None, project_id=None):
    sql = "SELECT * FROM dataset WHERE status=1"
    args = []
    user = _user()
    if user.get("role") != "admin":
        sql += " AND user_id=%s"
        args.append(user.get("id"))
    if project_id:
        sql += " AND project_id=%s"
        args.append(int(project_id))
    if scenario:
        sql += " AND scenario_code=%s"
        args.append(scenario)
    if keyword:
        sql += " AND (name LIKE %s OR filename LIKE %s)"
        args.extend([f"%{keyword}%", f"%{keyword}%"])
    sql += " ORDER BY id DESC"
    return [serialize_dataset(r) for r in query(sql, args)]


def get_dataset(ds_id):
    row = query("SELECT * FROM dataset WHERE id=%s", (ds_id,), one=True)
    return serialize_dataset(row) if row else None


def _profile_and_store(df, extra):
    profile = profile_dataframe(df)
    roles = {c["name"]: c["role"] for c in profile["columns"]}
    extra.update({
        "n_rows": int(len(df)),
        "n_cols": int(df.shape[1]),
        "schema_json": dumps([c["name"] for c in profile["columns"]]),
        "profile_json": dumps(profile),
        "role_json": dumps(roles),
    })
    return extra, profile


def save_upload(file_storage, name=None, scenario="store_sales", sheet_name=None, remark="", project_id=None):
    user = _user()
    if not project_id:
        raise ValueError("请先选择数据集配置后再上传数据表")
    filename = file_storage.filename
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    folder = get_user_dir(user.get("username") or "admin", "datasets")
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    raw_path = os.path.join(folder, f"{stamp}_{filename}")
    file_storage.save(raw_path)

    created = []
    if ext in ("xlsx", "xls"):
        sheets = excel_sheet_names(raw_path)
        targets = [sheet_name] if sheet_name else sheets or [0]
        for sh in targets:
            df = read_table(raw_path, filename=filename, sheet_name=sh)
            ds_name = name or f"{os.path.splitext(filename)[0]}_{sh}"
            parquet_path = os.path.join(folder, f"{stamp}_{sh}.csv")
            save_dataframe(df, parquet_path)
            payload = {
                "project_id": int(project_id),
                "name": ds_name if len(targets) == 1 else f"{ds_name}",
                "scenario_code": scenario,
                "filename": filename,
                "file_path": to_rel(parquet_path),
                "file_type": ext,
                "sheet_name": str(sh),
                "remark": remark,
                "user_id": user.get("id"),
                "username": user.get("username"),
                "status": 1,
            }
            payload, _ = _profile_and_store(df, payload)
            ds_id = insert("dataset", payload)
            created.append(get_dataset(ds_id))
        return created

    df = read_table(raw_path, filename=filename)
    persist = os.path.join(folder, f"{stamp}.csv")
    save_dataframe(df, persist)
    payload = {
        "project_id": int(project_id),
        "name": name or os.path.splitext(filename)[0],
        "scenario_code": scenario,
        "filename": filename,
        "file_path": to_rel(persist),
        "file_type": ext,
        "remark": remark,
        "user_id": user.get("id"),
        "username": user.get("username"),
        "status": 1,
    }
    payload, _ = _profile_and_store(df, payload)
    ds_id = insert("dataset", payload)
    return [get_dataset(ds_id)]


def upsert_dataframe(project_id, name, df, scenario="generic", remark="", filename=None, username="system"):
    """把内存表写入数据空间：同名则覆盖文件并重新画像。"""
    from config import get_user_dir, to_rel, to_abs
    if df is None or len(df) == 0:
        raise ValueError("没有可导入的数据")
    user = _user()
    uname = user.get("username") or username
    folder = get_user_dir(uname, "datasets")
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    persist = os.path.join(folder, f"{stamp}_{name}.csv")
    save_dataframe(df, persist)
    payload = {
        "project_id": int(project_id),
        "name": name,
        "scenario_code": scenario,
        "filename": filename or f"{name}.csv",
        "file_path": to_rel(persist),
        "file_type": "csv",
        "remark": remark,
        "user_id": user.get("id"),
        "username": uname,
        "status": 1,
    }
    payload, _ = _profile_and_store(df, payload)
    existing = query(
        "SELECT id, file_path FROM dataset WHERE project_id=%s AND name=%s AND status=1 ORDER BY id DESC",
        (int(project_id), name),
        one=True,
    )
    if existing:
        old = to_abs(existing.get("file_path"))
        update("dataset", payload, "id=%s", (existing["id"],))
        if old and os.path.exists(old) and old != persist:
            try:
                os.remove(old)
            except Exception:
                pass
        return get_dataset(existing["id"])
    ds_id = insert("dataset", payload)
    return get_dataset(ds_id)


def replace_upload(ds_id, file_storage, name=None, remark=None):
    """覆盖已有任务的数据文件，并重新画像。"""
    ds = get_dataset(ds_id)
    if not ds:
        raise ValueError("数据集不存在")
    user = _user()
    filename = file_storage.filename
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    folder = get_user_dir(user.get("username") or ds.get("username") or "admin", "datasets")
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    raw_path = os.path.join(folder, f"{stamp}_{filename}")
    file_storage.save(raw_path)
    df = read_table(raw_path, filename=filename, sheet_name=0 if ext in ("xlsx", "xls") else None)
    persist = os.path.join(folder, f"{stamp}_replace.csv")
    save_dataframe(df, persist)
    old_path = to_abs(ds.get("file_path"))
    payload = {
        "filename": filename,
        "file_path": to_rel(persist),
        "file_type": ext,
    }
    if name is not None and name != "":
        payload["name"] = name
    if remark is not None:
        payload["remark"] = remark
    payload, _ = _profile_and_store(df, payload)
    update("dataset", payload, "id=%s", (ds_id,))
    if old_path and os.path.exists(old_path) and old_path != persist:
        try:
            os.remove(old_path)
        except Exception:
            pass
    return get_dataset(ds_id)

def _preview_window(n=40, skip=0, cap=2000):
    try:
        n = int(n or 40)
    except (TypeError, ValueError):
        n = 40
    try:
        skip = int(skip or 0)
    except (TypeError, ValueError):
        skip = 0
    return max(1, min(n, cap)), max(0, skip)


def _to_float(value):
    if value is None or value == "":
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _apply_row_filters(df, filters):
    import pandas as pd

    if df is None or df.empty or not filters:
        return df
    mask = pd.Series(True, index=df.index)
    for item in filters:
        if not isinstance(item, dict):
            continue
        col = item.get("col")
        op = (item.get("op") or "contains").strip()
        val = item.get("value")
        val2 = item.get("value2")
        if not col or col not in df.columns:
            continue
        series = df[col]
        if op in ("gt", "gte", "lt", "lte", "between"):
            num = pd.to_numeric(series, errors="coerce")
            v1 = _to_float(val)
            if op == "between":
                v2 = _to_float(val2)
                lo, hi = (v1, v2) if v1 is not None and v2 is not None and v1 <= v2 else (v2, v1)
                if lo is None or hi is None:
                    continue
                mask &= num.between(lo, hi)
            elif v1 is None:
                continue
            elif op == "gt":
                mask &= num > v1
            elif op == "gte":
                mask &= num >= v1
            elif op == "lt":
                mask &= num < v1
            elif op == "lte":
                mask &= num <= v1
            continue
        text = series.astype(str)
        needle = "" if val is None else str(val)
        if op == "eq":
            mask &= text == needle
        elif op == "ne":
            mask &= text != needle
        elif op == "not_contains":
            mask &= ~text.str.contains(needle, case=False, na=False, regex=False)
        else:
            mask &= text.str.contains(needle, case=False, na=False, regex=False)
    return df[mask]


def _normalize_filters(filters):
    if not filters:
        return []
    if isinstance(filters, str):
        filters = loads(filters, default=[])
    if not isinstance(filters, list):
        return []
    out = []
    for item in filters:
        if not isinstance(item, dict) or not item.get("col"):
            continue
        op = (item.get("op") or "contains").strip()
        if op == "between" and item.get("value") in (None, "") and item.get("value2") in (None, ""):
            continue
        if op != "between" and item.get("value") in (None, "") and op not in ("eq", "ne"):
            continue
        out.append({
            "col": item.get("col"),
            "op": op,
            "value": item.get("value"),
            "value2": item.get("value2"),
        })
    return out


def _preview_table(path, n=40, skip=0, filters=None, fallback_n_rows=None):
    n, skip = _preview_window(n, skip)
    filters = _normalize_filters(filters)
    abs_path = to_abs(path)
    if filters:
        df = load_dataframe(abs_path)
        page = df.copy()
        page["__row_no"] = list(range(1, len(page) + 1))
        page = _apply_row_filters(page, filters)
        total = int(len(page))
        page = page.iloc[skip:skip + n]
    else:
        df = load_dataframe(abs_path, nrows=skip + n)
        page = df.iloc[skip:skip + n].copy()
        page["__row_no"] = list(range(skip + 1, skip + 1 + len(page)))
        total = int(fallback_n_rows or 0)
    row_nos = [int(v) for v in page["__row_no"].tolist()] if len(page) else []
    page = page.drop(columns=["__row_no"], errors="ignore")
    return page, list(page.columns), row_nos, total, bool(filters)


def _preview_live(ds, n=40, skip=0, filters=None):
    from services import source_service
    n, skip = _preview_window(n, skip)
    filters = _normalize_filters(filters)
    sid, db, table = ds.get("source_id"), ds.get("source_db"), ds.get("source_table")
    if filters:
        page = source_service.read_live_frame(sid, db, table, nrows=20000)
        page = page.copy()
        page["__row_no"] = list(range(1, len(page) + 1))
        page = _apply_row_filters(page, filters)
        total = int(len(page))
        page = page.iloc[skip:skip + n]
    else:
        total = source_service.count_table_rows(sid, db, table)
        page = source_service.read_live_frame(sid, db, table, nrows=n, skip=skip)
        page = page.copy()
        page["__row_no"] = list(range(skip + 1, skip + 1 + len(page)))
    row_nos = [int(v) for v in page["__row_no"].tolist()] if len(page) else []
    page = page.drop(columns=["__row_no"], errors="ignore")
    return page, list(page.columns), row_nos, total, bool(filters)


def preview_dataset(ds_id, n=40, skip=0, filters=None):
    from utils.field_labels import header_for_column
    ds = get_dataset(ds_id)
    if not ds:
        raise ValueError("数据集不存在")
    if is_live(ds):
        df, cols, row_nos, total, filtered = _preview_live(ds, n, skip, filters)
    else:
        df, cols, row_nos, total, filtered = _preview_table(
            ds["file_path"], n, skip, filters, ds.get("n_rows")
        )
    return {
        "dataset": ds,
        "columns": cols,
        "column_labels": {c: header_for_column(c, [ds], ds_id) for c in cols},
        "records": preview_records(df, len(df)),
        "n_rows": total if filtered else (total or ds.get("n_rows")),
        "imported": int(len(df)),
        "skip": skip if isinstance(skip, int) else 0,
        "row_nos": row_nos,
        "filtered": filtered,
    }


def update_roles(ds_id, roles):
    ds = get_dataset(ds_id)
    if not ds:
        raise ValueError("数据集不存在")
    update("dataset", {"role_json": dumps(roles)}, "id=%s", (ds_id,))
    return get_dataset(ds_id)


def update_dataset_meta(ds_id, payload):
    ds = get_dataset(ds_id)
    if not ds:
        raise ValueError("数据集不存在")
    data = {}
    if payload.get("name") is not None:
        data["name"] = payload["name"]
    if payload.get("remark") is not None:
        data["remark"] = payload["remark"]
    if data:
        update("dataset", data, "id=%s", (ds_id,))
    return get_dataset(ds_id)


def update_field_schema(ds_id, columns, meta=None):
    """保存用户对字段推断类型、角色、缺失策略、中文释义、是否参与建模的配置。"""
    from utils.field_labels import label_zh_for
    ds = get_dataset(ds_id)
    if not ds:
        raise ValueError("数据集不存在")
    profile = ds.get("profile") or {}
    old_cols = {c.get("name"): c for c in (profile.get("columns") or [])}
    new_cols = []
    roles = {}
    for item in columns or []:
        name = item.get("name")
        if not name:
            continue
        base = dict(old_cols.get(name) or {"name": name})
        if item.get("inferred") is not None:
            base["inferred"] = item["inferred"]
        if item.get("role") is not None:
            base["role"] = item["role"]
        if item.get("null_strategy") is not None:
            base["null_strategy"] = item["null_strategy"]
        if item.get("included") is not None:
            base["included"] = bool(item["included"])
        elif "included" not in base:
            # 默认：泄漏列不参与，其余参与
            base["included"] = base.get("role") != "leakage"
        if item.get("fill_value") is not None:
            base["fill_value"] = item["fill_value"]
        if "label_zh" in item:
            base["label_zh"] = str(item.get("label_zh") or "").strip()
        elif not str(base.get("label_zh") or "").strip():
            zh = label_zh_for(name)
            if zh:
                base["label_zh"] = zh
        roles[name] = base.get("role") or "feature"
        new_cols.append(base)
    # 保留未提交的旧列
    submitted = {c["name"] for c in new_cols}
    for name, col in old_cols.items():
        if name not in submitted:
            new_cols.append(col)
            roles[name] = col.get("role") or "feature"
    profile["columns"] = new_cols
    if meta:
        profile["meta"] = {**(profile.get("meta") or {}), **meta}
    update("dataset", {
        "profile_json": dumps(profile),
        "role_json": dumps(roles),
    }, "id=%s", (ds_id,))
    return get_dataset(ds_id)


def rebuild_bundle(bundle_id, name=None, dataset_ids=None, joins=None, fact_dataset_id=None, remark=None, selected_fields=None):
    """按新的关联配置重新物化逻辑数据集。"""
    user = _user()
    old = get_bundle(bundle_id)
    if not old:
        raise ValueError("逻辑数据集不存在")
    dataset_ids = [int(i) for i in (dataset_ids or old.get("dataset_ids") or [])]
    fact_dataset_id = int(fact_dataset_id or old.get("fact_dataset_id") or dataset_ids[0])
    joins = joins if joins is not None else (old.get("joins") or [])
    selected_fields = selected_fields if selected_fields is not None else (old.get("selected_fields") or [])
    frames, _ = load_frames(dataset_ids)
    merged = apply_joins(frames, fact_dataset_id, joins, required_ids=dataset_ids)
    keep = resolve_selected_columns(list(merged.columns), selected_fields)
    if keep:
        merged = merged[keep]
    folder = get_user_dir(user.get("username") or old.get("username") or "admin", "bundles")
    path = os.path.join(folder, f"bundle_{bundle_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv")
    save_dataframe(merged, path)
    old_path = to_abs(old.get("materialized_path"))
    update("dataset_bundle", {
        "name": name or old.get("name"),
        "fact_dataset_id": fact_dataset_id,
        "dataset_ids_json": dumps(dataset_ids),
        "joins_json": dumps(joins),
        "selected_fields_json": dumps(selected_fields or []),
        "materialized_path": to_rel(path),
        "n_rows": int(len(merged)),
        "n_cols": int(merged.shape[1]),
        "schema_json": dumps(list(merged.columns)),
        "remark": remark if remark is not None else old.get("remark"),
    }, "id=%s", (bundle_id,))
    if old_path and os.path.exists(old_path) and old_path != path:
        try:
            os.remove(old_path)
        except Exception:
            pass
    return get_bundle(bundle_id)


def update_meta(ds_id, payload):
    ds = get_dataset(ds_id)
    if not ds:
        raise ValueError("数据集不存在")
    data = {}
    if payload.get("name"):
        data["name"] = payload["name"]
    if "remark" in payload:
        data["remark"] = payload.get("remark") or ""
    if data:
        update("dataset", data, "id=%s", (ds_id,))
    return get_dataset(ds_id)


def fill_zh_labels(ds_id, overwrite=False):
    """为已有数据表补全默认中文释义，不覆盖用户手工填写（除非 overwrite）。"""
    from utils.field_labels import label_zh_for
    ds = get_dataset(ds_id)
    if not ds:
        raise ValueError("数据集不存在")
    profile = ds.get("profile") or {}
    changed = False
    for col in profile.get("columns") or []:
        existing = str(col.get("label_zh") or "").strip()
        if existing and not overwrite:
            continue
        zh = label_zh_for(col.get("name"))
        if zh and zh != existing:
            col["label_zh"] = zh
            changed = True
    if changed:
        update("dataset", {"profile_json": dumps(profile)}, "id=%s", (ds_id,))
    return get_dataset(ds_id)


def fill_zh_labels_for_project(project_id, overwrite=False):
    rows = query(
        "SELECT id FROM dataset WHERE project_id=%s AND status=1",
        (int(project_id),),
    )
    return [fill_zh_labels(r["id"], overwrite=overwrite) for r in rows]


def re_infer_fields(ds_id):
    """重新自动推断字段类型与角色（保留用户缺失策略可被覆盖为 auto）。"""
    ds = get_dataset(ds_id)
    if not ds:
        raise ValueError("数据集不存在")
    df = load_dataset_frame(ds, nrows=50000)
    payload = {"name": ds["name"]}
    payload, _ = _profile_and_store(df, payload)
    update(
        "dataset",
        {
            "schema_json": payload["schema_json"],
            "profile_json": payload["profile_json"],
            "role_json": payload["role_json"],
            "n_rows": payload["n_rows"],
            "n_cols": payload["n_cols"],
        },
        "id=%s",
        (ds_id,),
    )
    return get_dataset(ds_id)


def delete_dataset(ds_id):
    ds = get_dataset(ds_id)
    if not ds:
        return
    path = to_abs(ds.get("file_path"))
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass
    delete("dataset", "id=%s", (ds_id,))


def load_frames(dataset_ids, nrows=None):
    frames = {}
    metas = []
    for ds_id in dataset_ids:
        ds = get_dataset(ds_id)
        if not ds:
            continue
        df = load_dataset_frame(ds, nrows=nrows)
        frames[int(ds_id)] = df
        profile = ds.get("profile") or {}
        metas.append({
            "id": int(ds_id),
            "name": ds["name"],
            "columns": profile.get("columns") or [],
            "frame": df,
        })
    return frames, metas


def suggest_dataset_joins(dataset_ids):
    frames, metas = load_frames(dataset_ids, nrows=30000)
    return suggest_joins(metas)


def create_bundle(name, dataset_ids, joins, fact_dataset_id=None, scenario="store_sales", remark="", project_id=None, selected_fields=None):
    user = _user()
    if not project_id:
        raise ValueError("缺少数据集配置 project_id")
    dataset_ids = [int(i) for i in dataset_ids]
    fact_dataset_id = int(fact_dataset_id or dataset_ids[0])
    frames, _ = load_frames(dataset_ids)
    merged = apply_joins(frames, fact_dataset_id, joins, required_ids=dataset_ids)
    keep = resolve_selected_columns(list(merged.columns), selected_fields)
    if keep:
        merged = merged[keep]
    folder = get_user_dir(user.get("username") or "admin", "bundles")
    path = os.path.join(folder, f"bundle_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv")
    save_dataframe(merged, path)
    bundle_id = insert("dataset_bundle", {
        "project_id": int(project_id),
        "name": name,
        "scenario_code": scenario,
        "fact_dataset_id": fact_dataset_id,
        "dataset_ids_json": dumps(dataset_ids),
        "joins_json": dumps(joins),
        "selected_fields_json": dumps(selected_fields or []),
        "materialized_path": to_rel(path),
        "n_rows": int(len(merged)),
        "n_cols": int(merged.shape[1]),
        "schema_json": dumps(list(merged.columns)),
        "remark": remark,
        "user_id": user.get("id"),
        "username": user.get("username"),
        "status": 1,
    })
    return get_bundle(bundle_id)


def get_bundle(bundle_id):
    row = query("SELECT * FROM dataset_bundle WHERE id=%s", (bundle_id,), one=True)
    return serialize_bundle(row) if row else None


def list_bundles(keyword=None, scenario=None, project_id=None):
    sql = "SELECT * FROM dataset_bundle WHERE status=1"
    args = []
    user = _user()
    if user.get("role") != "admin":
        sql += " AND user_id=%s"
        args.append(user.get("id"))
    if project_id:
        sql += " AND project_id=%s"
        args.append(int(project_id))
    if scenario:
        sql += " AND scenario_code=%s"
        args.append(scenario)
    if keyword:
        sql += " AND name LIKE %s"
        args.append(f"%{keyword}%")
    sql += " ORDER BY id DESC"
    return [serialize_bundle(r) for r in query(sql, args)]


def delete_bundle(bundle_id):
    row = get_bundle(bundle_id)
    if not row:
        return
    path = to_abs(row.get("materialized_path"))
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass
    delete("dataset_bundle", "id=%s", (bundle_id,))


def preview_bundle(bundle_id, n=40, skip=0, filters=None):
    from utils.field_labels import header_for_column
    bundle = get_bundle(bundle_id)
    if not bundle:
        raise ValueError("逻辑数据集不存在")
    df, cols, row_nos, total, filtered = _preview_table(
        bundle["materialized_path"], n, skip, filters, bundle.get("n_rows")
    )
    datasets = [get_dataset(i) for i in (bundle.get("dataset_ids") or [])]
    datasets = [d for d in datasets if d]
    fact_id = bundle.get("fact_dataset_id")
    n, skip = _preview_window(n, skip)
    return {
        "bundle": bundle,
        "columns": cols,
        "column_labels": {c: header_for_column(c, datasets, fact_id) for c in cols},
        "records": preview_records(df, len(df)),
        "n_rows": total if filtered else bundle.get("n_rows"),
        "imported": int(len(df)),
        "skip": skip,
        "row_nos": row_nos,
        "filtered": filtered,
    }


def import_rossmann_demo(max_rows=80000, scenario="store_sales", project_id=None):
    from config import DEMO_ROSSMANN_CANDIDATES
    if not project_id:
        raise ValueError("请先选择数据集配置")
    data_dir = None
    for cand in DEMO_ROSSMANN_CANDIDATES:
        if cand and os.path.isdir(cand) and os.path.exists(os.path.join(cand, "store.csv")):
            data_dir = cand
            break
    if not data_dir:
        raise FileNotFoundError("未找到 Rossmann 示例数据目录")

    user = _user()
    folder = get_user_dir(user.get("username") or "admin", "datasets")
    created = []
    mapping = {}
    files = [
        ("store.csv", "门店维度", None),
        ("train.csv", "门店日销量", max_rows),
    ]
    for fname, name, nrows in files:
        src = os.path.join(data_dir, fname)
        if not os.path.exists(src):
            continue
        df = read_table(src, filename=fname, nrows=nrows)
        persist = os.path.join(folder, f"demo_{name}_{datetime.now().strftime('%H%M%S')}.csv")
        save_dataframe(df, persist)
        payload = {
            "project_id": int(project_id),
            "name": name,
            "scenario_code": scenario,
            "filename": fname,
            "file_path": to_rel(persist),
            "file_type": "csv",
            "remark": "Rossmann 示例数据",
            "user_id": user.get("id"),
            "username": user.get("username"),
            "status": 1,
        }
        payload, _ = _profile_and_store(df, payload)
        ds_id = insert("dataset", payload)
        mapping[name] = ds_id
        created.append(get_dataset(ds_id))

    bundle = None
    if "门店日销量" in mapping and "门店维度" in mapping:
        bundle = create_bundle(
            name="销量事实 × 门店维度",
            dataset_ids=[mapping["门店日销量"], mapping["门店维度"]],
            joins=[{
                "left_dataset_id": mapping["门店日销量"],
                "right_dataset_id": mapping["门店维度"],
                "left_key": "Store",
                "right_key": "Store",
                "how": "left",
                "score": 1,
                "reasons": ["示例数据标准关联键 Store"],
            }],
            fact_dataset_id=mapping["门店日销量"],
            scenario=scenario,
            remark="一键导入自动编织",
            project_id=int(project_id),
        )
    return {"datasets": created, "bundle": bundle}


def load_source_frame(target_type, target_id, nrows=None):
    if target_type == "bundle":
        bundle = get_bundle(target_id)
        if not bundle:
            raise ValueError("逻辑数据集不存在")
        return load_dataframe(to_abs(bundle["materialized_path"]), nrows=nrows), bundle
    ds = get_dataset(target_id)
    if not ds:
        raise ValueError("数据集不存在")
    return load_dataset_frame(ds, nrows=nrows), ds
