# -*- coding: utf-8 -*-
"""导入日前电价离线数据、训练风电/光伏（复用已有负荷），并跑通电价预测 DAG + 大模型解读。"""
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
        from services.extreme_weather_pipeline import (
            JOB_PRICE, import_assets, start_models, wait_jobs,
        )
        from services.graph_service import ensure_extreme_weather_dags, run_graph

        print("[1/4] 导入气象/负荷/风光/电价数据…")
        imported = import_assets(force_rebuild=False)
        print(json.dumps({
            "project_id": imported["project"]["id"],
            "bundle_id": imported["bundle"]["id"],
            "binding_id": imported["binding"]["id"],
            "binding_rows": imported["binding"].get("n_rows"),
            "dataset_ids": {k: v["id"] for k, v in imported["datasets"].items()},
        }, ensure_ascii=False, indent=2))

        print("[2/4] 训练负荷/风光/风电/光伏（已成功的任务会复用）…")
        jobs = start_models(imported, reuse=True)
        pending = [j for j in jobs if (j or {}).get("status") not in ("success", "failed")]
        if pending:
            jobs = wait_jobs(jobs, timeout=1200)
        print(json.dumps([{
            "id": j.get("id"),
            "name": j.get("name"),
            "target_col": j.get("target_col"),
            "status": j.get("status"),
            "metrics": j.get("metrics"),
        } for j in jobs], ensure_ascii=False, indent=2, default=str))
        failed = [j for j in jobs if (j or {}).get("status") != "success"]
        if failed:
            raise SystemExit("上游模型训练失败: " + ", ".join(j.get("name") or str(j.get("id")) for j in failed))

        print("[3/4] 写入风电/光伏/电价 DAG…")
        dags = ensure_extreme_weather_dags()
        price = next((gph for gph in dags if gph.get("name") == "日前电价预测编排"), None)
        if not price:
            raise SystemExit("未找到「日前电价预测编排」")
        print(f"  price dag id={price['id']} nodes={price.get('node_count')}")

        print("[4/4] 运行日前电价预测 DAG（模型预测 → LLM 风险预警）…")
        run = run_graph(price["id"], trigger="setup")
        print(json.dumps({
            "run_id": run.get("id"),
            "status": run.get("status"),
            "duration_sec": run.get("duration_sec"),
            "error": run.get("error_message"),
            "log": run.get("log_text"),
            "report_id": (run.get("result") or {}).get("report_id"),
            "predict_job_id": (run.get("result") or {}).get("predict_job_id"),
            "predict_summary": (run.get("result") or {}).get("predict_summary"),
            "llm_report_head": ((run.get("result") or {}).get("llm_report") or "")[:800],
        }, ensure_ascii=False, indent=2, default=str))
        if run.get("status") != "success":
            raise SystemExit(f"DAG 失败: {run.get('error_message')}")
        print("OK 电价预测流程已跑通")


if __name__ == "__main__":
    main()
