# -*- coding: utf-8 -*-
from decimal import Decimal

import pandas as pd
import pymysql
from flask import g
from pymysql.cursors import DictCursor

from config import DB_CONFIG
from services.dataset_service import upsert_dataframe
from utils.db import insert, query, update
from utils.jsonx import loads, row_to_dict

SKIP_SCHEMAS = {"information_schema", "performance_schema", "mysql", "sys"}
MAX_IMPORT_ROWS = 200000
ENGINE_PORTS = {"mysql": 3306, "mariadb": 3306}


def _user():
    try:
        return getattr(g, "user", {}) or {}
    except RuntimeError:
        return {}


def _ident(name):
    if not name or not isinstance(name, str):
        raise ValueError("缺少库名或表名")
    if "`" in name or "\x00" in name:
        raise ValueError(f"非法标识符: {name}")
    return f"`{name}`"


def serialize_source(row, with_secret=False):
    data = row_to_dict(row)
    data["username"] = row.get("db_user") or ""
    data["database_name"] = row.get("database_name") or ""
    data["has_password"] = bool(row.get("db_password"))
    data["extra"] = loads(row.get("extra_json"), default={})
    if not with_secret:
        data.pop("db_password", None)
        data.pop("password", None)
    else:
        data["password"] = row.get("db_password") or ""
    data.pop("db_user", None)
    return data


def list_sources():
    sql = "SELECT * FROM data_source WHERE status=1"
    args = []
    user = _user()
    if user.get("role") != "admin":
        sql += " AND (user_id=%s OR username=%s OR username='system')"
        args.extend([user.get("id"), user.get("username")])
    sql += " ORDER BY id DESC"
    return [serialize_source(r) for r in query(sql, args)]


def get_source(sid, with_secret=False):
    row = query("SELECT * FROM data_source WHERE id=%s AND status=1", (sid,), one=True)
    return serialize_source(row, with_secret=with_secret) if row else None


def _payload_from_body(body, existing=None):
    existing = existing or {}
    engine = (body.get("engine") or existing.get("engine") or "mysql").lower().strip()
    if engine not in ("mysql", "mariadb"):
        raise ValueError("目前仅支持 MySQL / MariaDB")
    name = (body.get("name") or existing.get("name") or "").strip()
    if not name:
        raise ValueError("请填写数据源名称")
    host = (body.get("host") or existing.get("host") or "").strip()
    if not host:
        raise ValueError("请填写主机地址")
    port = body.get("port")
    if port in (None, ""):
        port = existing.get("port") or ENGINE_PORTS.get(engine, 3306)
    password = body.get("password")
    if password in (None, ""):
        password = existing.get("password") or existing.get("db_password")
    user = _user()
    return {
        "name": name,
        "engine": engine,
        "host": host,
        "port": int(port),
        "db_user": (body.get("username") if body.get("username") is not None else existing.get("username") or "root"),
        "db_password": password or "",
        "database_name": (body.get("database_name") if body.get("database_name") is not None else existing.get("database_name") or "") or "",
        "remark": body.get("remark") if body.get("remark") is not None else existing.get("remark") or "",
        "user_id": user.get("id") or existing.get("user_id"),
        "username": user.get("username") or existing.get("username"),
        "status": 1,
    }


def save_source(body, sid=None):
    existing = get_source(sid, with_secret=True) if sid else None
    if sid and not existing:
        raise ValueError("数据源不存在")
    payload = _payload_from_body(body or {}, existing)
    if sid:
        update("data_source", payload, "id=%s", (sid,))
        return get_source(sid)
    new_id = insert("data_source", payload)
    return get_source(new_id)


def delete_source(sid):
    update("data_source", {"status": 0}, "id=%s", (sid,))
    return True


def _connect_kwargs(cfg, database=None):
    kwargs = {
        "host": cfg.get("host") or "127.0.0.1",
        "user": cfg.get("username") or cfg.get("db_user") or "root",
        "password": cfg.get("password") or cfg.get("db_password") or "",
        "port": int(cfg.get("port") or 3306),
        "charset": cfg.get("charset") or "utf8mb4",
        "cursorclass": DictCursor,
        "connect_timeout": 8,
        "read_timeout": 180,
        "write_timeout": 60,
    }
    db = database if database is not None else (cfg.get("database_name") or None)
    if db:
        kwargs["database"] = db
    return kwargs


