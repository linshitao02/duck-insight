# -*- coding: utf-8 -*-
from flask import Blueprint, request

from services import project_service as svc
from utils.auth import login_required
from utils.paging import paginate_args
from utils.response import fail, ok

project_bp = Blueprint("project", __name__, url_prefix="/api/project")


@project_bp.route("/list", methods=["GET"])
@login_required
def list_projects():
    return ok(paginate_args(
        svc.list_projects(request.args.get("keyword"), request.args.get("scenario")),
        request.args,
    ))


@project_bp.route("", methods=["POST"])
@login_required
def create():
    body = request.get_json(silent=True) or {}
    try:
        return ok(svc.create_project(body), "数据集配置已创建")
    except Exception as e:
        return fail(str(e))


@project_bp.route("/<int:pid>", methods=["GET"])
@login_required
def detail(pid):
    row = svc.get_project(pid)
    return ok(row) if row else fail("数据集配置不存在")


@project_bp.route("/<int:pid>", methods=["PUT"])
@login_required
def update(pid):
    body = request.get_json(silent=True) or {}
    try:
        return ok(svc.update_project(pid, body), "已更新")
    except Exception as e:
        return fail(str(e))


@project_bp.route("/<int:pid>", methods=["DELETE"])
@login_required
def remove(pid):
    svc.delete_project(pid)
    return ok(message="已删除")
