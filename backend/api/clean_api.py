# -*- coding: utf-8 -*-
from flask import Blueprint, request, send_file

from services import clean_service as svc
from utils.auth import login_required
from utils.paging import paginate_args
from utils.response import fail, ok

clean_bp = Blueprint("clean", __name__, url_prefix="/api/clean")


@clean_bp.route("/ops", methods=["GET"])
@login_required
def ops():
    return ok(svc.list_ops())


@clean_bp.route("/rule/<int:rid>", methods=["GET"])
@login_required
def rule_detail(rid):
    row = svc.get_rule(rid)
    return ok(row) if row else fail("规则不存在")


@clean_bp.route("/source-schema", methods=["GET"])
@login_required
def source_schema():
    try:
        return ok(svc.get_source_schema(
            request.args.get("target_type") or "dataset",
            int(request.args.get("target_id")),
        ))
    except Exception as e:
        return fail(str(e))


@clean_bp.route("/rule/list", methods=["GET"])
@login_required
def rule_list():
    return ok(paginate_args(
        svc.list_rules(request.args.get("keyword"), request.args.get("scenario")),
        request.args,
    ))


@clean_bp.route("/rule", methods=["POST"])
@login_required
def rule_create():
    body = request.get_json(silent=True) or {}
    if not body.get("name"):
        return fail("请填写规则名称")
    return ok(svc.save_rule(body), "已保存")


@clean_bp.route("/rule/<int:rid>/copy", methods=["POST"])
@login_required
def rule_copy(rid):
    body = request.get_json(silent=True) or {}
    try:
        return ok(svc.copy_rule(rid, body.get("name")), "已复制")
    except Exception as e:
        return fail(str(e))


@clean_bp.route("/rule/<int:rid>", methods=["PUT"])
@login_required
def rule_update(rid):
    body = request.get_json(silent=True) or {}
    return ok(svc.save_rule(body, rid), "已更新")


@clean_bp.route("/rule/<int:rid>", methods=["DELETE"])
@login_required
def rule_delete(rid):
    try:
        svc.delete_rule(rid)
        return ok(message="已删除")
    except Exception as e:
        return fail(str(e))


@clean_bp.route("/probe-tokens", methods=["POST"])
@login_required
def probe_tokens():
    body = request.get_json(silent=True) or {}
    try:
        return ok(svc.probe_tokens(
            body.get("target_type") or "dataset",
            body.get("target_id"),
            body.get("column"),
            body.get("steps") or [],
            int(body.get("max_tokens") or 40),
        ))
    except Exception as e:
        return fail(str(e))


@clean_bp.route("/preview", methods=["POST"])
@login_required
def preview():
    body = request.get_json(silent=True) or {}
    try:
        return ok(svc.preview_clean(
            body.get("target_type") or "dataset",
            body.get("target_id"),
            body.get("steps") or [],
        ))
    except Exception as e:
        return fail(str(e))


@clean_bp.route("/bind", methods=["POST"])
@login_required
def bind():
    body = request.get_json(silent=True) or {}
    try:
        return ok(svc.bind_and_materialize(
            body.get("target_type") or "bundle",
            body.get("target_id"),
            body.get("rule_id"),
            body.get("name"),
        ), "绑定并物化成功")
    except Exception as e:
        return fail(str(e))


@clean_bp.route("/bind/list", methods=["GET"])
@login_required
def bind_list():
    include_transient = str(request.args.get("include_transient") or "").lower() in ("1", "true", "yes")
    return ok(paginate_args(
        svc.list_bindings(
            request.args.get("target_type"),
            request.args.get("target_id"),
            include_transient=include_transient,
        ),
        request.args,
    ))


@clean_bp.route("/bind/<int:bid>", methods=["GET"])
@login_required
def bind_detail(bid):
    row = svc.get_binding(bid)
    return ok(row) if row else fail("清洗快照不存在")


@clean_bp.route("/bind/<int:bid>/preview", methods=["GET"])
@login_required
def bind_preview(bid):
    try:
        return ok(svc.preview_binding(bid, request.args.get("n") or 50, request.args.get("skip") or 0))
    except Exception as e:
        return fail(str(e))


@clean_bp.route("/bind/<int:bid>/download", methods=["GET"])
@login_required
def bind_download(bid):
    try:
        path, filename = svc.binding_download(bid)
    except Exception as e:
        return fail(str(e))
    return send_file(path, as_attachment=True, download_name=filename, mimetype="text/csv")


@clean_bp.route("/bind/<int:bid>", methods=["DELETE"])
@login_required
def bind_del(bid):
    force = request.args.get("force") in ("1", "true", "True")
    try:
        svc.delete_binding(bid, force=force)
    except Exception as e:
        return fail(str(e))
    return ok(message="已删除")
