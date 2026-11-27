# -*- coding: utf-8 -*-
"""Apache Doris 实时入库（Routine Load）、实时明细表与 SQL 控制台服务。"""
import json
import os
import re
import time
from datetime import date, datetime
from decimal import Decimal

import pymysql

DORIS_HOST = os.environ.get("DORIS_HOST", "192.168.139.10")
DORIS_PORT = int(os.environ.get("DORIS_PORT", "9030"))
DORIS_USER = os.environ.get("DORIS_USER", "root")
DORIS_PASSWORD = os.environ.get("DORIS_PASSWORD", "")
DORIS_DATABASE = os.environ.get("DORIS_DATABASE", "dw_ecommerce")
DORIS_KAFKA_BROKERS = os.environ.get("DORIS_KAFKA_BROKERS", "kafka:9092")

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_TOPIC_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_READONLY_RE = re.compile(r"^\s*(SELECT|SHOW|DESC|DESCRIBE|EXPLAIN|WITH)\b", re.IGNORECASE)
_LIMIT_RE = re.compile(r"\bLIMIT\s+\d+", re.IGNORECASE)


def _safe_val(v):
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime) else v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", "replace")
    return v


def _safe_row(row):
    if isinstance(row, dict):
        return {k: _safe_val(v) for k, v in row.items()}
    return [_safe_val(x) for x in row]


def _parse_json_safe(text):
    if not text:
        return {}
    if isinstance(text, dict):
        return text
    try:
        return json.loads(text)
    except Exception:
        return {}


