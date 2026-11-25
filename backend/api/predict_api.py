# -*- coding: utf-8 -*-
from flask import Blueprint, request, send_file

from services import model_service, predict_service
from utils.auth import login_required
from utils.paging import paginate_args
from utils.response import fail, ok

predict_bp = Blueprint("predict", __name__, url_prefix="/api/predict")


@predict_bp.route("/template/<int:job_id>", methods=["GET"])
@login_required
def template(job_id):
    job = model_service.get_job(job_id)
    if not job:
        return fail("模型不存在")
    bio, filename = predict_service.build_template_excel(job)
    return send_file(bio, as_attachment=True, download_name=filename,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@predict_bp.route("/columns/<int:job_id>", methods=["GET"])
@login_required
def columns(job_id):
    job = model_service.get_job(job_id)
    if not job:
        return fail("模型不存在")
    return ok({
        "columns": predict_service.template_columns(job),
        "feature_cols": job.get("feature_cols"),
        "target_col": job.get("target_col"),
    })


@predict_bp.route("/run", methods=["POST"])
@login_required
def run():
    excel = request.files.get("file")
    if excel:
        payload = {
            "train_job_id": int(request.form.get("train_job_id")),
            "use_llm": request.form.get("use_llm") in ("1", "true", "True"),
            "use_rag": request.form.get("use_rag", "1") not in ("0", "false", "False"),
            "llm_config_id": request.form.get("llm_config_id") or None,
            "prompt_id": request.form.get("prompt_id") or None,
            "question": request.form.get("question"),
            "system_prompt": request.form.get("system_prompt"),
            "name": request.form.get("name"),
        }
        if payload["llm_config_id"]:
            payload["llm_config_id"] = int(payload["llm_config_id"])
        if payload["prompt_id"]:
            payload["prompt_id"] = int(payload["prompt_id"])
    else:
        payload = request.get_json(silent=True) or {}
        excel = None
    try:
        row = predict_service.run_predict(payload, excel)
    except Exception as e:
        return fail(str(e))
    warn = (row or {}).get("llm_error")
    return ok(row, f"预测完成，但 LLM 解读失败：{warn}" if warn else "预测完成")


@predict_bp.route("/list", methods=["GET"])
@login_required
def pred_list():
    return ok(paginate_args(
        predict_service.list_preds(
            keyword=(request.args.get("keyword") or "").strip() or None,
            train_job_id=request.args.get("train_job_id") or None,
            llm_only=request.args.get("llm_only") in ("1", "true", "True"),
        ),
        request.args,
    ))


@predict_bp.route("/batch-delete", methods=["POST"])
@login_required
def pred_batch_delete():
    body = request.get_json(silent=True) or {}
    ids = body.get("ids") or body.get("pred_ids") or []
    if not ids:
        return fail("请选择要删除的预测记录")
    result = predict_service.delete_preds(ids)
    if not result.get("deleted"):
        return fail("没有可删除的预测记录")
    return ok(result, f"已删除 {result['deleted']} 条")


@predict_bp.route("/<int:pid>", methods=["GET"])
@login_required
def pred_detail(pid):
    row = predict_service.get_pred(pid)
    return ok(row) if row else fail("记录不存在")


@predict_bp.route("/<int:pid>", methods=["DELETE"])
@login_required
def pred_delete(pid):
    try:
        predict_service.delete_pred(pid)
        return ok(True, "已删除")
    except Exception as e:
        return fail(str(e))


@predict_bp.route("/<int:pid>/analyze", methods=["POST"])
@login_required
def pred_analyze(pid):
    body = request.get_json(silent=True) or {}
    try:
        return ok(predict_service.analyze_pred(pid, body), "LLM 分析完成")
    except Exception as e:
        return fail(str(e))
