# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from utils.db import query, update


def _parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value)[:19])
    except Exception:
        return None


def is_due(kind, last_at):
    kind = kind or "none"
    if kind in ("none", "", None):
        return False
    now = datetime.now()
    last = _parse_dt(last_at)
    if kind == "hourly":
        return last is None or now - last >= timedelta(hours=1)
    if kind == "every_6h":
        return last is None or now - last >= timedelta(hours=6)
    if kind == "daily":
        if last is None:
            return now.hour >= 8
        return last.date() < now.date() and now.hour >= 8
    return False


def claim_due_schedules():
    """把到期编排立刻记 last_at，避免卡住登录；实际执行由调用方另开线程。"""
    rows = query("SELECT * FROM if_graph WHERE status=1 AND schedule_enabled=1") or []
    claimed = []
    for g in rows:
        if not is_due(g.get("schedule_kind"), g.get("schedule_last_at")):
            continue
        running = query(
            "SELECT id FROM if_graph_run WHERE graph_id=%s AND status='running' ORDER BY id DESC",
            (g["id"],),
            one=True,
        )
        if running:
            continue
        update("if_graph", {"schedule_last_at": datetime.now()}, "id=%s", (g["id"],))
        claimed.append({"id": g["id"], "name": g.get("name")})
    return claimed


def run_due_schedules():
    from services.graph_service import run_graph
    claimed = claim_due_schedules()
    ran = []
    for item in claimed:
        try:
            result = run_graph(item["id"], trigger="schedule")
            ran.append({"id": item["id"], "name": item.get("name"), "run": (result or {}).get("id")})
        except Exception as e:
            print(f"[调度] 流程 {item.get('name')} 失败: {e}")
    return ran
