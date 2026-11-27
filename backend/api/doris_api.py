# -*- coding: utf-8 -*-
from flask import Blueprint, g, request

from services import doris_service as svc
from utils.auth import admin_required, login_required
from utils.response import fail, ok

doris_bp = Blueprint("doris", __name__, url_prefix="/api/doris")


@doris_bp.route("/overview", methods=["GET"])
@login_required
def overview():
    return ok(svc.get_overview())


@doris_bp.route("/tables", methods=["GET"])
@login_required
def list_tables():
    try:
        return ok(svc.list_tables())
    except Exception as e:
        return fail(str(e))


@doris_bp.route("/tables/<table_name>/preview", methods=["GET"])
@login_required
def preview_table(table_name):
    limit = request.args.get("limit", 20, type=int)
    try:
        return ok(svc.preview_table(table_name, limit=limit))
    except Exception as e:
        return fail(str(e))


@doris_bp.route("/routine-loads", methods=["GET"])
@login_required
def list_routine_loads():
    try:
        return ok(svc.list_routine_loads())
    except Exception as e:
        return fail(str(e))


@doris_bp.route("/routine-loads", methods=["POST"])
@admin_required
def create_routine_load():
    try:
        return ok(svc.create_routine_load(request.get_json(silent=True) or {}), "Routine Load 入库作业已创建")
    except Exception as e:
        return fail(str(e))


@doris_bp.route("/routine-loads/<job_name>/<action>", methods=["POST"])
@admin_required
def control_routine_load(job_name, action):
    try:
        data = svc.control_routine_load(job_name, action)
        labels = {"pause": "已暂停", "resume": "已恢复运行", "stop": "已停止"}
        return ok(data, labels.get(action, "操作成功"))
    except Exception as e:
        return fail(str(e))


@doris_bp.route("/sql/execute", methods=["POST"])
@login_required
def execute_sql():
    body = request.get_json(silent=True) or {}
    user = getattr(g, "user", None) or {}
    is_admin = (user.get("role") == "admin")
    try:
        return ok(svc.execute_sql(body.get("sql") or "", read_only=not is_admin))
    except Exception as e:
        return fail(str(e))
