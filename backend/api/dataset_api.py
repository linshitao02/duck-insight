# -*- coding: utf-8 -*-
import json

from flask import Blueprint, request

from services import dataset_service as svc
from utils.auth import login_required
from utils.paging import paginate_args
from utils.response import fail, ok

dataset_bp = Blueprint("dataset", __name__, url_prefix="/api/dataset")


@dataset_bp.route("/list", methods=["GET"])
@login_required
def list_ds():
    return ok(paginate_args(svc.list_datasets(
        request.args.get("keyword"),
        request.args.get("scenario"),
        request.args.get("project_id"),
    ), request.args))


@dataset_bp.route("/upload", methods=["POST"])
@login_required
def upload():
    files = request.files.getlist("files") or ([request.files.get("file")] if request.files.get("file") else [])
    files = [f for f in files if f]
    if not files:
        return fail("请选择文件")
    name = request.form.get("name")
    scenario = request.form.get("scenario") or "store_sales"
    remark = request.form.get("remark") or ""
    replace_id = request.form.get("dataset_id")
    project_id = request.form.get("project_id")
    try:
        if replace_id:
            row = svc.replace_upload(int(replace_id), files[0], name=name, remark=remark)
            return ok([row], "文件已替换并重新画像")
        if not project_id:
            return fail("请先进入数据集配置后再上传数据表")
        created = []
        for f in files:
            created.extend(svc.save_upload(
                f,
                name=name if len(files) == 1 else None,
                scenario=scenario,
                remark=remark,
                project_id=int(project_id),
            ))
        return ok(created, "上传成功")
    except Exception as e:
        return fail(str(e))


@dataset_bp.route("/<int:ds_id>", methods=["GET"])
@login_required
def detail(ds_id):
    ds = svc.get_dataset(ds_id)
    return ok(ds) if ds else fail("数据集不存在")


def _preview_args():
    try:
        n = int(request.args.get("n") or 40)
    except (TypeError, ValueError):
        n = 40
    try:
        skip = int(request.args.get("skip") or 0)
    except (TypeError, ValueError):
        skip = 0
    raw = request.args.get("filters")
    filters = []
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                filters = parsed
        except (TypeError, ValueError, json.JSONDecodeError):
            filters = []
    return n, skip, filters


@dataset_bp.route("/<int:ds_id>/preview", methods=["GET"])
@login_required
def preview(ds_id):
    try:
        n, skip, filters = _preview_args()
        return ok(svc.preview_dataset(ds_id, n, skip, filters))
    except Exception as e:
        return fail(str(e))


@dataset_bp.route("/<int:ds_id>/roles", methods=["PUT"])
@login_required
def roles(ds_id):
    body = request.get_json(silent=True) or {}
    return ok(svc.update_roles(ds_id, body.get("roles") or {}))


@dataset_bp.route("/<int:ds_id>/schema", methods=["PUT"])
@login_required
def schema(ds_id):
    body = request.get_json(silent=True) or {}
    try:
        return ok(svc.update_field_schema(
            ds_id,
            body.get("columns") or [],
            body.get("meta") or {},
        ), "字段配置已保存")
    except Exception as e:
        return fail(str(e))


@dataset_bp.route("/<int:ds_id>/meta", methods=["PUT"])
@login_required
def meta(ds_id):
    body = request.get_json(silent=True) or {}
    try:
        return ok(svc.update_dataset_meta(ds_id, body), "已更新")
    except Exception as e:
        return fail(str(e))


@dataset_bp.route("/<int:ds_id>", methods=["DELETE"])
@login_required
def remove(ds_id):
    svc.delete_dataset(ds_id)
    return ok(message="已删除")


@dataset_bp.route("/suggest-joins", methods=["POST"])
@login_required
def suggest():
    body = request.get_json(silent=True) or {}
    ids = body.get("dataset_ids") or []
    if len(ids) < 2:
        return fail("请至少选择两个数据集")
    return ok(svc.suggest_dataset_joins(ids))


@dataset_bp.route("/bundle", methods=["POST"])
@login_required
def create_bundle():
    body = request.get_json(silent=True) or {}
    if not body.get("dataset_ids"):
        return fail("请选择数据集")
    if not body.get("joins"):
        return fail("请配置至少一条关联字段")
    if not body.get("project_id"):
        return fail("请先进入数据集配置后再创建关联")
    try:
        bundle = svc.create_bundle(
            body.get("name") or "逻辑数据集",
            body.get("dataset_ids"),
            body.get("joins") or [],
            body.get("fact_dataset_id"),
            body.get("scenario_code") or "store_sales",
            body.get("remark") or "",
            project_id=body.get("project_id"),
            selected_fields=body.get("selected_fields"),
        )
        return ok(bundle, "编织完成")
    except Exception as e:
        return fail(str(e))


@dataset_bp.route("/bundle/<int:bid>/rebuild", methods=["PUT"])
@login_required
def bundle_rebuild(bid):
    body = request.get_json(silent=True) or {}
    try:
        row = svc.rebuild_bundle(
            bid,
            name=body.get("name"),
            dataset_ids=body.get("dataset_ids"),
            joins=body.get("joins"),
            fact_dataset_id=body.get("fact_dataset_id"),
            remark=body.get("remark"),
            selected_fields=body.get("selected_fields"),
        )
        return ok(row, "关联已更新并重新物化")
    except Exception as e:
        return fail(str(e))


@dataset_bp.route("/bundle/list", methods=["GET"])
@login_required
def bundle_list():
    return ok(paginate_args(svc.list_bundles(
        request.args.get("keyword"),
        request.args.get("scenario"),
        request.args.get("project_id"),
    ), request.args))


@dataset_bp.route("/bundle/<int:bid>", methods=["GET"])
@login_required
def bundle_detail(bid):
    row = svc.get_bundle(bid)
    return ok(row) if row else fail("不存在")


@dataset_bp.route("/bundle/<int:bid>/preview", methods=["GET"])
@login_required
def bundle_preview(bid):
    try:
        n, skip, filters = _preview_args()
        return ok(svc.preview_bundle(bid, n, skip, filters))
    except Exception as e:
        return fail(str(e))


@dataset_bp.route("/bundle/<int:bid>", methods=["DELETE"])
@login_required
def bundle_del(bid):
    svc.delete_bundle(bid)
    return ok(message="已删除")


@dataset_bp.route("/import-demo", methods=["POST"])
@login_required
def import_demo():
    body = request.get_json(silent=True) or {}
    if not body.get("project_id"):
        return fail("请先进入数据集配置后再导入示例")
    try:
        result = svc.import_rossmann_demo(
            int(body.get("max_rows") or 80000),
            project_id=body.get("project_id"),
        )
        return ok(result, "示例数据已导入并完成智能关联")
    except Exception as e:
        return fail(str(e))


@dataset_bp.route("/import-extreme-weather", methods=["POST"])
@login_required
def import_extreme_weather():
    body = request.get_json(silent=True) or {}
    try:
        from services.extreme_weather_pipeline import import_assets
        result = import_assets(
            force_rebuild=bool(body.get("force_rebuild")),
            project_id=body.get("project_id"),
        )
        return ok({
            "project_id": result["project"]["id"],
            "dataset_ids": {k: v["id"] for k, v in result["datasets"].items()},
            "bundle_id": result["bundle"]["id"],
            "rule_id": result["rule"]["id"],
            "binding_id": result["binding"]["id"],
            "binding_rows": result["binding"].get("n_rows"),
        }, "极端天气负荷/风光样本已导入并完成清洗绑定")
    except Exception as e:
        return fail(str(e))
