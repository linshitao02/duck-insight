# -*- coding: utf-8 -*-
import json

from flask import Blueprint, Response, request

from services.llm_service import LLMService
from services.rag_service import get_rag_service
from utils.auth import login_required
from utils.paging import paginate_args
from utils.response import fail, ok

llm_bp = Blueprint("llm", __name__, url_prefix="/api")


@llm_bp.route("/llm/list", methods=["GET"])
@login_required
def llm_list():
    return ok(paginate_args(LLMService.list_llm(), request.args))


@llm_bp.route("/llm", methods=["POST"])
@login_required
def llm_create():
    body = request.get_json(silent=True) or {}
    return ok(LLMService.save_llm(body), "已保存")


@llm_bp.route("/llm/<int:cid>", methods=["PUT"])
@login_required
def llm_update(cid):
    body = request.get_json(silent=True) or {}
    return ok(LLMService.save_llm(body, cid), "已更新")


@llm_bp.route("/llm/<int:cid>", methods=["DELETE"])
@login_required
def llm_delete(cid):
    LLMService.delete_llm(cid)
    return ok(message="已删除")


@llm_bp.route("/llm/<int:cid>/test", methods=["POST"])
@login_required
def llm_test(cid):
    body = request.get_json(silent=True) or {}
    message = body.get("message") or "你好，请用一句话介绍你自己。"
    cfg = LLMService.get_llm(cid)
    if not cfg:
        return fail("配置不存在")

    def generate():
        try:
            for chunk in LLMService.stream_complete(
                [{"role": "user", "content": message}], cfg
            ):
                yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
            yield "data: {\"done\": true}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return Response(generate(), mimetype="text/event-stream")


@llm_bp.route("/prompt/list", methods=["GET"])
@login_required
def prompt_list():
    qa = request.args.get("qa_only")
    qa_only = None if qa is None else int(qa)
    return ok(paginate_args(LLMService.list_prompts(
        request.args.get("scene"),
        qa_only,
        request.args.get("prompt_kind"),
    ), request.args))


@llm_bp.route("/prompt", methods=["POST"])
@login_required
def prompt_create():
    body = request.get_json(silent=True) or {}
    return ok(LLMService.save_prompt(body), "已保存")


@llm_bp.route("/prompt/<int:pid>", methods=["PUT"])
@login_required
def prompt_update(pid):
    body = request.get_json(silent=True) or {}
    return ok(LLMService.save_prompt(body, pid), "已更新")


@llm_bp.route("/prompt/<int:pid>", methods=["DELETE"])
@login_required
def prompt_delete(pid):
    LLMService.delete_prompt(pid)
    return ok(message="已删除")


@llm_bp.route("/rag/status", methods=["GET"])
@login_required
def rag_status():
    return ok(get_rag_service().status())


@llm_bp.route("/rag/docs", methods=["GET"])
@login_required
def rag_docs():
    return ok(get_rag_service().list_docs(
        page=request.args.get("page") or 1,
        page_size=request.args.get("page_size") or 10,
        keyword=request.args.get("keyword"),
    ))


@llm_bp.route("/rag/docs/detail", methods=["GET"])
@login_required
def rag_doc_detail():
    name = request.args.get("name")
    if not name:
        return fail("缺少文件名")
    row = get_rag_service().get_doc(name)
    return ok(row) if row else fail("文档不存在")


@llm_bp.route("/rag/chunks", methods=["GET"])
@login_required
def rag_chunks():
    return ok(get_rag_service().list_chunks(
        source=request.args.get("source"),
        page=request.args.get("page") or 1,
        page_size=request.args.get("page_size") or 20,
    ))


@llm_bp.route("/rag/docs", methods=["POST"])
@login_required
def rag_upload():
    f = request.files.get("file")
    if not f:
        return fail("请选择文档")
    try:
        return ok(get_rag_service().save_doc(f), "已入库并重建索引")
    except Exception as e:
        return fail(str(e))


@llm_bp.route("/rag/docs", methods=["DELETE"])
@login_required
def rag_delete():
    name = (request.get_json(silent=True) or {}).get("name") or request.args.get("name")
    if not name:
        return fail("缺少文件名")
    get_rag_service().delete_doc(name)
    return ok(message="已删除")


@llm_bp.route("/rag/rebuild", methods=["POST"])
@login_required
def rag_rebuild():
    get_rag_service().rebuild()
    return ok(get_rag_service().status(), "索引已重建")


@llm_bp.route("/rag/ask", methods=["POST"])
@login_required
def rag_ask():
    body = request.get_json(silent=True) or {}
    question = body.get("question")
    if not question:
        return fail("请输入问题")
    try:
        answer, snippets = LLMService.ask(
            question, body.get("llm_config_id"), body.get("prompt_id"), body.get("use_rag", True)
        )
        return ok({"answer": answer, "snippets": snippets})
    except Exception as e:
        return fail(str(e))
