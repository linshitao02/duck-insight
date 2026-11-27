# -*- coding: utf-8 -*-
"""实时同步服务：对齐 Taier 实时采集/Flink SQL 模式切换 与 DataWorks 多表同步规则。

核心能力：
1. 读取 MySQL 表结构与主键，映射为 Flink SQL 字段类型；
2. 向导模式生成单表或多表（EXECUTE STATEMENT SET）Flink CDC -> Kafka SQL；
3. 支持向导模式转为脚本模式（转换后不再被向导覆盖）；
4. Kafka 主题目录管理（支持对接真实 Kafka 集群或本地登记）；
5. Flink 作业提交、停止、状态刷新与最近检查点续跑。
"""
import json
import os
import re
import shlex
import subprocess
import urllib.error
import urllib.request

from flask import g
from kafka import KafkaAdminClient
from kafka.admin import NewTopic

from services import source_service
from utils.db import execute, insert, query, update
from utils.jsonx import dumps, loads, row_to_dict

FLINK_REST_URL = (os.environ.get("FLINK_REST_URL") or "http://127.0.0.1:8081").rstrip("/")
KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP") or "kafka:9092"
KAFKA_ADMIN_BOOTSTRAP = os.environ.get("KAFKA_ADMIN_BOOTSTRAP") or "127.0.0.1:9092"
FLINK_SQL_CLIENT_CMD = os.environ.get("FLINK_SQL_CLIENT_CMD") or ""
TOPIC_ALREADY_EXISTS = 36  # Kafka 错误码 TOPIC_ALREADY_EXISTS
REALTIME_CHECKPOINT_DIR = os.environ.get("REALTIME_CHECKPOINT_DIR") or "/opt/flink/state/checkpoints"

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_TOPIC_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_JOB_ID_RE = re.compile(r"Job ID:\s*([0-9a-fA-F]{32})")


def _user():
    u = getattr(g, "user", None) or {}
    return u.get("id"), u.get("username") or "system"


def _http_json(url, method="GET", timeout=5):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
        return json.loads(raw) if raw.strip() else {}


def _mysql_type_to_flink(data_type, column_type=""):
    dt = (data_type or "").lower().strip()
    ct = (column_type or "").lower().strip()
    if dt in ("bigint",):
        return "BIGINT"
    if dt in ("int", "integer", "mediumint"):
        return "INT"
    if dt in ("smallint",):
        return "SMALLINT"
    if dt == "tinyint":
        return "BOOLEAN" if ct.startswith("tinyint(1)") else "TINYINT"
    if dt in ("decimal", "numeric"):
        m = re.search(r"\((\d+)\s*,\s*(\d+)\)", ct)
        if m:
            return f"DECIMAL({m.group(1)}, {m.group(2)})"
        return "DECIMAL(18, 2)"
    if dt in ("double", "real"):
        return "DOUBLE"
    if dt in ("float",):
        return "FLOAT"
    if dt in ("datetime", "timestamp"):
        return "TIMESTAMP(3)"
    if dt == "date":
        return "DATE"
    if dt == "time":
        return "TIME(0)"
    if dt in ("binary", "varbinary", "blob", "longblob", "mediumblob"):
        return "BYTES"
    return "STRING"


def default_topic_name(prefix, database_name, table_name):
    p = re.sub(r"[^A-Za-z0-9_]+", "_", (prefix or "cdc").strip()).strip("_") or "cdc"
    d = re.sub(r"[^A-Za-z0-9_]+", "_", (database_name or "db").strip()).strip("_") or "db"
    t = re.sub(r"[^A-Za-z0-9_]+", "_", (table_name or "tbl").strip()).strip("_") or "tbl"
    return f"{p}_{d}_{t}"[:120]


