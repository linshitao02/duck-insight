# -*- coding: utf-8 -*-
from flask import Blueprint, request

from services import realtime_service as svc
from utils.auth import admin_required, login_required
from utils.response import fail, ok

realtime_bp = Blueprint("realtime", __name__, url_prefix="/api/realtime")


@realtime_bp.route("/overview", methods=["GET"])
@login_required
def overview():
    return ok(svc.cluster_overview())


@realtime_bp.route("/ops/tasks", methods=["GET"])
@login_required
def ops_tasks():
    sync_cluster = str(request.args.get("sync", "")).lower() in ("1", "true", "yes")
    return ok(svc.list_ops_tasks(sync_cluster=sync_cluster))


@realtime_bp.route("/tasks", methods=["GET"])
@login_required
def list_tasks():
    return ok(svc.list_tasks())


@realtime_bp.route("/tasks/<int:tid>", methods=["GET"])
@login_required
def get_task(tid):
    row = svc.get_task(tid)
    if not row:
        return fail("同步任务不存在", code=404)
    return ok(row)


@realtime_bp.route("/tasks", methods=["POST"])
@admin_required
def create_task():
    try:
        return ok(svc.save_task(request.get_json(silent=True) or {}), "同步任务已保存")
    except Exception as e:
        return fail(str(e))


@realtime_bp.route("/tasks/<int:tid>", methods=["PUT"])
@admin_required
def update_task(tid):
    try:
        return ok(svc.save_task(request.get_json(silent=True) or {}, tid=tid), "同步任务已更新")
    except Exception as e:
        return fail(str(e))


@realtime_bp.route("/tasks/<int:tid>", methods=["DELETE"])
@admin_required
def delete_task(tid):
    try:
        svc.delete_task(tid)
        return ok(None, "已删除")
    except Exception as e:
        return fail(str(e))


@realtime_bp.route("/tasks/preview-sql", methods=["POST"])
@login_required
def preview_sql():
    try:
        return ok(svc.preview_sql(request.get_json(silent=True) or {}))
    except Exception as e:
        return fail(str(e))


@realtime_bp.route("/tasks/<int:tid>/convert-script", methods=["POST"])
@admin_required
def convert_script(tid):
    try:
        return ok(svc.convert_to_script(tid), "已转为脚本模式")
    except Exception as e:
        return fail(str(e))


@realtime_bp.route("/tasks/<int:tid>/submit", methods=["POST"])
@admin_required
def submit_task(tid):
    body = request.get_json(silent=True) or {}
    resume = body.get("resume", True)
    checkpoint_path = body.get("checkpoint_path") or None
    try:
        return ok(svc.submit_task(tid, resume=bool(resume), checkpoint_path=checkpoint_path), "作业已提交")
    except Exception as e:
        return fail(str(e))


@realtime_bp.route("/tasks/<int:tid>/stop", methods=["POST"])
@admin_required
def stop_task(tid):
    try:
        return ok(svc.stop_task(tid), "作业已停止")
    except Exception as e:
        return fail(str(e))


@realtime_bp.route("/tasks/<int:tid>/refresh", methods=["POST"])
@login_required
def refresh_task(tid):
    try:
        return ok(svc.refresh_task_status(tid))
    except Exception as e:
        return fail(str(e))


@realtime_bp.route("/tasks/<int:tid>/runtime", methods=["GET"])
@login_required
def task_runtime(tid):
    try:
        return ok(svc.get_task_runtime(tid))
    except Exception as e:
        return fail(str(e))


@realtime_bp.route("/source/<int:sid>/schema", methods=["POST"])
@login_required
def source_schema(sid):
    body = request.get_json(silent=True) or {}
    try:
        data = svc.fetch_source_table_schemas(
            source_id=sid,
            database_name=body.get("database_name") or "",
            tables=body.get("tables") or [],
        )
        return ok(data)
    except Exception as e:
        return fail(str(e))


@realtime_bp.route("/topics", methods=["GET"])
@login_required
def list_topics():
    return ok(svc.list_topics())


@realtime_bp.route("/topics", methods=["POST"])
@admin_required
def create_topic():
    try:
        return ok(svc.create_topic(request.get_json(silent=True) or {}), "主题已创建")
    except Exception as e:
        return fail(str(e))


@realtime_bp.route("/topics/<name>", methods=["DELETE"])
@admin_required
def delete_topic(name):
    try:
        svc.delete_topic(name)
        return ok(None, "已删除")
    except Exception as e:
        return fail(str(e))
