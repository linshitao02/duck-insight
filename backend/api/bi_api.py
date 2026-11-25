# -*- coding: utf-8 -*-
from flask import Blueprint, request

from services import bi_service as svc
from utils.auth import login_required
from utils.paging import paginate_args
from utils.response import fail, ok

bi_bp = Blueprint("bi", __name__, url_prefix="/api/bi")


@bi_bp.route("/catalog", methods=["GET"])
@login_required
def catalog():
    return ok(svc.catalog())


@bi_bp.route("/sources", methods=["GET"])
@login_required
def sources():
    return ok(svc.list_sources(request.args.get("project_id"), request.args.get("scenario")))


@bi_bp.route("/source/<kind>/<int:sid>", methods=["GET"])
@login_required
def source_detail(kind, sid):
    try:
        return ok(svc.describe_source(kind, sid))
    except Exception as e:
        return fail(str(e))


@bi_bp.route("/list", methods=["GET"])
@login_required
def list_boards():
    rows = svc.list_boards(request.args.get("scenario"))
    return ok(paginate_args(rows, request.args))


@bi_bp.route("", methods=["POST"])
@login_required
def create():
    try:
        body = request.get_json(silent=True) or {}
        template = body.get("template")
        source = body.get("source") or {}
        if template and source.get("id"):
            body["layout"] = svc.apply_template(template, source, body.get("name"))
            if not body.get("scenario_code"):
                body["scenario_code"] = "power_trading" if template in ("power_monitor", "realtime") else body.get("scenario_code")
        elif body.get("auto") and source.get("id"):
            rec = svc.recommend_layout(source.get("kind") or "dataset", source["id"], body.get("name"))
            body["layout"] = rec
        return ok(svc.save_board(body), "看板已创建")
    except Exception as e:
        return fail(str(e))


@bi_bp.route("/recommend", methods=["POST"])
@login_required
def recommend():
    body = request.get_json(silent=True) or {}
    source = body.get("source") or {}
    if not source.get("id"):
        return fail("请选择数据表或逻辑数据集")
    try:
        return ok(svc.recommend_layout(source.get("kind") or "dataset", source["id"], body.get("name")))
    except Exception as e:
        return fail(str(e))


@bi_bp.route("/<int:bid>", methods=["GET"])
@login_required
def detail(bid):
    row = svc.get_board(bid)
    return ok(row) if row else fail("看板不存在")


@bi_bp.route("/<int:bid>", methods=["PUT"])
@login_required
def update(bid):
    try:
        return ok(svc.save_board(request.get_json(silent=True) or {}, bid), "已更新")
    except Exception as e:
        return fail(str(e))


@bi_bp.route("/<int:bid>", methods=["DELETE"])
@login_required
def remove(bid):
    svc.delete_board(bid)
    return ok(message="已删除")


@bi_bp.route("/query", methods=["POST"])
@login_required
def ad_hoc_query():
    try:
        return ok(svc.query_ad_hoc(request.get_json(silent=True) or {}))
    except Exception as e:
        return fail(str(e))


@bi_bp.route("/<int:bid>/query", methods=["GET", "POST"])
@login_required
def query_board(bid):
    try:
        if request.method == "POST":
            body = request.get_json(silent=True) or {}
            return ok(svc.query_board_layout(
                bid,
                grain=body.get("grain"),
                filters=body.get("filters"),
                widget_id=body.get("widget_id"),
            ))
        metrics = request.args.get("metrics")
        horizons = request.args.get("horizons")
        return ok(svc.query_board(
            bid,
            grain=request.args.get("grain"),
            metrics=metrics.split(",") if metrics else None,
            horizons=horizons.split(",") if horizons else None,
        ))
    except Exception as e:
        return fail(str(e))