def fetch_source_table_schemas(source_id, database_name, tables):
    """读取 MySQL 多张表的字段、类型、主键，并生成 Flink 类型映射。"""
    if not source_id:
        raise ValueError("请选择 MySQL 数据源")
    if not database_name:
        raise ValueError("请选择数据库")
    if not tables:
        return []
    cfg = source_service.get_source(int(source_id), with_secret=True)
    if not cfg:
        raise ValueError("数据源不存在")
    conn = source_service._open(cfg, database=database_name)
    result = []
    try:
        with conn.cursor() as cur:
            for tbl in tables:
                tname = str(tbl).strip()
                if not tname:
                    continue
                cur.execute(
                    """
                    SELECT COLUMN_NAME, DATA_TYPE, COLUMN_TYPE, COLUMN_KEY, IS_NULLABLE, COLUMN_COMMENT
                    FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s
                    ORDER BY ORDINAL_POSITION
                    """,
                    (database_name, tname),
                )
                rows = cur.fetchall() or []
                cols = []
                pks = []
                for r in rows:
                    cname = r.get("COLUMN_NAME")
                    dtype = r.get("DATA_TYPE")
                    ctype = r.get("COLUMN_TYPE")
                    is_pk = (r.get("COLUMN_KEY") or "").upper() == "PRI"
                    if is_pk:
                        pks.append(cname)
                    cols.append({
                        "name": cname,
                        "mysql_type": ctype or dtype,
                        "flink_type": _mysql_type_to_flink(dtype, ctype),
                        "is_pk": is_pk,
                        "nullable": (r.get("IS_NULLABLE") or "YES").upper() == "YES",
                        "comment": r.get("COLUMN_COMMENT") or "",
                    })
                result.append({
                    "table": tname,
                    "primary_keys": pks,
                    "columns": cols,
                })
    finally:
        conn.close()
    return result


def _safe_flink_ident(name):
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", str(name or "").strip())
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"t_{cleaned}"
    return cleaned[:60]


def _default_channel(channel=None, task_id=None):
    ch = dict(channel or {})
    base_id = 5400 + (int(task_id) if task_id else 1) * 10
    return {
        "parallelism": max(1, min(16, int(ch.get("parallelism") or 1))),
        "checkpoint_interval_ms": max(3000, int(ch.get("checkpoint_interval_ms") or 10000)),
        "startup_mode": ch.get("startup_mode") or "initial",
        "server_id_range": (ch.get("server_id_range") or f"{base_id}-{base_id + 4}").strip(),
        "kafka_bootstrap": (ch.get("kafka_bootstrap") or KAFKA_BOOTSTRAP).strip(),
        "mysql_host_override": (ch.get("mysql_host_override") or "").strip(),
        "mysql_port_override": ch.get("mysql_port_override") or "",
        "kafka_format": ch.get("kafka_format") or "debezium-json",
        "topic_replication_factor": max(1, min(3, int(ch.get("topic_replication_factor") or 1))),
        "topic_retention_days": max(1, min(90, int(ch.get("topic_retention_days") or 7))),
    }


