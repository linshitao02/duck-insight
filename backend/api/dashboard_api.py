# -*- coding: utf-8 -*-
from flask import Blueprint, g

from utils.auth import login_required
from utils.db import query
from utils.response import ok

dash_bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")


@dash_bp.route("/overview", methods=["GET"])
@login_required
def overview():
    user = g.user
    cond = ""
    args = []
    if user.get("role") != "admin":
        cond = " WHERE user_id=%s"
        args = [user.get("id")]

    def count(table, extra=""):
        has_user = "user_id" in _cols(table)
        sql = f"SELECT COUNT(*) AS c FROM `{table}` WHERE 1=1"
        local_args = []
        if has_user and user.get("role") != "admin":
            sql += " AND user_id=%s"
            local_args.append(user.get("id"))
        if extra:
            sql += " " + extra
        row = query(sql, local_args, one=True)
        return int(row["c"] if row else 0)

    stats = {
        "datasets": count("dataset", "AND status=1"),
        "bundles": count("dataset_bundle"),
        "rules": query("SELECT COUNT(*) AS c FROM clean_rule WHERE status=1", one=True)["c"],
        "models": count("train_job"),
        "success_models": count("train_job", "AND status='success'"),
        "predicts": count("predict_job"),
        "reports": count("insight_report"),
        "docs": 0,
    }
    try:
        from services.rag_service import get_rag_service
        stats["docs"] = get_rag_service().status().get("file_count") or 0
    except Exception:
        pass

    recent_jobs = query(
        "SELECT id, name, model_type, status, progress, metrics_json, create_time FROM train_job"
        + (" WHERE user_id=%s" if cond else "")
        + " ORDER BY id DESC LIMIT 6",
        args,
    )
    # 近 7 日训练次数：以数据库当天为锚点，补齐无数据的日期为 0，
    # 保证「今天」始终出现在横轴上（此前只返回有记录的日期，当天为 0 时会被整段省略）。
    from datetime import datetime, timedelta
    today = query("SELECT CURDATE() AS d", one=True)["d"]
    if isinstance(today, str):
        today = datetime.strptime(today[:10], "%Y-%m-%d").date()
    elif isinstance(today, datetime):
        today = today.date()
    start = today - timedelta(days=6)
    where = " WHERE create_time >= %s"
    trend_args = [start]
    if user.get("role") != "admin":
        where += " AND user_id=%s"
        trend_args.append(user.get("id"))
    rows = query(
        "SELECT DATE(create_time) AS d, COUNT(*) AS c FROM train_job"
        + where
        + " GROUP BY DATE(create_time)",
        trend_args,
    )
    by_day = {str(r["d"]): int(r["c"] or 0) for r in rows}
    trend = [
        {
            "date": str(start + timedelta(days=i)),
            "count": by_day.get(str(start + timedelta(days=i)), 0),
        }
        for i in range(7)
    ]

    from utils.jsonx import row_to_dict
    return ok({
        "stats": {k: int(v or 0) for k, v in stats.items()},
        "recent_jobs": [row_to_dict(r) for r in recent_jobs],
        "trend": trend,
    })


def _cols(table):
    rows = query(f"SHOW COLUMNS FROM `{table}`")
    return {r["Field"] for r in rows}
