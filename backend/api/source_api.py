# -*- coding: utf-8 -*-
from flask import Blueprint, request

from services import source_service as svc
from utils.auth import login_required
from utils.paging import paginate_args
from utils.response import fail, ok

source_bp = Blueprint("datasource", __name__, url_prefix="/api/datasource")


@source_bp.route("/list", methods=["GET"])
@login_required
def list_sources():
    return ok(paginate_args(svc.list_sources(), request.args))


@source_bp.route("", methods=["POST"])
@login_required
def create():
    try:
        return ok(svc.save_source(request.get_json(silent=True) or {}), "数据源已保存")
    except Exception as e:
        return fail(str(e))


@source_bp.route("/test", methods=["POST"])
@login_required
def test_form():
    body = request.get_json(silent=True) or {}
    try:
        return ok(svc.test_connection(body, sid=body.get("id")), "连接成功")
    except Exception as e:
        return fail(str(e))


@source_bp.route("/<int:sid>", methods=["GET"])
@login_required
def detail(sid):
    row = svc.get_source(sid)
    return ok(row) if row else fail("数据源不存在")


@source_bp.route("/<int:sid>", methods=["PUT"])
@login_required
def update(sid):
    try:
        return ok(svc.save_source(request.get_json(silent=True) or {}, sid), "已更新")
    except Exception as e:
        return fail(str(e))


@source_bp.route("/<int:sid>", methods=["DELETE"])
@login_required
def remove(sid):
    if not svc.get_source(sid):
        return fail("数据源不存在")
    svc.delete_source(sid)
    return ok(True, "已删除")


@source_bp.route("/<int:sid>/test", methods=["POST"])
@login_required
def test_saved(sid):
    try:
        return ok(svc.test_connection(request.get_json(silent=True) or {}, sid=sid), "连接成功")
    except Exception as e:
        return fail(str(e))


@source_bp.route("/<int:sid>/databases", methods=["GET"])
@login_required
def databases(sid):
    try:
        return ok(svc.list_databases(sid))
    except Exception as e:
        return fail(str(e))


@source_bp.route("/<int:sid>/tables", methods=["GET", "POST"])
@login_required
def tables(sid):
    body = request.get_json(silent=True) or {}
    dbs = body.get("databases") or request.args.getlist("databases")
    if not dbs and request.args.get("databases"):
        dbs = [x for x in request.args.get("databases").split(",") if x]
    try:
        return ok(svc.list_tables(sid, dbs))
    except Exception as e:
        return fail(str(e))


@source_bp.route("/<int:sid>/import", methods=["POST"])
@login_required
def import_tables(sid):
    body = request.get_json(silent=True) or {}
    if not body.get("project_id"):
        return fail("请先进入数据集配置后再导入")
    try:
        result = svc.import_tables(
            sid,
            body.get("project_id"),
            body.get("tables") or [],
            name=body.get("name"),
            remark=body.get("remark") or "",
            scenario=body.get("scenario") or "generic",
            max_rows=int(body.get("max_rows") or svc.MAX_IMPORT_ROWS),
        )
        msg = f"已导入 {result.get('count') or 0} 张表"
        if result.get("errors"):
            msg += f"，{len(result['errors'])} 张失败"
        return ok(result, msg)
    except Exception as e:
        return fail(str(e))


@source_bp.route("/<int:sid>/preview", methods=["POST"])
@login_required
def preview_table(sid):
    body = request.get_json(silent=True) or {}
    try:
        return ok(svc.preview_table(
            sid,
            body.get("database") or body.get("source_db"),
            body.get("table") or body.get("source_table"),
            n=int(body.get("n") or 40),
            skip=int(body.get("skip") or 0),
            filters=body.get("filters"),
        ))
    except Exception as e:
        return fail(str(e))


@source_bp.route("/<int:sid>/attach-live", methods=["POST"])
@login_required
def attach_live(sid):
    body = request.get_json(silent=True) or {}
    if not body.get("project_id"):
        return fail("请先进入数据集配置后再挂接")
    try:
        row = svc.attach_live_dataset(
            sid,
            body.get("project_id"),
            body.get("database") or body.get("source_db"),
            body.get("table") or body.get("source_table"),
            name=body.get("name"),
            remark=body.get("remark") or "",
            scenario=body.get("scenario") or "generic",
        )
        return ok(row, "已挂接实时表，预览与训练会读当前库表")
    except Exception as e:
        return fail(str(e))