def build_flink_sql(
    name,
    source_cfg,
    database_name,
    tables_cfg,
    channel=None,
    task_id=None,
    mask_secret=True,
    savepoint_path=None,
):
    """按 Taier + DataWorks 规范生成单表或多表 Flink CDC -> Kafka SQL。"""
    if not tables_cfg:
        raise ValueError("请至少勾选一张需要同步的表")
    ch = _default_channel(channel, task_id=task_id)
    raw_pipe = re.sub(r"[^A-Za-z0-9_.-]+", "-", (name or "").strip()).strip("-")
    pipe_name = raw_pipe or f"sync-task-{task_id or 'job'}"
    host = ch["mysql_host_override"] or (source_cfg or {}).get("host") or "mysql"
    port = str(ch["mysql_port_override"] or (source_cfg or {}).get("port") or 3306)
    username = (source_cfg or {}).get("username") or "cdc"
    password = "***" if mask_secret else ((source_cfg or {}).get("password") or "")
    startup_mode = ch["startup_mode"] if ch["startup_mode"] in ("initial", "latest-offset", "earliest-offset") else "initial"

    lines = []
    if savepoint_path:
        lines.append(f"SET 'execution.savepoint.path' = '{savepoint_path}';")
    lines.extend([
        "SET 'execution.runtime-mode' = 'streaming';",
        f"SET 'parallelism.default' = '{ch['parallelism']}';",
        f"SET 'execution.checkpointing.interval' = '{ch['checkpoint_interval_ms']}ms';",
        "SET 'execution.attached' = 'false';",
        f"SET 'pipeline.name' = '{pipe_name}';",
        "SET 'table.local-time-zone' = 'Asia/Shanghai';",
        "",
    ])

    inserts = []
    for idx, item in enumerate(tables_cfg):
        tname = str(item.get("table") or "").strip()
        if not tname:
            continue
        topic = str(item.get("topic") or default_topic_name("cdc", database_name, tname)).strip()
        cols = item.get("columns") or []
        if not cols:
            cols = [{"name": "id", "flink_type": "BIGINT", "is_pk": True}]
        pks = [c["name"] for c in cols if c.get("is_pk")] or list(item.get("primary_keys") or [])
        if not pks:
            pks = [cols[0]["name"]]

        src_tbl = f"src_{_safe_flink_ident(tname)}"
        sink_tbl = f"kafka_{_safe_flink_ident(tname)}"
        col_defs = [f"  `{c['name']}` {c.get('flink_type') or 'STRING'}" for c in cols]
        pk_clause = ", ".join(f"`{k}`" for k in pks)
        src_col_block = ",\n".join(col_defs + [f"  PRIMARY KEY ({pk_clause}) NOT ENFORCED"])
        sink_col_block = ",\n".join(col_defs)
        select_cols = ", ".join(f"`{c['name']}`" for c in cols)

        # 多表共用一条任务时，各源表使用不重叠的 server-id 偏移
        sid_range = ch["server_id_range"]
        if len(tables_cfg) > 1 and "-" in sid_range:
            try:
                start_id = int(sid_range.split("-", 1)[0]) + idx * 10
                sid_range = f"{start_id}-{start_id + 4}"
            except Exception:
                pass

        lines.extend([
            f"-- 表 {idx + 1}: {database_name}.{tname} -> Kafka 主题 {topic}",
            f"CREATE TABLE {src_tbl} (",
            src_col_block,
            ") WITH (",
            "  'connector' = 'mysql-cdc',",
            f"  'hostname' = '{host}',",
            f"  'port' = '{port}',",
            f"  'username' = '{username}',",
            f"  'password' = '{password}',",
            f"  'database-name' = '{database_name}',",
            f"  'table-name' = '{tname}',",
            "  'server-time-zone' = 'Asia/Shanghai',",
            f"  'server-id' = '{sid_range}',",
            f"  'scan.startup.mode' = '{startup_mode}',",
            "  'jdbc.properties.useSSL' = 'false',",
            "  'jdbc.properties.allowPublicKeyRetrieval' = 'true',",
            "  'debezium.database.allowPublicKeyRetrieval' = 'true',",
            "  'connect.timeout' = '30s'",
            ");",
            "",
            f"CREATE TABLE {sink_tbl} (",
            sink_col_block,
            ") WITH (",
            "  'connector' = 'kafka',",
            f"  'topic' = '{topic}',",
            f"  'properties.bootstrap.servers' = '{ch['kafka_bootstrap']}',",
            f"  'format' = '{ch['kafka_format']}',",
            "  'debezium-json.timestamp-format.standard' = 'SQL'",
            ");",
            "",
        ])
        inserts.append(f"  INSERT INTO {sink_tbl} SELECT {select_cols} FROM {src_tbl};")

    if len(inserts) == 1:
        lines.append(inserts[0].lstrip())
    else:
        lines.append("EXECUTE STATEMENT SET")
        lines.append("BEGIN")
        lines.extend(inserts)
        lines.append("END;")

    return "\n".join(lines) + "\n"


def _serialize_task(row):
    if not row:
        return None
    d = row_to_dict(row)
    d["tables"] = loads(d.pop("tables_json", None), [])
    d["channel"] = _default_channel(loads(d.pop("channel_json", None), {}), task_id=d.get("id"))
    return d


def list_tasks():
    rows = query(
        "SELECT * FROM realtime_sync_task WHERE status=1 ORDER BY update_time DESC, id DESC"
    )
    return [_serialize_task(r) for r in (rows or [])]


def get_task(tid):
    row = query("SELECT * FROM realtime_sync_task WHERE id=%s AND status=1", (int(tid),), one=True)
    return _serialize_task(row)


def _sync_topics_for_task(task_id, tables_cfg, channel=None):
    uid, uname = _user()
    ch = _default_channel(channel, task_id=task_id)
    for item in tables_cfg or []:
        tname = str(item.get("topic") or "").strip()
        if not tname:
            continue
        exists = query("SELECT id FROM realtime_kafka_topic WHERE name=%s", (tname,), one=True)
        if not exists:
            insert("realtime_kafka_topic", {
                "name": tname,
                "partitions": int(item.get("partitions") or 1),
                "replication_factor": ch["topic_replication_factor"],
                "retention_ms": ch["topic_retention_days"] * 86400 * 1000,
                "source_task_id": task_id,
                "remark": f"由同步任务 #{task_id} 映射表 {item.get('table') or ''} 自动登记",
                "user_id": uid,
                "username": uname,
                "status": 1,
            })