def _open(cfg, database=None):
    try:
        return pymysql.connect(**_connect_kwargs(cfg, database=database))
    except pymysql.err.OperationalError as e:
        raise ValueError(f"无法连接数据库: {e}") from e


def test_connection(body=None, sid=None):
    cfg = dict(body or {})
    if sid:
        src = get_source(sid, with_secret=True)
        if not src:
            raise ValueError("数据源不存在")
        if not cfg.get("password"):
            cfg["password"] = src.get("password")
        for key in ("host", "port", "username", "database_name", "engine"):
            if not cfg.get(key) and src.get(key):
                cfg[key] = src.get(key)
    conn = _open(cfg, database=cfg.get("database_name") or None)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION() AS v, DATABASE() AS db")
            row = cur.fetchone() or {}
            cur.execute("SHOW DATABASES")
            dbs = [r.get("Database") for r in cur.fetchall() if r.get("Database") not in SKIP_SCHEMAS]
        return {
            "ok": True,
            "version": row.get("v"),
            "current_database": row.get("db"),
            "database_count": len(dbs),
        }
    finally:
        conn.close()


def list_databases(sid):
    src = get_source(sid, with_secret=True)
    if not src:
        raise ValueError("数据源不存在")
    conn = _open(src, database=None)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT SCHEMA_NAME AS name, DEFAULT_CHARACTER_SET_NAME AS charset
                FROM information_schema.SCHEMATA
                ORDER BY SCHEMA_NAME
                """
            )
            rows = cur.fetchall() or []
        items = []
        for r in rows:
            name = r.get("name")
            if name in SKIP_SCHEMAS:
                continue
            items.append({"name": name, "charset": r.get("charset")})
        return {"items": items, "default": src.get("database_name") or ""}
    finally:
        conn.close()


def list_tables(sid, databases=None):
    src = get_source(sid, with_secret=True)
    if not src:
        raise ValueError("数据源不存在")
    names = [d for d in (databases or []) if d and d not in SKIP_SCHEMAS]
    if not names and src.get("database_name"):
        names = [src["database_name"]]
    if not names:
        raise ValueError("请先选择要浏览的数据库")
    placeholders = ", ".join(["%s"] * len(names))
    conn = _open(src, database=None)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT TABLE_SCHEMA AS db_name, TABLE_NAME AS table_name,
                       TABLE_ROWS AS table_rows, TABLE_COMMENT AS table_comment,
                       ENGINE AS engine, DATA_LENGTH AS data_length
                FROM information_schema.TABLES
                WHERE TABLE_TYPE='BASE TABLE' AND TABLE_SCHEMA IN ({placeholders})
                ORDER BY TABLE_SCHEMA, TABLE_NAME
                """,
                names,
            )
            rows = cur.fetchall() or []
        items = []
        for r in rows:
            items.append({
                "database": r.get("db_name"),
                "table": r.get("table_name"),
                "rows": int(r.get("table_rows") or 0),
                "comment": r.get("table_comment") or "",
                "engine": r.get("engine") or "",
                "data_length": int(r.get("data_length") or 0),
            })
        return {"items": items}
    finally:
        conn.close()


def _cell(v):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        try:
            return bytes(v).decode("utf-8")
        except Exception:
            return bytes(v).hex()
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat(sep=" ")
        except TypeError:
            return v.isoformat()
    return v


def _read_table(conn, database, table, max_rows=MAX_IMPORT_ROWS, skip=0, order_col=None, desc=False):
    limit = max(1, min(int(max_rows or MAX_IMPORT_ROWS), MAX_IMPORT_ROWS))
    offset = max(0, int(skip or 0))
    sql = f"SELECT * FROM {_ident(database)}.{_ident(table)}"
    if order_col:
        sql += f" ORDER BY {_ident(order_col)} {'DESC' if desc else 'ASC'}"
    sql += f" LIMIT {limit} OFFSET {offset}"
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall() or []
        cols = [d[0] for d in cur.description] if cur.description else []
    if not cols:
        return pd.DataFrame()
    data = [{k: _cell(r.get(k)) for k in cols} for r in rows]
    return pd.DataFrame(data, columns=cols)


