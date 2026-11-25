# -*- coding: utf-8 -*-
from flask import Blueprint, request, send_file

from services import insight_service, model_service
from services.train_export import build_export_zip, build_insight_markdown, export_insight_report
from trainers.zoo import list_zoo
from utils.auth import login_required
from utils.paging import paginate_args
from utils.response import fail, ok

model_bp = Blueprint("model", __name__, url_prefix="/api/model")


@model_bp.route("/zoo", methods=["GET"])
@login_required
def zoo():
    return ok(list_zoo())


@model_bp.route("/list", methods=["GET"])
@login_required
def job_list():
    return ok(paginate_args(
        model_service.list_jobs(request.args.get("keyword"), request.args.get("status")),
        request.args,
    ))


@model_bp.route("/<int:job_id>", methods=["GET"])
@login_required
def job_detail(job_id):
    job = model_service.get_job(job_id)
    return ok(job) if job else fail("任务不存在")


@model_bp.route("/<int:job_id>", methods=["DELETE"])
@login_required
def job_delete(job_id):
    try:
        model_service.delete_job(job_id)
        return ok(True, "已删除")
    except Exception as e:
        return fail(str(e))


@model_bp.route("/batch-delete", methods=["POST"])
@login_required
def job_batch_delete():
    body = request.get_json(silent=True) or {}
    ids = body.get("ids") or body.get("job_ids") or []
    if not ids:
        return fail("请选择要删除的训练任务")
    try:
        result = model_service.delete_jobs(ids)
    except Exception as e:
        return fail(str(e))
    if not result.get("deleted"):
        return fail("没有可删除的训练任务")
    return ok(result, f"已删除 {result['deleted']} 条")


@model_bp.route("/train", methods=["POST"])
@login_required
def train():
    body = request.get_json(silent=True) or {}
    if not body.get("model_type") or not body.get("target_id"):
        return fail("请选择数据源和模型")
    try:
        return ok(model_service.create_and_run(body), "训练已开始")
    except Exception as e:
        return fail(str(e))


@model_bp.route("/compare", methods=["POST"])
@login_required
def compare():
    body = request.get_json(silent=True) or {}
    return ok(model_service.compare_jobs(body.get("job_ids") or []))


@model_bp.route("/insight", methods=["POST"])
@login_required
def insight():
    body = request.get_json(silent=True) or {}
    try:
        row = insight_service.create_from_train(
            body.get("train_job_id"),
            body.get("llm_config_id"),
            body.get("prompt_id"),
            body.get("use_rag", True),
            question=body.get("question"),
            system_prompt=body.get("system_prompt"),
        )
        from utils.jsonx import row_to_dict
        return ok(row_to_dict(row))
    except Exception as e:
        return fail(str(e))


@model_bp.route("/insight/list", methods=["GET"])
@login_required
def insight_list():
    from utils.jsonx import row_to_dict
    rows = [row_to_dict(r) if not isinstance(r, dict) else r for r in insight_service.list_reports(
        request.args.get("keyword"),
        request.args.get("target_col"),
        request.args.get("model_type"),
    )]
    return ok(paginate_args(rows, request.args))


@model_bp.route("/insight/batch-delete", methods=["POST"])
@login_required
def insight_batch_delete():
    body = request.get_json(silent=True) or {}
    ids = body.get("ids") or body.get("report_ids") or []
    if not ids:
        return fail("请选择要删除的洞察报告")
    try:
        result = insight_service.delete_reports(ids)
    except Exception as e:
        return fail(str(e))
    if not result.get("deleted"):
        return fail("没有可删除的洞察报告")
    return ok(result, f"已删除 {result['deleted']} 条")


@model_bp.route("/insight/<int:report_id>", methods=["GET"])
@login_required
def insight_detail(report_id):
    row = insight_service.get_report(report_id)
    return ok(row) if row else fail("洞察报告不存在")


@model_bp.route("/insight/<int:report_id>", methods=["DELETE"])
@login_required
def insight_delete(report_id):
    try:
        insight_service.delete_report(report_id)
        return ok(True, "已删除")
    except ValueError as e:
        return fail(str(e))
    except Exception as e:
        return fail(str(e))


@model_bp.route("/insight/<int:report_id>/export.md", methods=["GET"])
@login_required
def insight_export_md(report_id):
    row = insight_service.get_report(report_id)
    try:
        bio, filename = export_insight_report(row, "md")
    except ValueError as e:
        return fail(str(e))
    return send_file(bio, as_attachment=True, download_name=filename, mimetype="text/markdown; charset=utf-8")


@model_bp.route("/insight/<int:report_id>/export.docx", methods=["GET"])
@login_required
def insight_export_docx(report_id):
    row = insight_service.get_report(report_id)
    try:
        bio, filename = export_insight_report(row, "docx")
    except ValueError as e:
        return fail(str(e))
    return send_file(
        bio, as_attachment=True, download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@model_bp.route("/<int:job_id>/export", methods=["GET"])
@login_required
def job_export(job_id):
    try:
        bio, filename = build_export_zip(job_id)
    except ValueError as e:
        return fail(str(e))
    return send_file(bio, as_attachment=True, download_name=filename, mimetype="application/zip")


@model_bp.route("/<int:job_id>/insight.md", methods=["GET"])
@login_required
def job_insight_md(job_id):
    try:
        bio, filename = build_insight_markdown(job_id)
    except ValueError as e:
        return fail(str(e))
    return send_file(bio, as_attachment=True, download_name=filename, mimetype="text/markdown; charset=utf-8")
