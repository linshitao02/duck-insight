# -*- coding: utf-8 -*-
import os
import sqlite3
import threading
from datetime import datetime

import pymysql
from pymysql.cursors import DictCursor

from config import DB_CONFIG, DB_ENGINE, SQLITE_PATH
from utils.sql_dialect import adapt_sql, show_columns_table

_LOCK = threading.RLock()
_COLUMNS = {}


def is_sqlite():
    return DB_ENGINE == "sqlite"


def get_conn(database=None):
    if is_sqlite():
        os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)
        conn = sqlite3.connect(SQLITE_PATH, check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
    cfg = dict(DB_CONFIG)
    if database is not None:
        cfg["database"] = database
    cfg.pop("engine", None)
    cfg.pop("path", None)
    return pymysql.connect(cursorclass=DictCursor, autocommit=False, **cfg)


def _dicts(cursor):
    if cursor.description is None:
        return []
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _run(sql, args=None, fetch=False):
    statement = adapt_sql(sql) if is_sqlite() else sql
    params = tuple(args or ())
    if is_sqlite():
        with _LOCK:
            conn = get_conn()
            try:
                cur = conn.execute(statement, params)
                rows = _dicts(cur) if fetch else []
                conn.commit()
                return rows, cur.lastrowid, cur.rowcount
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(statement, params)
            rows = list(cur.fetchall()) if fetch else []
            conn.commit()
            return rows, cur.lastrowid, cur.rowcount
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def table_columns(table):
    cached = _COLUMNS.get(table)
    if cached is not None:
        return cached
    if is_sqlite():
        rows, _, _ = _run(f'PRAGMA table_info("{table}")', fetch=True)
        cols = {row["name"] for row in rows}
    else:
        rows = query(f"SHOW COLUMNS FROM `{table}`")
        cols = {row["Field"] for row in rows}
    _COLUMNS[table] = cols
    return cols


def clear_column_cache():
    _COLUMNS.clear()


def query(sql, args=None, one=False):
    table = show_columns_table(sql) if is_sqlite() else None
    if table:
        rows, _, _ = _run(f'PRAGMA table_info("{table}")', fetch=True)
        mapped = [
            {"Field": row["name"], "Type": row["type"], "Null": "NO" if row["notnull"] else "YES"}
            for row in rows
        ]
        return (mapped[0] if mapped else None) if one else mapped
    rows, _, _ = _run(sql, args, fetch=True)
    if one:
        return rows[0] if rows else None
    return rows


def execute(sql, args=None):
    _, last_id, count = _run(sql, args, fetch=False)
    return last_id, count


def insert(table, data: dict):
    cols = [key for key, value in data.items() if value is not None]
    if not cols:
        return None
    marks = ", ".join(["%s"] * len(cols))
    quoted = ", ".join(f"`{col}`" for col in cols)
    sql = f"INSERT INTO `{table}` ({quoted}) VALUES ({marks})"
    last_id, _ = execute(sql, [data[col] for col in cols])
    return last_id


def update(table, data: dict, where_sql: str, where_args=None):
    payload = {key: value for key, value in data.items() if value is not None}
    if "update_time" not in data:
        try:
            if "update_time" in table_columns(table):
                payload["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    cols = list(payload.keys())
    if not cols:
        return 0
    sets = ", ".join(f"`{col}`=%s" for col in cols)
    sql = f"UPDATE `{table}` SET {sets} WHERE {where_sql}"
    _, count = execute(sql, [payload[col] for col in cols] + list(where_args or []))
    return count


def delete(table, where_sql: str, where_args=None):
    _, count = execute(f"DELETE FROM `{table}` WHERE {where_sql}", where_args or [])
    return count