def save_task(body, tid=None):
    name = (body.get("name") or "").strip()
    if not name:
        raise ValueError("请填写任务名称")
    existing = get_task(tid) if tid else None
    if tid and not existing:
        raise ValueError("同步任务不存在")

    mode = (body.get("mode") or (existing.get("mode") if existing else "wizard")).strip()
    if mode not in ("wizard", "script"):
        mode = "wizard"

    source_id = body.get("source_id") if "source_id" in body else (existing.get("source_id") if existing else None)
    database_name = (body.get("database_name") if "database_name" in body else (existing.get("database_name") if existing else "")) or ""
    topic_prefix = (body.get("topic_prefix") or (existing.get("topic_prefix") if existing else "cdc")).strip() or "cdc"
    tables = body.get("tables") if "tables" in body else (existing.get("tables") if existing else [])
    channel = _default_channel(
        body.get("channel") if "channel" in body else (existing.get("channel") if existing else {}),
        task_id=tid,
    )

    source_cfg = source_service.get_source(int(source_id), with_secret=True) if source_id else None
    generated_sql = existing.get("generated_sql") if existing else ""
    if mode == "wizard" and tables:
        generated_sql = build_flink_sql(
            name=name,
            source_cfg=source_cfg,
            database_name=database_name,
            tables_cfg=tables,
            channel=channel,
            task_id=tid,
            mask_secret=True,
        )

    script_sql = body.get("script_sql") if "script_sql" in body else (existing.get("script_sql") if existing else "")

    uid, uname = _user()
    payload = {
        "name": name,
        "description": (body.get("description") or "").strip(),
        "mode": mode,
        "source_id": int(source_id) if source_id else None,
        "database_name": database_name,
        "topic_prefix": topic_prefix,
        "tables_json": dumps(tables or []),
        "channel_json": dumps(channel),
        "generated_sql": generated_sql,
        "script_sql": script_sql,
    }
    if tid:
        update("realtime_sync_task", payload, "id=%s", (int(tid),))
        task_id = int(tid)
    else:
        payload.update({
            "job_status": "draft",
            "user_id": uid,
            "username": uname,
            "status": 1,
        })
        task_id = insert("realtime_sync_task", payload)
        # 新建后用真实 task_id 再刷新一次 server-id 区间
        if mode == "wizard" and tables:
            channel = _default_channel(body.get("channel") or {}, task_id=task_id)
            generated_sql = build_flink_sql(
                name=name,
                source_cfg=source_cfg,
                database_name=database_name,
                tables_cfg=tables,
                channel=channel,
                task_id=task_id,
                mask_secret=True,
            )
            update(
                "realtime_sync_task",
                {"channel_json": dumps(channel), "generated_sql": generated_sql},
                "id=%s",
                (task_id,),
            )

    _sync_topics_for_task(task_id, tables, channel)
    return get_task(task_id)


def delete_task(tid):
    update("realtime_sync_task", {"status": 0}, "id=%s", (int(tid),))


def convert_to_script(tid):
    """对齐 Taier 模式切换：向导模式转为脚本模式，之后向导不再覆盖脚本。"""
    task = get_task(tid)
    if not task:
        raise ValueError("同步任务不存在")
    if task.get("mode") == "script":
        return task
    sql = task.get("script_sql") or task.get("generated_sql") or ""
    update("realtime_sync_task", {"mode": "script", "script_sql": sql}, "id=%s", (int(tid),))
    return get_task(tid)


def preview_sql(body):
    source_id = body.get("source_id")
    source_cfg = source_service.get_source(int(source_id), with_secret=True) if source_id else None
    sql = build_flink_sql(
        name=body.get("name") or "sync-preview",
        source_cfg=source_cfg,
        database_name=body.get("database_name") or "ecommerce",
        tables_cfg=body.get("tables") or [],
        channel=body.get("channel") or {},
        task_id=body.get("id"),
        mask_secret=True,
    )
    return {"sql": sql}


def _kafka_reachable():
    try:
        _cluster_topic_names()
        return True
    except Exception:
        return False


def cluster_overview():
    """查询 Flink 集群概览。"""
    try:
        data = _http_json(f"{FLINK_REST_URL}/overview", timeout=4)
        return {
            "connected": True,
            "flink_rest_url": FLINK_REST_URL,
            "kafka_bootstrap": KAFKA_BOOTSTRAP,
            "kafka_admin_bootstrap": KAFKA_ADMIN_BOOTSTRAP,
            "kafka_connected": _kafka_reachable(),
            "flink_version": data.get("flink-version"),
            "taskmanagers": data.get("taskmanagers", 0),
            "slots_total": data.get("slots-total", 0),
            "slots_available": data.get("slots-available", 0),
            "jobs_running": data.get("jobs-running", 0),
        }
    except Exception as e:
        return {
            "connected": False,
            "flink_rest_url": FLINK_REST_URL,
            "kafka_bootstrap": KAFKA_BOOTSTRAP,
            "error": str(e),
        }


