# -*- coding: utf-8 -*-
from flask import Blueprint, request

from services import graph_service as svc
from utils.auth import login_required
from utils.paging import paginate_args, parse_page
from utils.response import fail, ok

graph_bp = Blueprint("graph", __name__, url_prefix="/api/graph")


@graph_bp.route("/components", methods=["GET"])
@login_required
def components():
    return ok({"ops": svc.COMPONENTS, "categories": svc.CATEGORY_LABELS})


@graph_bp.route("/list", methods=["GET"])
@login_required
def list_graphs():
    rows = svc.list_graphs(request.args.get("scenario"), request.args.get("keyword"))
    return ok(paginate_args(rows, request.args))


@graph_bp.route("", methods=["POST"])
@login_required
def create():
    try:
        return ok(svc.save_graph(request.get_json(silent=True) or {}), "流程已保存")
    except Exception as e:
        return fail(str(e))


@graph_bp.route("/<int:gid>", methods=["GET"])
@login_required
def detail(gid):
    row = svc.get_graph(gid)
    return ok(row) if row else fail("流程不存在")


@graph_bp.route("/<int:gid>", methods=["PUT"])
@login_required
def update(gid):
    try:
        return ok(svc.save_graph(request.get_json(silent=True) or {}, gid), "已更新")
    except Exception as e:
        return fail(str(e))


@graph_bp.route("/<int:gid>/clone", methods=["POST"])
@login_required
def clone(gid):
    try:
        return ok(svc.clone_graph(gid, request.get_json(silent=True) or {}), "已复制编排")
    except Exception as e:
        return fail(str(e))


@graph_bp.route("/<int:gid>/run", methods=["POST"])
@login_required
def run(gid):
    try:
        return ok(svc.run_graph(gid), "流程已执行")
    except Exception as e:
        return fail(str(e))


@graph_bp.route("/<int:gid>/schedule", methods=["PUT", "PATCH"])
@login_required
def schedule(gid):
    try:
        return ok(svc.patch_schedule(gid, request.get_json(silent=True) or {}), "定时已更新")
    except Exception as e:
        return fail(str(e))


@graph_bp.route("/<int:gid>", methods=["DELETE"])
@login_required
def remove(gid):
    if not svc.get_graph(gid):
        return fail("流程不存在")
    svc.delete_graph(gid)
    return ok(True, "已删除")


@graph_bp.route("/batch-delete", methods=["POST"])
@login_required
def batch_remove():
    body = request.get_json(silent=True) or {}
    ids = body.get("ids") or body.get("graph_ids") or []
    if not ids:
        return fail("请选择要删除的编排")
    try:
        result = svc.delete_graphs(ids)
    except Exception as e:
        return fail(str(e))
    if not result.get("deleted"):
        return fail("没有可删除的编排")
    return ok(result, f"已删除 {result['deleted']} 条")


@graph_bp.route("/runs", methods=["GET"])
@login_required
def runs():
    gid = request.args.get("graph_id")
    paging = parse_page(request.args)
    graph_id = int(gid) if gid else None
    if paging:
        page, size = paging
        return ok(svc.list_runs(graph_id, page=page, page_size=size))
    limit = request.args.get("limit") or 50
    return ok(svc.list_runs(graph_id, limit=limit))


@graph_bp.route("/run/<int:rid>", methods=["GET"])
@login_required
def run_detail(rid):
    row = svc.get_run(rid)
    return ok(row) if row else fail("运行不存在")
