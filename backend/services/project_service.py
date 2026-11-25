# -*- coding: utf-8 -*-
from flask import g

from utils.db import delete, insert, query, update
from utils.jsonx import row_to_dict


def _user():
    return getattr(g, "user", {}) or {}


def serialize(row):
    if not row:
        return None
    data = row_to_dict(row)
    # 附带统计
    pid = data.get("id")
    ds = query("SELECT COUNT(*) AS c FROM dataset WHERE project_id=%s AND status=1", (pid,), one=True)
    bd = query("SELECT COUNT(*) AS c FROM dataset_bundle WHERE project_id=%s AND status=1", (pid,), one=True)
    data["dataset_count"] = int((ds or {}).get("c") or 0)
    data["bundle_count"] = int((bd or {}).get("c") or 0)
    return data


def list_projects(keyword=None, scenario=None):
    sql = "SELECT * FROM data_project WHERE status=1"
    args = []
    user = _user()
    if user.get("role") != "admin":
        sql += " AND user_id=%s"
        args.append(user.get("id"))
    if scenario:
        sql += " AND scenario_code=%s"
        args.append(scenario)
    if keyword:
        sql += " AND name LIKE %s"
        args.append(f"%{keyword}%")
    sql += " ORDER BY id DESC"
    return [serialize(r) for r in query(sql, args)]


def get_project(pid):
    row = query("SELECT * FROM data_project WHERE id=%s AND status=1", (pid,), one=True)
    return serialize(row)


def create_project(payload):
    user = _user()
    name = (payload.get("name") or "").strip()
    if not name:
        raise ValueError("请填写数据集配置名称")
    pid = insert("data_project", {
        "name": name,
        "description": payload.get("description") or "",
        "scenario_code": payload.get("scenario_code") or "store_sales",
        "cover_color": payload.get("cover_color") or "",
        "user_id": user.get("id"),
        "username": user.get("username"),
        "status": 1,
    })
    return get_project(pid)


def update_project(pid, payload):
    if not get_project(pid):
        raise ValueError("数据集配置不存在")
    data = {}
    for k in ("name", "description", "scenario_code", "cover_color"):
        if k in payload and payload[k] is not None:
            data[k] = payload[k]
    if data:
        update("data_project", data, "id=%s", (pid,))
    return get_project(pid)


def delete_project(pid):
    """软删数据集配置；其下表与逻辑集一并软删。"""
    if not get_project(pid):
        return
    update("data_project", {"status": 0}, "id=%s", (pid,))
    update("dataset", {"status": 0}, "project_id=%s", (pid,))
    update("dataset_bundle", {"status": 0}, "project_id=%s", (pid,))