def _find_latest_checkpoint(job_id):
    if not job_id:
        return None
    try:
        data = _http_json(f"{FLINK_REST_URL}/jobs/{job_id}/checkpoints", timeout=4)
        latest = (data.get("latest") or {}).get("completed") or {}
        return latest.get("external_path")
    except Exception:
        return None


_STATE_MAP = {
    "RUNNING": "running",
    "RESTARTING": "running",
    "CREATED": "running",
    "INITIALIZING": "running",
    "RECONCILING": "running",
    "CANCELED": "stopped",
    "CANCELLING": "stopped",
    "FINISHED": "stopped",
    "FAILED": "failed",
    "FAILING": "failed",
}


def _fetch_jobs_overview_map():
    """一次拉取 Flink 集群所有作业概览，按 jid 索引。"""
    try:
        data = _http_json(f"{FLINK_REST_URL}/jobs/overview", timeout=4)
        return {j["jid"]: j for j in (data.get("jobs") or []) if j.get("jid")}
    except Exception:
        return {}


def list_ops_tasks(sync_cluster=False):
    """运维中心列表：合并 Flink 集群实时运行态、时长与任务统计。"""
    tasks = list_tasks()
    jobs_map = _fetch_jobs_overview_map()
    enriched = []
    stats = {"total": 0, "running": 0, "stopped": 0, "failed": 0, "draft": 0}

    for t in tasks:
        jid = t.get("flink_job_id")
        fj = jobs_map.get(jid) if jid else None
        if fj:
            raw_state = (fj.get("state") or "").upper()
            mapped = _STATE_MAP.get(raw_state, t.get("job_status") or "draft")
            t["flink_state"] = raw_state
            t["flink_job_name"] = fj.get("name")
            t["start_time"] = fj.get("start-time") if (fj.get("start-time") or -1) > 0 else None
            t["end_time"] = fj.get("end-time") if (fj.get("end-time") or -1) > 0 else None
            t["duration_ms"] = fj.get("duration") if (fj.get("duration") or -1) >= 0 else None
            t["tasks_summary"] = fj.get("tasks") or {}
            if sync_cluster:
                ckpt = _find_latest_checkpoint(jid) or t.get("last_checkpoint")
                if mapped != t.get("job_status") or ckpt != t.get("last_checkpoint"):
                    update(
                        "realtime_sync_task",
                        {"job_status": mapped, "last_checkpoint": ckpt},
                        "id=%s",
                        (int(t["id"]),),
                    )
                t["last_checkpoint"] = ckpt
            t["job_status"] = mapped
        else:
            t["flink_state"] = None
            t["start_time"] = None
            t["end_time"] = None
            t["duration_ms"] = None
            t["tasks_summary"] = {}

        st = t.get("job_status") or "draft"
        stats["total"] += 1
        if st in stats:
            stats[st] += 1
        enriched.append(t)

    return {
        "overview": cluster_overview(),
        "stats": stats,
        "tasks": enriched,
    }