def _conn(database=DORIS_DATABASE, timeout=6):
    return pymysql.connect(
        host=DORIS_HOST,
        port=DORIS_PORT,
        user=DORIS_USER,
        password=DORIS_PASSWORD,
        database=database or None,
        charset="utf8mb4",
        connect_timeout=timeout,
        read_timeout=15,
        write_timeout=15,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def _check_ident(name, label="名称"):
    s = (name or "").strip()
    if not s or not _IDENT_RE.match(s):
        raise ValueError(f"{label}不合法，只允许字母、数字、下划线且以字母或下划线开头")
    return s


def get_overview():
    """查询 Doris 集群 FE/BE 健康、表数量及 Routine Load 汇总。"""
    base = {
        "connected": False,
        "host": DORIS_HOST,
        "port": DORIS_PORT,
        "database": DORIS_DATABASE,
        "kafka_brokers": DORIS_KAFKA_BROKERS,
        "frontends": [],
        "backends": [],
        "table_count": 0,
        "routine_load_summary": {
            "total": 0,
            "running": 0,
            "paused": 0,
            "stopped": 0,
            "total_loaded_rows": 0,
            "total_error_rows": 0,
        },
        "error": None,
    }
    try:
        conn = _conn(database=None, timeout=5)
    except Exception as e:
        base["error"] = f"无法连接 Doris（{DORIS_HOST}:{DORIS_PORT}）: {e}"
        return base

    try:
        with conn.cursor() as cur:
            base["connected"] = True

            cur.execute("SHOW FRONTENDS")
            for r in cur.fetchall() or []:
                base["frontends"].append({
                    "name": r.get("Name"),
                    "host": r.get("Host") or r.get("IP"),
                    "alive": str(r.get("Alive", "")).lower() == "true",
                    "is_master": str(r.get("IsMaster", "")).lower() == "true",
                    "query_port": r.get("QueryPort"),
                    "http_port": r.get("HttpPort"),
                    "version": r.get("Version"),
                })

            cur.execute("SHOW BACKENDS")
            for r in cur.fetchall() or []:
                base["backends"].append({
                    "id": r.get("BackendId"),
                    "host": r.get("Host") or r.get("IP"),
                    "alive": str(r.get("Alive", "")).lower() == "true",
                    "tablet_num": int(r.get("TabletNum") or 0),
                    "avail_capacity": r.get("AvailCapacity"),
                    "total_capacity": r.get("TotalCapacity"),
                    "used_pct": r.get("UsedPct"),
                    "mem_used_pct": r.get("MemUsedPct"),
                    "version": r.get("Version"),
                })

            try:
                cur.execute(f"USE `{DORIS_DATABASE}`")
                cur.execute("SHOW TABLES")
                base["table_count"] = len(cur.fetchall() or [])
            except Exception:
                base["table_count"] = 0

        loads = list_routine_loads()
        sm = base["routine_load_summary"]
        sm["total"] = len(loads)
        for j in loads:
            st = (j.get("state") or "").upper()
            if st == "RUNNING":
                sm["running"] += 1
            elif st == "PAUSED":
                sm["paused"] += 1
            elif st in ("STOPPED", "CANCELLED"):
                sm["stopped"] += 1
            sm["total_loaded_rows"] += int(j.get("loaded_rows") or 0)
            sm["total_error_rows"] += int(j.get("error_rows") or 0)
        return base
    except Exception as e:
        base["error"] = str(e)
        return base
    finally:
        conn.close()


def list_tables():
    """列出 Doris 目标库中的所有实时明细表与视图。"""
    conn = _conn(timeout=5)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT TABLE_NAME, TABLE_TYPE, ENGINE, TABLE_ROWS, DATA_LENGTH, CREATE_TIME, TABLE_COMMENT
                FROM information_schema.tables
                WHERE TABLE_SCHEMA = %s
                ORDER BY TABLE_TYPE ASC, TABLE_NAME ASC
                """,
                (DORIS_DATABASE,),
            )
            rows = cur.fetchall() or []
            items = []
            for r in rows:
                tname = r.get("TABLE_NAME")
                exact_rows = r.get("TABLE_ROWS")
                try:
                    cur.execute(f"SELECT COUNT(*) AS cnt FROM `{tname}`")
                    cnt_row = cur.fetchone() or {}
                    exact_rows = int(cnt_row.get("cnt") or 0)
                except Exception:
                    pass
                items.append({
                    "name": tname,
                    "table_type": r.get("TABLE_TYPE") or "BASE TABLE",
                    "engine": r.get("ENGINE") or "Doris",
                    "rows": exact_rows,
                    "data_length": int(r.get("DATA_LENGTH") or 0),
                    "create_time": _safe_val(r.get("CREATE_TIME")),
                    "comment": r.get("TABLE_COMMENT") or "",
                })
            return items
    finally:
        conn.close()


def preview_table(table_name, limit=20):
    """查看 Doris 表结构与最新抽样数据。"""
    tname = _check_ident(table_name, "表名")
    limit = max(1, min(200, int(limit or 20)))
    conn = _conn(timeout=5)
    try:
        with conn.cursor() as cur:
            cur.execute(f"DESC `{tname}`")
            cols_raw = cur.fetchall() or []
            schema = [
                {
                    "field": c.get("Field"),
                    "type": c.get("Type"),
                    "nullable": c.get("Null"),
                    "key": c.get("Key"),
                    "default": c.get("Default"),
                    "extra": c.get("Extra"),
                }
                for c in cols_raw
            ]
            cur.execute(f"SELECT COUNT(*) AS cnt FROM `{tname}`")
            total = int((cur.fetchone() or {}).get("cnt") or 0)

            cur.execute(f"SELECT * FROM `{tname}` LIMIT {limit}")
            data_rows = [_safe_row(r) for r in (cur.fetchall() or [])]
            return {
                "table": tname,
                "database": DORIS_DATABASE,
                "total_rows": total,
                "schema": schema,
                "columns": [s["field"] for s in schema],
                "rows": data_rows,
            }
    finally:
        conn.close()


def list_routine_loads():
    """查询目标库下所有 Doris Routine Load 入库作业。"""
    conn = _conn(timeout=5)
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW ALL ROUTINE LOAD")
            rows = cur.fetchall() or []
            items = []
            for r in rows:
                ds_props = _parse_json_safe(r.get("DataSourceProperties"))
                stat = _parse_json_safe(r.get("Statistic"))
                progress = _parse_json_safe(r.get("Progress"))
                job_props = _parse_json_safe(r.get("JobProperties"))
                items.append({
                    "id": r.get("Id"),
                    "name": r.get("Name"),
                    "create_time": _safe_val(r.get("CreateTime")),
                    "pause_time": _safe_val(r.get("PauseTime")),
                    "end_time": _safe_val(r.get("EndTime")),
                    "db_name": r.get("DbName"),
                    "table_name": r.get("TableName"),
                    "state": r.get("State"),
                    "data_source_type": r.get("DataSourceType"),
                    "current_task_num": int(r.get("CurrentTaskNum") or 0),
                    "topic": ds_props.get("topic") or "",
                    "kafka_brokers": ds_props.get("kafka_broker_list") or "",
                    "loaded_rows": int(stat.get("loadedRows") or 0),
                    "error_rows": int(stat.get("errorRows") or 0),
                    "unselected_rows": int(stat.get("unselectedRows") or 0),
                    "received_bytes": int(stat.get("receivedBytes") or 0),
                    "total_rows": int(stat.get("totalRows") or 0),
                    "committed_tasks": int(stat.get("committedTaskNum") or 0),
                    "progress": progress,
                    "job_properties": job_props,
                    "reason": r.get("ReasonOfStateChanged") or "",
                    "error_log_urls": r.get("ErrorLogUrls") or "",
                })
            return items
    finally:
        conn.close()


def create_routine_load(body):
    """可视化创建 Doris Routine Load（Kafka -> Doris 实时入库作业）。"""
    job_name = _check_ident(body.get("job_name"), "入库作业名")
    table_name = _check_ident(body.get("table_name"), "目标 Doris 表名")
    topic = (body.get("topic") or "").strip()
    if not topic or not _TOPIC_RE.match(topic):
        raise ValueError("Kafka 主题名不合法")

    fmt = (body.get("format") or "debezium-json").strip().lower()
    if fmt not in ("debezium-json", "json"):
        raise ValueError("格式只支持 debezium-json 或 json")

    concurrent = max(1, min(8, int(body.get("desired_concurrent_number") or 1)))
    max_error = max(0, min(100000, int(body.get("max_error_number") or 100)))
    offset_mode = (body.get("offset") or "OFFSET_BEGINNING").strip().upper()
    if offset_mode not in ("OFFSET_BEGINNING", "OFFSET_END"):
        offset_mode = "OFFSET_BEGINNING"

    conn = _conn(timeout=6)
    try:
        with conn.cursor() as cur:
            cur.execute(f"DESC `{table_name}`")
            desc_rows = cur.fetchall() or []
            if not desc_rows:
                raise ValueError(f"目标表 {table_name} 不存在")
            cols = [c["Field"] for c in desc_rows if not str(c["Field"]).startswith("__DORIS_")]
            if not cols:
                raise ValueError(f"目标表 {table_name} 未解析到业务字段")

            if fmt == "debezium-json":
                jsonpaths = [f"$.after.{c}" for c in cols] + ["$.op"]
                col_expr = ", ".join([f"`{c}`" for c in cols] + ["op"])
                merge_clause = "WITH MERGE\n"
                col_block = f"COLUMNS({col_expr}),\nPRECEDING FILTER op IS NOT NULL,\nDELETE ON op = 'd'"
            else:
                jsonpaths = [f"$.{c}" for c in cols]
                col_expr = ", ".join([f"`{c}`" for c in cols])
                merge_clause = ""
                col_block = f"COLUMNS({col_expr})"

            jp_json = json.dumps(jsonpaths, ensure_ascii=False)
            ddl = f"""CREATE ROUTINE LOAD `{DORIS_DATABASE}`.`{job_name}` ON `{table_name}`
{merge_clause}{col_block}
PROPERTIES
(
    "desired_concurrent_number" = "{concurrent}",
    "max_batch_interval" = "5",
    "max_batch_rows" = "200000",
    "max_error_number" = "{max_error}",
    "format" = "json",
    "jsonpaths" = '{jp_json}',
    "strip_outer_array" = "false",
    "strict_mode" = "false"
)
FROM KAFKA
(
    "kafka_broker_list" = "{DORIS_KAFKA_BROKERS}",
    "kafka_topic" = "{topic}",
    "property.kafka_default_offsets" = "{offset_mode}",
    "property.group.id" = "doris_rl_{job_name}"
)"""
            cur.execute(ddl)
            return {"job_name": job_name, "table_name": table_name, "topic": topic, "ddl": ddl}
    finally:
        conn.close()


def control_routine_load(job_name, action):
    """暂停 / 恢复 / 停止 Routine Load 作业。"""
    jname = _check_ident(job_name, "入库作业名")
    act = (action or "").strip().lower()
    if act not in ("pause", "resume", "stop"):
        raise ValueError("不支持的操作类型")
    verb = act.upper()
    conn = _conn(timeout=6)
    try:
        with conn.cursor() as cur:
            cur.execute(f"{verb} ROUTINE LOAD FOR `{DORIS_DATABASE}`.`{jname}`")
            return {"job_name": jname, "action": act}
    finally:
        conn.close()


def execute_sql(sql_text, read_only=False):
    """Doris SQL 控制台执行（支持只读限制与自动 LIMIT）。"""
    raw = (sql_text or "").strip().rstrip(";").strip()
    if not raw:
        raise ValueError("SQL 不能为空")
    if ";" in raw:
        raise ValueError("一次只允许执行一条 SQL 语句")
    if read_only and not _READONLY_RE.match(raw):
        raise ValueError("当前账号仅允许执行只读查询（SELECT / SHOW / DESC / EXPLAIN）")

    exec_sql = raw
    if re.match(r"^\s*(SELECT|WITH)\b", exec_sql, re.IGNORECASE) and not _LIMIT_RE.search(exec_sql):
        exec_sql = f"{exec_sql} LIMIT 500"

    t0 = time.time()
    conn = _conn(timeout=6)
    try:
        with conn.cursor() as cur:
            cur.execute(exec_sql)
            elapsed_ms = int((time.time() - t0) * 1000)
            if cur.description:
                columns = [d[0] for d in cur.description]
                rows = [_safe_row(r) for r in (cur.fetchall() or [])]
                return {
                    "columns": columns,
                    "rows": rows,
                    "row_count": len(rows),
                    "elapsed_ms": elapsed_ms,
                    "executed_sql": exec_sql,
                }
            return {
                "columns": ["affected_rows"],
                "rows": [{"affected_rows": cur.rowcount}],
                "row_count": cur.rowcount,
                "elapsed_ms": elapsed_ms,
                "executed_sql": exec_sql,
            }
    finally:
        conn.close()
