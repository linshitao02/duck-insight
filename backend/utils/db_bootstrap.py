# -*- coding: utf-8 -*-
import json
import os

import pymysql
from werkzeug.security import generate_password_hash

from config import DB_CONFIG, DB_ENGINE, ROOT_DIR, SQLITE_PATH
from utils.sql_dialect import convert_schema


def _split_sql(text):
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        lines.append(line)
    blob = "\n".join(lines)
    return [stmt.strip() for stmt in blob.split(";") if stmt.strip()]


def ensure_database():
    if DB_ENGINE == "sqlite":
        _ensure_sqlite()
    else:
        _ensure_mysql()
    seed_defaults()


def _ensure_sqlite():
    import sqlite3

    from utils.db import clear_column_cache, execute, query

    os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)
    conn = sqlite3.connect(SQLITE_PATH)
    sql_path = os.path.join(ROOT_DIR, "db", "schema.sql")
    try:
        sql_text = open(sql_path, encoding="utf-8").read()
        count = 0
        for stmt in convert_schema(sql_text):
            conn.execute(stmt)
            count += 1
        conn.commit()
        print(f"[数据库] SQLite {SQLITE_PATH}，已同步 {count} 条结构语句")
        conn.commit()
    finally:
        conn.close()
    clear_column_cache()
    orphan = query("SELECT COUNT(*) AS c FROM dataset WHERE project_id IS NULL AND status=1", one=True)
    orphan_n = orphan.get("c") if orphan else 0
    if orphan_n:
        row = query("SELECT id FROM data_project WHERE name=%s LIMIT 1", ("默认分析任务",), one=True)
        pid = row.get("id") if row else None
        if not pid:
            execute(
                "INSERT INTO data_project (name, description, scenario_code, username, status) VALUES (%s, %s, %s, %s, 1)",
                ("默认分析任务", "系统自动归集的历史数据表与逻辑数据集", "store_sales", "system"),
            )
            pid = query("SELECT id FROM data_project WHERE name=%s", ("默认分析任务",), one=True)["id"]
        execute("UPDATE dataset SET project_id=%s WHERE project_id IS NULL", (pid,))
        execute("UPDATE dataset_bundle SET project_id=%s WHERE project_id IS NULL", (pid,))
        print(f"[数据库] 已将历史数据归入全局任务 id={pid}")


def _ensure_mysql():
    db_name = DB_CONFIG["database"]
    conn = pymysql.connect(
        host=DB_CONFIG.get("host", "127.0.0.1"),
        user=DB_CONFIG.get("user", "root"),
        password=DB_CONFIG.get("password", "root"),
        port=int(DB_CONFIG.get("port", 3306)),
        charset="utf8mb4",
        autocommit=True,
    )
    sql_path = os.path.join(ROOT_DIR, "db", "schema.sql")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s",
                (db_name,),
            )
            exists = cur.fetchone()
            if not exists:
                print(f"[数据库] 创建 {db_name}")
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
            )
            conn.select_db(db_name)
            sql_text = open(sql_path, encoding="utf-8").read()
            count = 0
            for stmt in _split_sql(sql_text):
                head = stmt.lstrip().lower()
                if head.startswith("create database") or head.startswith("use "):
                    continue
                cur.execute(stmt)
                count += 1
            print(f"[数据库] 已同步表结构，执行 {count} 条语句")
    finally:
        conn.close()
    ensure_schema_updates()


def _column_exists(cur, db_name, table, column):
    cur.execute(
        """
        SELECT COUNT(*) AS c FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s
        """,
        (db_name, table, column),
    )
    row = cur.fetchone()
    return bool(row and (row[0] if not isinstance(row, dict) else row.get("c")))