def get_task_runtime(tid):
    """运维详情：聚合 Flink 算子流量、Checkpoint 历史与异常堆栈。"""
    task = get_task(tid)
    if not task:
        raise ValueError("同步任务不存在")

    jid = task.get("flink_job_id")
    runtime = {
        "connected": False,
        "job": None,
        "vertices": [],
        "checkpoints": {
            "counts": {"total": 0, "completed": 0, "failed": 0, "in_progress": 0, "restored": 0},
            "latest_completed": None,
            "latest_failed": None,
            "latest_restored": None,
            "history": [],
        },
        "exceptions": {
            "root_exception": None,
            "timestamp": None,
            "history": [],
        },
        "error": None,
    }

    if jid:
        try:
            detail = _http_json(f"{FLINK_REST_URL}/jobs/{jid}", timeout=5)
            runtime["connected"] = True
            raw_state = (detail.get("state") or "").upper()
            mapped = _STATE_MAP.get(raw_state, task.get("job_status") or "draft")
            runtime["job"] = {
                "jid": detail.get("jid"),
                "name": detail.get("name"),
                "state": raw_state,
                "start_time": detail.get("start-time") if (detail.get("start-time") or -1) > 0 else None,
                "end_time": detail.get("end-time") if (detail.get("end-time") or -1) > 0 else None,
                "duration_ms": detail.get("duration") if (detail.get("duration") or -1) >= 0 else None,
                "status_counts": detail.get("status-counts") or {},
            }
            verts = []
            for v in detail.get("vertices") or []:
                m = v.get("metrics") or {}
                verts.append({
                    "id": v.get("id"),
                    "name": v.get("name"),
                    "parallelism": v.get("parallelism"),
                    "status": v.get("status"),
                    "duration_ms": v.get("duration"),
                    "read_records": m.get("read-records", 0),
                    "write_records": m.get("write-records", 0),
                    "read_bytes": m.get("read-bytes", 0),
                    "write_bytes": m.get("write-bytes", 0),
                    "busy_ms": m.get("accumulated-busy-time", 0),
                    "idle_ms": m.get("accumulated-idle-time", 0),
                    "backpressured_ms": m.get("accumulated-backpressured-time", 0),
                })
            runtime["vertices"] = verts

            # Checkpoint 历史
            latest_ckpt_path = task.get("last_checkpoint")
            try:
                ck = _http_json(f"{FLINK_REST_URL}/jobs/{jid}/checkpoints", timeout=5)
                latest_block = ck.get("latest") or {}
                lc = latest_block.get("completed")
                if lc and lc.get("external_path"):
                    latest_ckpt_path = lc.get("external_path")
                history = []
                for item in (ck.get("history") or [])[:25]:
                    ext = item.get("external_path")
                    discarded = bool(item.get("discarded"))
                    status = item.get("status")
                    history.append({
                        "id": item.get("id"),
                        "status": status,
                        "checkpoint_type": item.get("checkpoint_type") or "CHECKPOINT",
                        "trigger_timestamp": item.get("trigger_timestamp"),
                        "latest_ack_timestamp": item.get("latest_ack_timestamp"),
                        "duration_ms": item.get("end_to_end_duration"),
                        "state_size": item.get("state_size") or item.get("checkpointed_size") or 0,
                        "external_path": ext,
                        "discarded": discarded,
                        "recoverable": bool(ext and status == "COMPLETED" and not discarded),
                    })
                runtime["checkpoints"] = {
                    "counts": ck.get("counts") or runtime["checkpoints"]["counts"],
                    "latest_completed": lc,
                    "latest_failed": latest_block.get("failed"),
                    "latest_restored": latest_block.get("restored"),
                    "history": history,
                }
            except Exception:
                pass

            # 异常堆栈
            try:
                ex = _http_json(f"{FLINK_REST_URL}/jobs/{jid}/exceptions", timeout=5)
                entries = ((ex.get("exception-history") or {}).get("entries")) or []
                ex_hist = []
                for ent in entries[:15]:
                    ex_hist.append({
                        "timestamp": ent.get("timestamp"),
                        "exception_name": ent.get("exceptionName"),
                        "task_name": ent.get("taskName"),
                        "location": ent.get("location"),
                        "stacktrace": ent.get("stacktrace"),
                    })
                runtime["exceptions"] = {
                    "root_exception": ex.get("root-exception") or None,
                    "timestamp": ex.get("timestamp") or None,
                    "history": ex_hist,
                }
            except Exception:
                pass

            update(
                "realtime_sync_task",
                {"job_status": mapped, "last_checkpoint": latest_ckpt_path},
                "id=%s",
                (int(tid),),
            )
            task = get_task(tid)
        except Exception as e:
            runtime["error"] = f"无法获取 Flink 作业详情: {e}"

    return {
        "task": task,
        "runtime": runtime,
    }


def refresh_task_status(tid):
    task = get_task(tid)
    if not task:
        raise ValueError("同步任务不存在")
    jid = task.get("flink_job_id")
    if not jid:
        return task
    try:
        detail = _http_json(f"{FLINK_REST_URL}/jobs/{jid}", timeout=5)
        raw_state = (detail.get("state") or "").upper()
        status = _STATE_MAP.get(raw_state, task.get("job_status") or "draft")
        ckpt = _find_latest_checkpoint(jid) or task.get("last_checkpoint")
        update(
            "realtime_sync_task",
            {"job_status": status, "last_checkpoint": ckpt},
            "id=%s",
            (int(tid),),
        )
    except Exception as e:
        update("realtime_sync_task", {"last_error": f"刷新状态失败: {e}"}, "id=%s", (int(tid),))
    return get_task(tid)


