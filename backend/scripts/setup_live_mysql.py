# -*- coding: utf-8 -*-
"""建实时库、挂接活表、写入新 DAG 并跑通光伏训练。"""
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import create_app
from flask import g
from utils.db import query
from utils.db_bootstrap import ensure_database


def main():
    ensure_database()
    app = create_app()
    with app.app_context():
        g.user = query("SELECT * FROM sys_user WHERE username=%s", ("admin",), one=True) or {
            "id": 1, "username": "admin", "role": "admin",
        }
        from services import live_ops
        from services.graph_service import LIVE_DAG_NAME, ensure_live_mysql_dag, run_graph

        print("[1/3] 建库导表并登记实时数据源…")
        pack = live_ops.ensure_live_ops(import_data=True)
        print(json.dumps(pack, ensure_ascii=False, indent=2, default=str))

        print("[2/3] 写入实时库表训练 DAG…")
        dag = ensure_live_mysql_dag(refresh_graph=True)
        if not dag:
            raise SystemExit("实时 DAG 未创建，请检查数据源与清洗规则")
        print(f"  dag id={dag.get('id')} name={dag.get('name')}")

        print("[3/3] 运行 DAG（数据源接入 → 极端天气电力质控-实时 → 训练）…")
        run = run_graph(dag["id"], trigger="setup")
        print(json.dumps({
            "run_id": run.get("id"),
            "status": run.get("status"),
            "duration_sec": run.get("duration_sec"),
            "error": run.get("error_message"),
            "log": run.get("log_text"),
            "job_id": (run.get("result") or {}).get("job_id"),
        }, ensure_ascii=False, indent=2, default=str))
        if run.get("status") != "success":
            raise SystemExit(f"DAG 失败: {run.get('error_message')}")
        print(f"OK {LIVE_DAG_NAME} 已跑通")


if __name__ == "__main__":
    main()