def ensure_schema_updates():
    """为已有库补齐全局任务表与 project_id 字段。"""
    db_name = DB_CONFIG["database"]
    conn = pymysql.connect(
        host=DB_CONFIG.get("host", "127.0.0.1"),
        user=DB_CONFIG.get("user", "root"),
        password=DB_CONFIG.get("password", "root"),
        port=int(DB_CONFIG.get("port", 3306)),
        database=db_name,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS `data_project` (
                  `id` int NOT NULL AUTO_INCREMENT,
                  `name` varchar(128) NOT NULL,
                  `description` varchar(512) DEFAULT NULL,
                  `scenario_code` varchar(64) DEFAULT 'store_sales',
                  `cover_color` varchar(32) DEFAULT NULL,
                  `user_id` int DEFAULT NULL,
                  `username` varchar(64) DEFAULT NULL,
                  `status` tinyint DEFAULT 1,
                  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
                  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                  PRIMARY KEY (`id`),
                  KEY `idx_user` (`user_id`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS `data_source` (
                  `id` int NOT NULL AUTO_INCREMENT,
                  `name` varchar(128) NOT NULL,
                  `engine` varchar(32) DEFAULT 'mysql',
                  `host` varchar(128) NOT NULL,
                  `port` int DEFAULT 3306,
                  `db_user` varchar(128) DEFAULT NULL,
                  `db_password` varchar(255) DEFAULT NULL,
                  `database_name` varchar(128) DEFAULT NULL,
                  `remark` varchar(512) DEFAULT NULL,
                  `extra_json` longtext,
                  `user_id` int DEFAULT NULL,
                  `username` varchar(64) DEFAULT NULL,
                  `status` tinyint DEFAULT 1,
                  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
                  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                  PRIMARY KEY (`id`),
                  KEY `idx_user` (`user_id`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            for table, column, ddl in [
                ("dataset", "project_id", "int DEFAULT NULL COMMENT '所属数据空间'"),
                ("dataset_bundle", "project_id", "int DEFAULT NULL COMMENT '所属数据空间'"),
                ("dataset_bundle", "selected_fields_json", "longtext COMMENT '勾选展示字段'"),
                ("if_graph", "schedule_kind", "varchar(32) DEFAULT 'none'"),
                ("if_graph", "schedule_enabled", "tinyint DEFAULT 0"),
                ("if_graph", "schedule_last_at", "datetime DEFAULT NULL"),
                ("if_graph", "seed_key", "varchar(64) DEFAULT NULL COMMENT '系统种子流程的稳定标识；NULL=用户自建'"),
                ("prompt_template", "prompt_kind", "varchar(32) DEFAULT 'system' COMMENT 'question=用户短问题 system=系统提示词'"),
                ("bi_board", "layout_json", "longtext COMMENT 'FineBI 风格组件布局'"),
                ("bi_board", "scenario_code", "varchar(64) DEFAULT 'generic'"),
                ("bi_board", "is_template", "tinyint DEFAULT 0"),
                ("bi_board", "published", "tinyint DEFAULT 1"),
                ("bi_board", "cover_color", "varchar(32) DEFAULT NULL"),
                ("dataset_binding", "engine_path", "varchar(512) DEFAULT NULL COMMENT 'LabelEncoder/Scaler 等清洗状态'"),
                ("dataset", "origin_type", "varchar(32) DEFAULT 'file' COMMENT 'file=落地快照 mysql_live=每次读源表'"),
                ("dataset", "source_id", "int DEFAULT NULL COMMENT '活表数据源'"),
                ("dataset", "source_db", "varchar(128) DEFAULT NULL"),
                ("dataset", "source_table", "varchar(128) DEFAULT NULL"),
                ("chat_session", "summary", "text COMMENT '会话级滚动摘要（中长期记忆）'"),
                ("chat_session", "summary_upto", "int DEFAULT 0 COMMENT '摘要已覆盖到的消息 id'"),
                ("predict_job", "llm_question", "text COMMENT '用户短问题，可为空'"),
            ]:
                if not _column_exists(cur, db_name, table, column):
                    cur.execute(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {ddl}")
                    print(f"[数据库] 已为 {table} 添加字段 {column}")
            # 把历史无归属数据迁入默认全局任务
            cur.execute("SELECT COUNT(*) AS c FROM dataset WHERE project_id IS NULL AND status=1")
            orphan = cur.fetchone()
            orphan_n = orphan[0] if not isinstance(orphan, dict) else orphan.get("c")
            if orphan_n:
                cur.execute("SELECT id FROM data_project WHERE name=%s LIMIT 1", ("默认分析任务",))
                row = cur.fetchone()
                pid = row[0] if row and not isinstance(row, dict) else (row.get("id") if row else None)
                if not pid:
                    cur.execute(
                        """
                        INSERT INTO data_project (name, description, scenario_code, username, status)
                        VALUES (%s, %s, %s, %s, 1)
                        """,
                        ("默认分析任务", "系统自动归集的历史数据表与逻辑数据集", "store_sales", "system"),
                    )
                    pid = cur.lastrowid
                cur.execute("UPDATE dataset SET project_id=%s WHERE project_id IS NULL", (pid,))
                cur.execute("UPDATE dataset_bundle SET project_id=%s WHERE project_id IS NULL", (pid,))
                print(f"[数据库] 已将历史数据归入全局任务 id={pid}")
    finally:
        conn.close()


def seed_defaults():
    from config import DEFAULT_SYSTEM_PROMPT
    from utils.db import query, insert, execute, update

    if DB_ENGINE == "mysql" and not query("SELECT id FROM data_source WHERE status=1", one=True):
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
        print("[数据库] 已登记本机 MySQL 数据源")

    if not query("SELECT id FROM sys_user WHERE username=%s", ("admin",), one=True):
        insert("sys_user", {
            "username": "admin",
            "password": generate_password_hash("admin123"),
            "nickname": "管理员",
            "role": "admin",
            "status": 1,
        })
        print("[数据库] 已创建默认账号 admin / admin123")

    if not query("SELECT id FROM sys_scenario WHERE code=%s", ("store_sales",), one=True):
        insert("sys_scenario", {
            "code": "store_sales",
            "name": "商店销售",
            "description": "零售门店销量预测、促销分析与竞品影响洞察，默认适配 Rossmann 数据。",
            "icon": "Shop",
            "is_default": 1,
            "status": 1,
        })
        insert("sys_scenario", {
            "code": "generic",
            "name": "通用表格分析",
            "description": "任意 CSV/Excel 的清洗、建模与预测，便于拓展新的数据分析场景。",
            "icon": "DataBoard",
            "is_default": 0,
            "status": 1,
        })
    if not query("SELECT id FROM sys_scenario WHERE code=%s", ("power_trading",), one=True):
        insert("sys_scenario", {
            "code": "power_trading",
            "name": "电力交易分析",
            "description": "气象治理、负荷与风光预测、电价与报价建议、风险预警与日复盘。",
            "icon": "Lightning",
            "is_default": 0,
            "status": 1,
        })

    if not query("SELECT id FROM clean_rule WHERE name=%s", ("Rossmann销量清洗模板",), one=True):
        insert("clean_rule", {
            "name": "Rossmann销量清洗模板",
            "scenario_code": "store_sales",
            "description": "过滤零销量、拆解日期与促销月份、自动填补缺失、类别编码与标准化。",
            "steps_json": json.dumps([
                {"op": "filter", "column": "Sales", "operator": ">", "value": 0, "skip_if_missing": True},
                {"op": "parse_date", "column": "Date", "extract": ["year", "month", "day", "weekday"], "skip_if_missing": True},
                {"op": "split_flags", "column": "PromoInterval", "tokens": [
                    "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
                ], "prefix": "promo", "skip_if_missing": True},
                {"op": "drop_columns", "columns": ["Id", "Date", "Customers"], "skip_if_missing": True},
                {"op": "fill_missing", "strategy": "auto"},
                {"op": "label_encode", "columns": "auto_categorical"},
                {"op": "scale", "method": "standard", "columns": "auto_numeric"},
            ], ensure_ascii=False),
            "is_preset": 1,
            "username": "system",
            "status": 1,
        })
        insert("clean_rule", {
            "name": "通用快速清洗",
            "scenario_code": "generic",
            "description": "去重、自动填补缺失、类别编码。适合快速试用。",
            "steps_json": json.dumps([
                {"op": "drop_duplicates"},
                {"op": "fill_missing", "strategy": "auto"},
                {"op": "label_encode", "columns": "auto_categorical"},
            ], ensure_ascii=False),
            "is_preset": 1,
            "username": "system",
            "status": 1,
        })

    ollama_cfg = {
        "name": "本地Ollama-qwen3:4b",
        "model_name": "qwen3:4b",
        "api_key": "ollama",
        "base_url": "http://127.0.0.1:11434",
        "temperature": 0.4,
        "max_tokens": 2500,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "is_local_llm": 1,
        "is_default": 1,
        "username": "system",
        "status": 1,
    }
    if not query("SELECT id FROM llm_config", one=True):
        # 只预置本机 Ollama（无密钥，指向 127.0.0.1）。
        # 云端模型与 API Key 不内置，由用户在「LLM 配置」页面自行添加。
        insert("llm_config", ollama_cfg)
    else:
        row = query(
            "SELECT id FROM llm_config WHERE model_name=%s OR (is_local_llm=1 AND base_url LIKE %s) ORDER BY id DESC",
            ("qwen3:4b", "%11434%"),
            one=True,
        )
        update("llm_config", {"is_default": 0}, "1=1", [])
        if row:
            update("llm_config", {
                "name": "本地Ollama-qwen3:4b",
                "model_name": "qwen3:4b",
                "base_url": "http://127.0.0.1:11434",
                "api_key": "ollama",
                "is_local_llm": 1,
                "is_default": 1,
                "status": 1,
                "system_prompt": DEFAULT_SYSTEM_PROMPT,
                "max_tokens": 2500,
            }, "id=%s", (row["id"],))
        else:
            insert("llm_config", ollama_cfg)

    prompts = [
        (
            "特征重要性业务解读",
            "insight",
            "请根据材料直接撰写 Markdown 报告正文。禁止复述本说明、禁止输出思考过程、禁止出现「首先用户要求」这类套话。\n"
            "用五个二级标题：\n"
            "## 1. 本轮训练与关键特征\n## 2. 预测表现与误差形态\n"
            "## 3. 业务含义与调度交易影响\n## 4. 数据质量、泄漏与局限\n## 5. 可写入论文或附件的结论\n"
            "第 3、5 节涉及报价/调度必须写「需人工确认，系统未下单」。数字必须来自评估指标和特征重要性。\n\n"
            "【评估指标】\n{metrics}\n\n【特征重要性】\n{importance}\n\n"
            "【任务】\n{question}\n\n【知识库片段】\n{context}\n",
            0, 1, "system",
        ),
        (
            "预测结果解读",
            "predict",
            "请根据预测明细，总结整体水平、异常值、可能原因，并给出补货/排班/促销建议。"
            "不要编造输入中没有的数字。\n\n【预测结果】\n{predictions}\n\n【知识库片段】\n{context}\n",
            0, 0, "system",
        ),
        (
            "数据问答助手",
            "qa",
            "你是数据分析知识助手。使用简体中文，结论先行。\n"
            "若【知识库召回片段】中有相关内容，优先依据它回答，并在句末标注来源文件名。\n"
            "若召回为空、或片段与问题无关，不要拒答，直接依据你的通用知识给出完整、具体的回答，"
            "不要声称「暂无足够依据」。\n\n"
            "【知识库召回片段】\n{context}\n\n【用户问题】\n{question}",
            1, 1, "system",
        ),
        (
            "电力交易决策报告",
            "power_decision",
            "你是电力交易分析岗的决策助理。只输出最终报告正文，禁止输出思考过程。数字必须来自【评估指标】，禁止编造，交易建议必须注明需人工确认。\n"
            "按 5 节撰写，每节 3–6 句：\n"
            "1. 气象预测与数据治理\n2. 负荷与新能源出力\n3. 电价预测与交易支持\n"
            "4. 风险预警与决策支撑\n5. 模型迭代与工具建设\n\n"
            "【评估指标】\n{metrics}\n\n【预测切片】\n{predictions}\n\n【知识库片段】\n{context}\n",
            0, 1, "system",
        ),
        (
            "电价预测DAG解读",
            "price_forecast",
            "你是电力交易分析岗。只输出最终中文正文，禁止思考提纲。数字必须来自【评估指标】和【预测切片】，禁止编造。\n"
            "按 4 节写，每节 3–6 句：\n"
            "1. 本轮 DAG 做了什么（哪些上游模型、是否手填特征）\n"
            "2. 日前电价预测要点（趋势、高峰时段）\n"
            "3. 报价策略、套利建议、风险对冲（须写需交易员确认）\n"
            "4. 数据质量与后续注意点\n\n"
            "【评估指标】\n{metrics}\n\n【特征重要性】\n{importance}\n\n"
            "【预测切片】\n{predictions}\n\n【知识库片段】\n{context}\n\n【补充】\n{question}\n",
            0, 1, "system",
        ),
        (
            "预测风险预警报告",
            "predict_risk",
            "你是电力交易风险分析岗。只输出最终中文正文，禁止思考提纲。数字必须来自【预测切片】，禁止编造。\n"
            "按 4 节写，每节 3–6 句：\n"
            "1. 预测概况（模型、样本数、预测区间、输入是上游数据还是手填特征）\n"
            "2. 风险预警（高峰、极端值、与知识库规则对照）\n"
            "3. 报价注意点（报价带、高峰时段、申报口径）\n"
            "4. 处置建议（须写需交易员确认，系统未下单）\n\n"
            "【评估指标】\n{metrics}\n\n【特征重要性】\n{importance}\n\n"
            "【预测切片】\n{predictions}\n\n【知识库片段】\n{context}\n\n【补充】\n{question}\n",
            0, 1, "system",
        ),
        (
            "日前电价风险问询",
            "predict_risk",
            "根据本次负荷、风光出力与日前电价预测结果，结合市场规则给出风险预警与报价注意点。",
            0, 1, "question",
        ),
        (
            "高峰电价偏差问询",
            "predict_risk",
            "关注高峰小时电价是否异常偏高，结合新能源出力和负荷预测分析高峰时段的价格风险。",
            0, 0, "question",
        ),
        (
            "训练指标解读问询",
            "price_forecast",
            "根据日前电价模型的评估指标和特征重要性，给出报价策略、套利窗口与风险对冲建议。",
            0, 0, "question",
        ),
        (
            "极端天气训练解读",
            "power_train",
            "你是电力现货市场的气象驱动预测分析岗。只输出最终中文正文，禁止思考提纲。"
            "数字必须来自【评估指标】和【特征重要性】，禁止编造。\n"
            "按 4 节写，每节 3–6 句：\n"
            "1. 本轮训练做了什么（目标列、算法、关键气象特征）\n"
            "2. 出力或负荷形态与极端天气情景（热浪/寒潮/台风/强对流）\n"
            "3. 对调度与现货交易的影响（须写需人工确认，系统未下单）\n"
            "4. 负出力裁剪与后续数据注意\n\n"
            "【评估指标】\n{metrics}\n\n【特征重要性】\n{importance}\n\n"
            "【预测切片】\n{predictions}\n\n【知识库片段】\n{context}\n\n【补充】\n{question}\n",
            0, 1, "system",
        ),
        (
            "极端天气训练系统提示",
            "power_train",
            "你是电力现货市场的气象驱动预测分析岗。只输出最终中文正文，禁止思考提纲。"
            "数字必须来自【评估指标】和【特征重要性】，禁止编造。"
            "按 4 节写：1) 本轮训练与关键气象特征 2) 出力或负荷形态与极端情景 "
            "3) 对调度/交易的影响（须写需人工确认，系统未下单）4) 数据质量与后续注意。",
            0, 0, "system",
        ),
        (
            "光伏出力训练问询",
            "power_train",
            "光伏出力训练：辐照、热浪和午间高峰如何影响 solar_mw？消纳受阻要注意什么？",
            0, 0, "question",
        ),
        (
            "风电出力训练问询",
            "power_train",
            "风电出力训练：10米/100米风速、阵风和台风如何影响 wind_mw？切出风险要注意什么？",
            0, 0, "question",
        ),
        (
            "风光出力训练问询",
            "power_train",
            "风光合计出力训练：新能源高发如何挤压残余负荷？消纳与反调峰要注意什么？",
            0, 0, "question",
        ),
        (
            "用电负荷训练问询",
            "power_train",
            "用电负荷训练：气温、热浪和寒潮如何驱动 load_mw？晚高峰备电要注意什么？",
            0, 0, "question",
        ),
    ]
    for name, scene, content, qa_only, is_default, prompt_kind in prompts:
        row = query("SELECT id FROM prompt_template WHERE name=%s", (name,), one=True)
        payload = {
            "name": name,
            "scene": scene,
            "content": content,
            "placeholders": "{metrics},{importance},{predictions},{context},{question}",
            "is_default": is_default,
            "qa_only": qa_only,
            "prompt_kind": prompt_kind,
            "username": "system",
            "status": 1,
        }
        if not row:
            insert("prompt_template", payload)
        else:
            update("prompt_template", {
                "content": content,
                "scene": scene,
                "status": 1,
                "prompt_kind": prompt_kind,
            }, "id=%s", (row["id"],))
    execute("UPDATE prompt_template SET prompt_kind='system' WHERE prompt_kind IS NULL OR prompt_kind=''")
    try:
        from services.graph_service import ensure_extreme_weather_dags, ensure_live_mysql_dag, migrate_dag_llm_nodes
        from services import live_ops
        extreme = ensure_extreme_weather_dags()
        print(f"[DAG] 极端天气编排 {len(extreme or [])} 条")
        upgraded = migrate_dag_llm_nodes()
        print(f"[DAG] LLM 节点提示词升级 {upgraded} 条流程")
        if DB_ENGINE == "mysql":
            live = live_ops.ensure_live_ops(import_data=False)
            print(f"[实时库] {live.get('dataset') or live.get('source')}")
            live_dag = ensure_live_mysql_dag()
            print(f"[DAG] 实时库表训练 id={live_dag.get('id') if live_dag else None}")
        else:
            print("[数据库] 当前是 SQLite，跳过本机 MySQL 实时库")
    except Exception as e:
        print(f"[DAG] 默认流程初始化失败: {e}")
    try:
        from services.bi_service import ensure_power_monitor_board, ensure_realtime_board
        board = ensure_power_monitor_board()
        print(f"[BI] 监测看板 id={board.get('id') if board else None}")
        rt = ensure_realtime_board()
        print(f"[BI] 实时看板 id={rt.get('id') if rt else None}")
    except Exception as e:
        print(f"[BI] 监测看板初始化失败: {e}")
    execute("SELECT 1")