def stop_task(tid):
    task = get_task(tid)
    if not task:
        raise ValueError("同步任务不存在")
    jid = task.get("flink_job_id")
    if not jid:
        update("realtime_sync_task", {"job_status": "stopped"}, "id=%s", (int(tid),))
        return get_task(tid)
    ckpt = _find_latest_checkpoint(jid) or task.get("last_checkpoint")
    try:
        _http_json(f"{FLINK_REST_URL}/jobs/{jid}?mode=cancel", method="PATCH", timeout=8)
    except Exception as e:
        raise ValueError(f"停止 Flink 作业失败: {e}")
    update(
        "realtime_sync_task",
        {"job_status": "stopped", "last_checkpoint": ckpt, "last_error": ""},
        "id=%s",
        (int(tid),),
    )
    return get_task(tid)


def submit_task(tid, resume=True, checkpoint_path=None):
    """提交同步任务到 Flink 集群，支持从最近一次或指定历史检查点续跑。"""
    task = get_task(tid)
    if not task:
        raise ValueError("同步任务不存在")

    custom_ckpt = (checkpoint_path or "").strip() or None
    if custom_ckpt:
        if any(ch in custom_ckpt for ch in ("'", '"', "\n", "\r", ";")):
            raise ValueError("检查点路径包含非法字符")
        savepoint = custom_ckpt
    else:
        savepoint = task.get("last_checkpoint") if resume else None

    if task.get("mode") == "script":
        sql_text = (task.get("script_sql") or "").strip()
        if not sql_text:
            raise ValueError("脚本内容为空，无法提交")
        if task.get("source_id") and "'password' = '***'" in sql_text:
            source_cfg = source_service.get_source(int(task["source_id"]), with_secret=True)
            real_pwd = ((source_cfg or {}).get("password") or "").replace("'", "''")
            sql_text = sql_text.replace("'password' = '***'", f"'password' = '{real_pwd}'")
        # 清理脚本里可能残留的旧 savepoint 设置，按本次启动方式重新决定
        sql_text = re.sub(
            r"^\s*SET\s+'execution\.savepoint\.path'\s*=\s*'[^']*';\s*\n?",
            "",
            sql_text,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        if savepoint:
            sql_text = f"SET 'execution.savepoint.path' = '{savepoint}';\n" + sql_text
    else:
        source_cfg = source_service.get_source(int(task["source_id"]), with_secret=True) if task.get("source_id") else None
        sql_text = build_flink_sql(
            name=task["name"],
            source_cfg=source_cfg,
            database_name=task.get("database_name") or "ecommerce",
            tables_cfg=task.get("tables") or [],
            channel=task.get("channel") or {},
            task_id=task["id"],
            mask_secret=False,
            savepoint_path=savepoint,
        )

    # 先在 Kafka 中创建或确认主题；任一失败就中止提交，避免 Flink 写入不存在的主题
    ch = task.get("channel") or {}
    for item in task.get("tables") or []:
        tname = item.get("topic")
        if not tname:
            continue
        try:
            ensure_kafka_topic(
                tname,
                partitions=int(item.get("partitions") or 1),
                replication_factor=ch.get("topic_replication_factor", 1),
                retention_days=ch.get("topic_retention_days", 7),
            )
        except RuntimeError as e:
            msg = str(e)[-600:]
            update("realtime_sync_task", {"job_status": "failed", "last_error": msg}, "id=%s", (int(tid),))
            raise ValueError(msg)

    if not FLINK_SQL_CLIENT_CMD:
        raise ValueError(
            "当前后端未配置 FLINK_SQL_CLIENT_CMD（Flink SQL 客户端执行命令）。"
            "任务和 SQL 已保存，可在部署环境配置该变量后一键提交。"
        )

    cmd = shlex.split(FLINK_SQL_CLIENT_CMD)
    proc = subprocess.run(
        cmd,
        input=sql_text.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )
    out = (proc.stdout or b"").decode("utf-8", "replace")
    err = (proc.stderr or b"").decode("utf-8", "replace")
    m = _JOB_ID_RE.search(out + "\n" + err)
    if proc.returncode != 0 or not m:
        # 优先提取 Flink SQL 客户端的真实错误行，避免被 JVM 启动警告截断
        combined = (out + "\n" + err).splitlines()
        err_lines = [ln for ln in combined if ("[ERROR]" in ln or "Exception" in ln or "Caused by" in ln)]
        msg = ("\n".join(err_lines) if err_lines else (err or out or "提交失败"))[-600:]
        update("realtime_sync_task", {"job_status": "failed", "last_error": msg}, "id=%s", (int(tid),))
        raise ValueError(f"Flink 提交失败: {msg}")

    jid = m.group(1)
    update(
        "realtime_sync_task",
        {"flink_job_id": jid, "job_status": "running", "last_error": ""},
        "id=%s",
        (int(tid),),
    )
    return get_task(tid)


def _admin_client():
    return KafkaAdminClient(
        bootstrap_servers=KAFKA_ADMIN_BOOTSTRAP,
        client_id="duck-insight-realtime",
        request_timeout_ms=15000,
    )


def _cluster_topic_names():
    admin = _admin_client()
    try:
        return set(admin.list_topics())
    finally:
        admin.close()


def ensure_kafka_topic(name, partitions=1, replication_factor=1, retention_days=7):
    """通过 Kafka AdminClient 创建主题；已存在则返回 exists。

    失败抛出 RuntimeError，调用方据此中止提交，不再静默忽略。
    """
    retention_ms = max(1, int(retention_days or 7)) * 86400 * 1000
    try:
        admin = _admin_client()
    except Exception as e:
        raise RuntimeError(f"无法连接 Kafka（{KAFKA_ADMIN_BOOTSTRAP}）: {e}")
    try:
        if name in set(admin.list_topics()):
            return "exists"
        resp = admin.create_topics(
            [NewTopic(
                name=name,
                num_partitions=int(partitions or 1),
                replication_factor=int(replication_factor or 1),
                topic_configs={"retention.ms": str(retention_ms)},
            )],
            timeout_ms=15000,
        )
        for item in getattr(resp, "topic_errors", None) or []:
            topic, code = item[0], item[1]
            msg = item[2] if len(item) > 2 else ""
            if code == 0:
                return "created"
            if code == TOPIC_ALREADY_EXISTS:
                return "exists"
            raise RuntimeError(f"创建主题 {topic} 失败（错误码 {code}）{': ' + msg if msg else ''}")
        return "created"
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"创建主题 {name} 失败: {e}")
    finally:
        admin.close()