def count_table_rows(sid, database, table):
    src = get_source(sid, with_secret=True)
    if not src:
        raise ValueError("数据源不存在")
    conn = _open(src, database=None)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS c FROM {_ident(database)}.{_ident(table)}")
            row = cur.fetchone() or {}
        return int(row.get("c") or 0)
    finally:
        conn.close()


def read_live_frame(sid, database, table, nrows=None, skip=0, order_col=None, desc=False):
    src = get_source(sid, with_secret=True)
    if not src:
        raise ValueError("数据源不存在")
    if not database or not table:
        raise ValueError("请选择库和表")
    if database in SKIP_SCHEMAS:
        raise ValueError(f"系统库不可读取: {database}")
    conn = _open(src, database=None)
    try:
        return _read_table(
            conn, database, table,
            max_rows=nrows or MAX_IMPORT_ROWS, skip=skip,
            order_col=order_col, desc=desc,
        )
    finally:
        conn.close()


def column_types(sid, database, table):
    """读取表的列名与数据类型，用于挑选时间列、判断字段角色。"""
    src = get_source(sid, with_secret=True)
    if not src:
        raise ValueError("数据源不存在")
    if not database or not table:
        raise ValueError("请选择库和表")
    conn = _open(src, database=None)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COLUMN_NAME AS name, DATA_TYPE AS data_type,
                       COLUMN_COMMENT AS comment, ORDINAL_POSITION AS pos
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s
                ORDER BY ORDINAL_POSITION
                """,
                (database, table),
            )
            rows = cur.fetchall() or []
        return [
            {
                "name": r.get("name"),
                "data_type": str(r.get("data_type") or "").lower(),
                "comment": r.get("comment") or "",
            }
            for r in rows
        ]
    finally:
        conn.close()


def preview_table(sid, database, table, n=40, skip=0, filters=None):
    from services.dataset_service import _apply_row_filters, _normalize_filters, _preview_window
    from utils.field_labels import header_for_column
    from utils.profiler import preview_records
    if not database or not table:
        raise ValueError("请选择库和表")
    n, skip = _preview_window(n, skip)
    filters = _normalize_filters(filters)
    if filters:
        page = read_live_frame(sid, database, table, nrows=20000)
        page = page.copy()
        page["__row_no"] = list(range(1, len(page) + 1))
        page = _apply_row_filters(page, filters)
        total = int(len(page))
        page = page.iloc[skip:skip + n]
    else:
        total = count_table_rows(sid, database, table)
        page = read_live_frame(sid, database, table, nrows=n, skip=skip)
        page = page.copy()
        page["__row_no"] = list(range(skip + 1, skip + 1 + len(page)))
    row_nos = [int(v) for v in page["__row_no"].tolist()] if len(page) else []
    page = page.drop(columns=["__row_no"], errors="ignore")
    return {
        "database": database,
        "table": table,
        "columns": list(page.columns),
        "column_labels": {c: header_for_column(c) for c in page.columns},
        "records": preview_records(page, len(page)),
        "n_rows": total,
        "imported": int(len(page)),
        "skip": skip,
        "row_nos": row_nos,
        "filtered": bool(filters),
        "origin_type": "mysql_live",
    }


def attach_live_dataset(sid, project_id, database, table, name=None, remark="", scenario="generic"):
    from services.dataset_service import _profile_and_store, get_dataset
    if not project_id:
        raise ValueError("请先进入数据集配置后再挂接")
    if not database or not table:
        raise ValueError("请选择库和表")
    if database in SKIP_SCHEMAS:
        raise ValueError(f"系统库不可挂接: {database}")
    src = get_source(sid, with_secret=True)
    if not src:
        raise ValueError("数据源不存在")
    user = _user()
    n_rows = count_table_rows(sid, database, table)
    ds_name = (name or "").strip() or f"{database}.{table}"
    existing = query(
        """
        SELECT id FROM dataset
        WHERE status=1 AND project_id=%s AND origin_type='mysql_live'
          AND source_id=%s AND source_db=%s AND source_table=%s
        ORDER BY id DESC
        """,
        (int(project_id), int(sid), database, table),
        one=True,
    )
    if not existing:
        existing = query(
            "SELECT id FROM dataset WHERE project_id=%s AND name=%s AND status=1 ORDER BY id DESC",
            (int(project_id), ds_name),
            one=True,
        )
    if existing:
        light = {
            "n_rows": n_rows,
            "filename": f"{database}.{table}",
            "file_type": "mysql",
            "origin_type": "mysql_live",
            "source_id": int(sid),
            "source_db": database,
            "source_table": table,
        }
        if (name or "").strip():
            light["name"] = ds_name
        if remark:
            light["remark"] = remark[:500]
        update("dataset", light, "id=%s", (existing["id"],))
        return get_dataset(existing["id"])
    df = read_live_frame(sid, database, table, nrows=50000)
    if df is None or df.empty:
        raise ValueError("表为空，无法挂接")
    payload = {
        "project_id": int(project_id),
        "name": ds_name,
        "scenario_code": scenario or "generic",
        "filename": f"{database}.{table}",
        "file_type": "mysql",
        "origin_type": "mysql_live",
        "source_id": int(sid),
        "source_db": database,
        "source_table": table,
        "remark": (remark or f"实时挂接 {src.get('name')} · {database}.{table}")[:500],
        "user_id": user.get("id"),
        "username": user.get("username") or "system",
        "status": 1,
    }
    payload, _ = _profile_and_store(df, payload)
    payload["n_rows"] = n_rows
    ds_id = insert("dataset", payload)
    return get_dataset(ds_id)


def import_tables(sid, project_id, tables, name=None, remark="", scenario="generic", max_rows=MAX_IMPORT_ROWS):
    if not project_id:
        raise ValueError("请先进入数据集配置后再导入")
    src = get_source(sid, with_secret=True)
    if not src:
        raise ValueError("数据源不存在")
    picks = []
    for item in tables or []:
        if isinstance(item, str):
            if "." not in item:
                raise ValueError(f"表名需要带库名: {item}")
            db, tb = item.split(".", 1)
            picks.append({"database": db, "table": tb, "name": None})
        else:
            db = item.get("database") or item.get("db")
            tb = item.get("table") or item.get("name")
            picks.append({"database": db, "table": tb, "name": item.get("alias")})
    if not picks:
        raise ValueError("请至少选择一张表")
    seen = set()
    cleaned = []
    for p in picks:
        key = (p["database"], p["table"])
        if not p["database"] or not p["table"]:
            raise ValueError("库名和表名不能为空")
        if p["database"] in SKIP_SCHEMAS:
            raise ValueError(f"系统库不可导入: {p['database']}")
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(p)

    conn = _open(src, database=None)
    created = []
    errors = []
    try:
        for i, p in enumerate(cleaned):
            db, tb = p["database"], p["table"]
            try:
                df = _read_table(conn, db, tb, max_rows=max_rows)
                if df is None or df.empty:
                    errors.append({"database": db, "table": tb, "message": "表为空，已跳过"})
                    continue
                ds_name = p.get("name")
                if not ds_name:
                    if name and len(cleaned) == 1:
                        ds_name = name.strip()
                    else:
                        ds_name = f"{db}.{tb}" if len({x['table'] for x in cleaned}) < len(cleaned) else tb
                note = remark or f"导入自 {src.get('name')} · {db}.{tb}"
                row = upsert_dataframe(
                    int(project_id),
                    ds_name,
                    df,
                    scenario=scenario or "generic",
                    remark=note[:500],
                    filename=f"{db}.{tb}",
                )
                created.append({
                    **row,
                    "source_database": db,
                    "source_table": tb,
                    "truncated": int(len(df)) >= int(max_rows or MAX_IMPORT_ROWS),
                })
            except Exception as e:
                errors.append({"database": db, "table": tb, "message": str(e)})
    finally:
        conn.close()
    if not created and errors:
        raise ValueError(errors[0]["message"])
    return {"created": created, "errors": errors, "count": len(created)}


def ensure_default_source():
    if query("SELECT id FROM data_source WHERE status=1", one=True):
        return
    insert("data_source", {
        "name": "本机 MySQL",
        "engine": "mysql",
        "host": DB_CONFIG.get("host", "127.0.0.1"),
        "port": int(DB_CONFIG.get("port", 3306)),
        "db_user": DB_CONFIG.get("user", "root"),
        "db_password": DB_CONFIG.get("password", "root"),
        "database_name": DB_CONFIG.get("database", "insight_forge"),
        "remark": "系统自动登记的本地 MySQL，可浏览库表并导入为数据表",
        "username": "system",
        "status": 1,
    })
