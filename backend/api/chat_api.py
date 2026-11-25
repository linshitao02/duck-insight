# -*- coding: utf-8 -*-
import json

from flask import Blueprint, Response, g, request, stream_with_context

from services import chat_service
from utils.auth import login_required
from utils.response import fail, ok

chat_bp = Blueprint("chat", __name__, url_prefix="/api/chat")

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
    "Content-Type": "text/event-stream; charset=utf-8",
}


def _user():
    return dict(getattr(g, "user", {}) or {})


# --------------------------------------------------------------------------- #
# 会话管理
# --------------------------------------------------------------------------- #
@chat_bp.route("/sessions", methods=["GET"])
@login_required
def session_list():
    return ok(chat_service.list_sessions(user=_user(), keyword=request.args.get("keyword")))


@chat_bp.route("/sessions", methods=["POST"])
@login_required
def session_create():
    body = request.get_json(silent=True) or {}
    return ok(chat_service.create_session(body, user=_user()), "已新建会话")


@chat_bp.route("/sessions", methods=["DELETE"])
@login_required
def session_clear():
    return ok({"removed": chat_service.clear_sessions(user=_user())}, "已清空会话")


@chat_bp.route("/sessions/<int:sid>", methods=["GET"])
@login_required
def session_detail(sid):
    row = chat_service.get_session(sid, with_messages=True, user=_user())
    return ok(row) if row else fail("会话不存在")


@chat_bp.route("/sessions/<int:sid>", methods=["PUT"])
@login_required
def session_update(sid):
    """重命名会话，或更新会话的 LLM 模型 / 提示词 / RAG 开关。"""
    body = request.get_json(silent=True) or {}
    user = _user()
    if not chat_service.get_session(sid, user=user):
        return fail("会话不存在")
    if "title" in body:
        title = (body.get("title") or "").strip()
        if not title:
            return fail("标题不能为空")
        chat_service.rename_session(sid, title, user=user)
    chat_service.update_session_settings(sid, body, user=user)
    return ok(chat_service.get_session(sid, user=user), "已更新")


@chat_bp.route("/sessions/<int:sid>", methods=["DELETE"])
@login_required
def session_delete(sid):
    if not chat_service.delete_session(sid, user=_user()):
        return fail("会话不存在")
    return ok(message="已删除会话")


@chat_bp.route("/sessions/<int:sid>/messages", methods=["GET"])
@login_required
def message_list(sid):
    if not chat_service.get_session(sid, user=_user()):
        return fail("会话不存在")
    return ok(chat_service.list_messages(sid))


# --------------------------------------------------------------------------- #
# 对话
# --------------------------------------------------------------------------- #
def _ask_kwargs(body):
    """只转发客户端显式传入的设置，未传则沿用会话上持久化的选择。"""
    return {k: body[k] for k in ("llm_config_id", "prompt_id", "use_rag") if k in body}


@chat_bp.route("/sessions/<int:sid>/stream", methods=["POST"])
@login_required
def session_stream(sid):
    """SSE 流式问答：逐字返回回答，结束后回传会话与标题状态。"""
    body = request.get_json(silent=True) or {}
    user = _user()
    kwargs = _ask_kwargs(body)

    def generate():
        try:
            for event in chat_service.ask_stream(
                sid, body.get("question"), user=user, **kwargs
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            payload = json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
            yield f"data: {payload}\n\n"

    return Response(stream_with_context(generate()), headers=SSE_HEADERS)


@chat_bp.route("/sessions/<int:sid>/ask", methods=["POST"])
@login_required
def session_ask(sid):
    body = request.get_json(silent=True) or {}
    try:
        return ok(chat_service.ask(sid, body.get("question"), user=_user(), **_ask_kwargs(body)))
    except ValueError as e:
        return fail(str(e))
    except Exception as e:
        return fail(str(e))


@chat_bp.route("/sessions/<int:sid>/title", methods=["POST"])
@login_required
def session_title(sid):
    body = request.get_json(silent=True) or {}
    try:
        return ok(
            chat_service.summarize_title(sid, body.get("question"), body.get("answer"), user=_user()),
            "已生成标题",
        )
    except ValueError as e:
        return fail(str(e))
    except Exception as e:
        return fail(str(e))


# --------------------------------------------------------------------------- #
# 长期记忆
# --------------------------------------------------------------------------- #
@chat_bp.route("/memories", methods=["GET"])
@login_required
def memory_list():
    return ok(chat_service.list_memories(user=_user(), kind=request.args.get("kind")))


@chat_bp.route("/memories", methods=["DELETE"])
@login_required
def memory_clear():
    return ok({"removed": chat_service.clear_memories(user=_user())}, "已清空记忆")


@chat_bp.route("/memories/<int:mid>", methods=["DELETE"])
@login_required
def memory_delete(mid):
    if not chat_service.delete_memory(mid, user=_user()):
        return fail("记忆不存在")
    return ok(message="已删除记忆")