def list_topics():
    rows = query(
        "SELECT * FROM realtime_kafka_topic WHERE status=1 ORDER BY update_time DESC, id DESC"
    )
    items = [row_to_dict(r) for r in (rows or [])]
    known = {i["name"] for i in items}

    # 合并集群里已有但未登记在平台目录的主题；集群不可达时只返回平台目录
    try:
        for t in sorted(_cluster_topic_names()):
            if t.startswith("__") or t in known:
                continue
            items.append({
                "id": None,
                "name": t,
                "partitions": None,
                "replication_factor": None,
                "retention_ms": None,
                "source_task_id": None,
                "remark": "来自 Kafka 集群",
                "cluster_only": True,
            })
    except Exception:
        pass
    return items


def create_topic(body):
    name = (body.get("name") or "").strip()
    if not name or not _TOPIC_RE.match(name):
        raise ValueError("主题名只允许字母、数字、下划线和短横线，且长度不超过 128")
    partitions = max(1, min(32, int(body.get("partitions") or 1)))
    replication = max(1, min(3, int(body.get("replication_factor") or 1)))
    retention_days = max(1, min(90, int(body.get("retention_days") or 7)))
    retention_ms = retention_days * 86400 * 1000
    remark = (body.get("remark") or "").strip()

    exists = query("SELECT id FROM realtime_kafka_topic WHERE name=%s AND status=1", (name,), one=True)
    if exists:
        raise ValueError(f"主题 {name} 已存在")

    # 先在 Kafka 创建，成功后才登记到平台目录，失败不留下脏记录
    try:
        state = ensure_kafka_topic(name, partitions=partitions, replication_factor=replication, retention_days=retention_days)
    except RuntimeError as e:
        raise ValueError(str(e))

    uid, uname = _user()
    tid = insert("realtime_kafka_topic", {
        "name": name,
        "partitions": partitions,
        "replication_factor": replication,
        "retention_ms": retention_ms,
        "remark": remark,
        "user_id": uid,
        "username": uname,
        "status": 1,
    })
    row = query("SELECT * FROM realtime_kafka_topic WHERE id=%s", (tid,), one=True)
    d = row_to_dict(row)
    d["cluster_synced"] = True
    d["cluster_message"] = "已在 Kafka 创建" if state == "created" else "Kafka 中已存在，已登记到目录"
    return d


def delete_topic(name):
    execute("DELETE FROM realtime_kafka_topic WHERE name=%s", (name,))
