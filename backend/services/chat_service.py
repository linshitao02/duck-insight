# -*- coding: utf-8 -*-
"""智能问答：多会话管理 + 流式输出 + 短期/长期记忆。

记忆分层设计：
- 短期记忆：当前会话最近 SHORT_TERM_MESSAGES 条原文，直接进对话消息；
- 中长期记忆：会话级滚动摘要（chat_session.summary），压缩超出短期窗口的历史；
- 长期记忆：跨会话的事实/偏好（chat_memory），按问题相关性召回后注入系统提示词。
"""
import re
import threading
import time

from flask import g

from services.llm_service import LLMService
from services.rag_service import get_rag_service
from utils.db import delete, execute, insert, query, update
from utils.jsonx import dumps, row_to_dict

DEFAULT_TITLE = "新会话"
TITLE_MAX_LEN = 18
TITLE_MIN_LEN = 4
TITLE_FALLBACK_LEN = 14
RAG_TOP_K = 3            # 知识库召回片段数
RAG_SNIPPET_CHARS = 320  # 单个片段注入上限（控制提示词长度，压低首字延迟）
SHORT_TERM_MESSAGES = 6  # 短期记忆窗口（条）
SHORT_TERM_CHARS = 700   # 单条历史截断长度
HISTORY_BUDGET_CHARS = 2400  # 短期记忆总字符预算，超出则优先丢最早的
SUMMARY_TRIGGER = 4      # 超出短期窗口的消息累计到该数量即滚动摘要
SUMMARY_MAX_LEN = 320    # 会话摘要长度上限
MEMORY_TOP_K = 5         # 长期记忆召回条数
MEMORY_MIN_SCORE = 0.06  # 长期记忆相关性下限
MEMORY_SCAN_LIMIT = 400  # 单次参与打分的历史记忆上限
FACT_EVERY = 4           # 每 N 条消息抽取一次长期记忆
POST_TURN_DELAY = 12     # 后台记忆维护延迟秒数，避开用户连续提问

# 会话主提示词：只放平台级基础要求（身份、引用、记忆、合规、排版）。
# 「召回为空时如何作答」属于业务策略，写在提示词模板里由用户选择，平台不覆盖。
CHAT_SYSTEM = (
    "你是「气象电力数据分析平台」的智能助手，服务于电力交易、新能源场站与气象数据分析场景。\n"
    "回答要求：\n"
    "1. 优先采用【知识库召回片段】的内容，引用时在句末标注来源文件名；\n"
    "2. 结合【长期记忆】与【会话历史摘要】理解用户背景，保持口径与偏好一致；\n"
    "3. 涉及报价、调度、下单等交易动作时，提示需人工确认，系统不直接下单；\n"
    "4. 用简体中文与 Markdown 组织内容，结论先行，数字不得编造。"
)

_MEMORY_LOCK = threading.Lock()

# 小模型常复述提示词结构，这些前缀需要剥掉
_META_PREFIX = re.compile(
    r"^(?:本轮)?(?:对话|会话)?(?:的)?"
    r"(?:用户(?:的)?问题|用户提问|问题|提问|助手(?:的)?回答|助手回答|回答|答案|标题|主题|概括|总结)"
    r"\s*[：:是为]?\s*"
)
_META_WORDS = ("用户问题", "用户的问题", "用户提问", "助手的回答", "助手回答",
               "暂无足够依据", "知识库召回", "根据知识库", "对话主题")
_ECHO_WORDS = ("只输出", "只回答", "不要", "禁止", "示例", "用不超过",
               "直接输出", "直接回答", "标题生成", "一行", "问答内容", "请给",
               "要求", "格式", "输出", "概括", "指的是", "我需要", "让我",
               "用户提供", "问答", "以上", "下面", "这段", "提供", "这段对话",
               "参考", "回答方向", "回答要点", "阅读下面", "概括主题", "中文短语",
               "用户指定", "用户输入", "用户描述", "用户说的", "指定的",
               "该问题", "此问题", "问题主题", "上述", "如下", "本次")
# 标题以这些词开头基本都是复述任务说明，而非话题本身
_TITLE_BAD_PREFIX = ("用户", "助手", "该问题", "此问题", "问题", "示例", "注意",
                     "本段", "上述", "根据", "按照", "以「", "输出")
_TITLE_CHARS = re.compile(r"[\u4e00-\u9fa5A-Za-z0-9、·]+")
_TITLE_STOPWORDS = {"所以", "但是", "因此", "不过", "这个", "那个", "其实", "好的",
                    "首先", "然后", "最后", "总之", "综上", "标题", "主题", "内容"}
_LABELED = re.compile(r"(?:短?标题|主题)\s*(?:是|为)?\s*[：:]\s*([^\n]+)")
_MEM_PREFIX = "MEM|"
# 长期记忆必须是「类别|内容」式陈述，禁止把对话转写或推理过程当成记忆
_MEMORY_REJECT = ("用户", "助手", "消息", "提问", "对话", "本轮", "第一个",
                  "这段", "以上", "下面", "?", "？", "**", "\"", "\"", "\"",
                  "不要", "简洁", "不超过", "示例", "应该", "需要", "注意",
                  "格式", "输出", "回答", "字\"", "字数")
_MEMORY_KEY_MAX = 10
_MEMORY_VALUE_MIN = 4
_MEMORY_VALUE_MAX = 40


# --------------------------------------------------------------------------- #
# 上下文与归属
# --------------------------------------------------------------------------- #
def _ctx_user(user=None):
    return user if user is not None else (getattr(g, "user", {}) or {})


def _owner_scope(user=None, alias=""):
    """管理员可管理全部会话，普通用户仅限自己的会话。"""
    prefix = f"{alias}." if alias else ""
    if _ctx_user(user).get("role") == "admin":
        return "", []
    return f" AND {prefix}user_id=%s", [_ctx_user(user).get("id")]


def _tokenize(text):
    """记忆检索用的轻量分词：中文 1-2 gram + 英文数字词。"""
    raw = (text or "").lower()
    out = set(re.findall(r"[a-z0-9_]{2,}", raw))
    for seg in re.findall(r"[\u4e00-\u9fff]+", raw):
        for i in range(len(seg)):
            out.add(seg[i])
            if i + 2 <= len(seg):
                out.add(seg[i:i + 2])
    return out


def _squash(text, limit=None):
    out = re.sub(r"\s+", " ", (text or "")).strip()
    return out[:limit] if limit else out


def _after_think(text):
    """思考型模型可能把推理混进正文，截取 </think> 之后的内容。"""
    out = text or ""
    if "</think>" in out:
        out = out.split("</think>", 1)[-1]
    return out.replace("<think>", "").strip()


# --------------------------------------------------------------------------- #
# 序列化
# --------------------------------------------------------------------------- #
def serialize_session(row):
    if not row:
        return None
    data = row_to_dict(row)
    data["message_count"] = int(data.get("message_count") or 0)
    data["title_auto"] = int(data.get("title_auto") or 0)
    data["use_rag"] = int(1 if data.get("use_rag") is None else data.get("use_rag"))
    data["title"] = data.get("title") or DEFAULT_TITLE
    data["has_summary"] = bool((data.get("summary") or "").strip())
    return data


def serialize_message(row):
    if not row:
        return None
    data = row_to_dict(row)
    snippets = data.get("snippets")
    data["snippets"] = snippets if isinstance(snippets, list) else []
    return data


def serialize_memory(row):
    return row_to_dict(row) if row else None


# --------------------------------------------------------------------------- #
# 会话 CRUD
# --------------------------------------------------------------------------- #
def list_sessions(user=None, keyword=None):
    where, args = _owner_scope(user)
    sql = "SELECT * FROM chat_session WHERE status=1" + where
    if keyword:
        sql += " AND (title LIKE %s OR last_message LIKE %s)"
        args += [f"%{keyword}%", f"%{keyword}%"]
    sql += " ORDER BY update_time DESC, id DESC"
    return [serialize_session(r) for r in query(sql, args)]


def get_session(sid, with_messages=False, user=None):
    where, args = _owner_scope(user)
    row = query("SELECT * FROM chat_session WHERE id=%s AND status=1" + where, [sid] + args, one=True)
    data = serialize_session(row)
    if data and with_messages:
        data["messages"] = list_messages(sid)
    return data


def list_messages(sid):
    rows = query("SELECT * FROM chat_message WHERE session_id=%s ORDER BY id ASC", (sid,))
    return [serialize_message(r) for r in rows]


def create_session(payload=None, user=None):
    payload = payload or {}
    me = _ctx_user(user)
    data = {
        "title": (payload.get("title") or "").strip() or DEFAULT_TITLE,
        "title_auto": 0,
        "llm_config_id": payload.get("llm_config_id"),
        "prompt_id": payload.get("prompt_id"),
        "use_rag": 1 if payload.get("use_rag") is None else int(bool(payload.get("use_rag"))),
        "message_count": 0,
        "user_id": me.get("id"),
        "username": me.get("username"),
        "status": 1,
    }
    return get_session(insert("chat_session", data), user=user)


def rename_session(sid, title, user=None):
    title = (title or "").strip()
    where, args = _owner_scope(user)
    update("chat_session", {"title": title or DEFAULT_TITLE, "title_auto": 0},
           f"id=%s{where}", [sid] + args)
    return get_session(sid, user=user)


def update_session_settings(sid, payload, user=None):
    """更新会话的推理设置：LLM 模型 / 提示词 / 是否启用知识库召回。"""
    payload = payload or {}
    fields = {}
    for key in ("llm_config_id", "prompt_id"):
        if key in payload:
            val = payload.get(key)
            try:
                fields[key] = int(val) if val not in (None, "", 0, "0") else None
            except (TypeError, ValueError):
                fields[key] = None
    if "use_rag" in payload:
        val = payload.get("use_rag")
        fields["use_rag"] = 1 if str(val).lower() in ("1", "true", "yes", "on") or val is True else 0
    if fields:
        where, args = _owner_scope(user)
        update("chat_session", fields, f"id=%s{where}", [sid] + args)
    return get_session(sid, user=user)


def delete_session(sid, user=None):
    where, args = _owner_scope(user)
    execute("DELETE FROM chat_message WHERE session_id=%s", (sid,))
    return delete("chat_session", f"id=%s{where}", [sid] + args)


def clear_sessions(user=None):
    """清空当前用户（管理员为全部）的会话与记忆。"""
    where, args = _owner_scope(user)
    rows = query("SELECT id FROM chat_session WHERE status=1" + where, args)
    ids = [r["id"] for r in rows]
    if ids:
        marks = ", ".join(["%s"] * len(ids))
        execute(f"DELETE FROM chat_message WHERE session_id IN ({marks})", ids)
    removed = delete("chat_session", "1=1" + where, args)
    delete("chat_memory", "1=1" + where, args)
    return removed


def _store(sid, role, content, snippets=None):
    insert("chat_message", {
        "session_id": sid,
        "role": role,
        "content": content,
        "snippets_json": dumps(snippets or []) if snippets else None,
    })
    count = int(query("SELECT COUNT(*) AS c FROM chat_message WHERE session_id=%s", (sid,), one=True)["c"])
    update("chat_session", {
        "message_count": count,
        "last_message": re.sub(r"\s+", " ", (content or "")).strip()[:200],
    }, "id=%s", (sid,))
    return count


# --------------------------------------------------------------------------- #
# 标题：LLM 自动总结
# --------------------------------------------------------------------------- #
def _fallback_title(question):
    raw = re.sub(r"\s+", " ", (question or "")).strip()
    if not raw:
        return DEFAULT_TITLE
    return raw[:TITLE_FALLBACK_LEN].rstrip() + ("…" if len(raw) > TITLE_FALLBACK_LEN else "")


def _title_prompts(q_text, a_text, no_think=False):
    suffix = " /no_think" if no_think else ""
    yield [
        {"role": "system", "content": "你是标题助手。" + suffix},
        {
            "role": "user",
            "content": (
                f"阅读下面的问答，概括主题，只回一行，形如「短标题：内容」，内容为 8-14 字中文短语。\n\n"
                f"问：{q_text[:160]}\n答：{a_text[:200]}\n\n短标题："
            ),
        },
    ]
    yield [
        {"role": "system", "content": "直接回答，不要解释。" + suffix},
        {"role": "user", "content": f"用 8-14 个字概括主题。只回答主题本身，不要标点。\n\n主题：{q_text[:160]}"},
    ]


def _sanitize_title(text):
    raw = (text or "").strip()
    if not raw:
        return ""
    raw = raw.lstrip("\"'“”‘’《》<>#*`-—:：,，.。!！?？【】[]（）() ")
    matched = _TITLE_CHARS.match(raw)
    if not matched:
        return ""
    raw = matched.group(0)
    for _ in range(3):
        stripped = _META_PREFIX.sub("", raw).strip()
        if stripped == raw:
            break
        raw = stripped
    if len(raw) < TITLE_MIN_LEN or len(raw) > TITLE_MAX_LEN:
        return ""
    if raw in _TITLE_STOPWORDS or raw.startswith(_TITLE_BAD_PREFIX):
        return ""
    if any(w in raw for w in _META_WORDS + _ECHO_WORDS):
        return ""
    return raw


def _clean_title(text):
    raw = (text or "").strip()
    if not raw:
        return ""
    labeled = _LABELED.search(raw)
    if labeled:
        got = _sanitize_title(labeled.group(1))
        if got:
            return got
    for line in raw.splitlines():
        got = _sanitize_title(line)
        if got:
            return got
    return ""


def summarize_title(sid, question=None, answer=None, user=None):
    """用 LLM 依据首轮对话总结一个短标题。"""
    session = get_session(sid, user=user)
    if not session:
        raise ValueError("会话不存在")

    messages = list_messages(sid)
    first_user = next((m for m in messages if m.get("role") == "user"), None)
    first_assistant = next((m for m in messages if m.get("role") == "assistant"), None)
    q_text = (question or (first_user or {}).get("content") or "").strip()
    a_text = (answer or (first_assistant or {}).get("content") or "").strip()

    title = ""
    try:
        cfg, _ = LLMService._resolve(session.get("llm_config_id"), None, None)
        if cfg:
            small = dict(cfg)
            small["max_tokens"] = 48
            small["temperature"] = 0.2
            for prompt_messages in _title_prompts(q_text, a_text, bool(int(cfg.get("is_local_llm") or 0))):
                title = _clean_title(LLMService.chat_complete(prompt_messages, small, think=False))
                if title:
                    break
    except Exception:
        title = ""

    update("chat_session", {"title": title or _fallback_title(q_text), "title_auto": 1}, "id=%s", (sid,))
    return get_session(sid, user=user)


# --------------------------------------------------------------------------- #
# 长期记忆（chat_memory）
# --------------------------------------------------------------------------- #
def list_memories(user=None, kind=None, limit=200):
    where, args = _owner_scope(user)
    sql = "SELECT * FROM chat_memory WHERE status=1" + where
    if kind:
        sql += " AND kind=%s"
        args.append(kind)
    sql += " ORDER BY update_time DESC, id DESC LIMIT %s"
    args.append(int(limit))
    return [serialize_memory(r) for r in query(sql, args)]


def delete_memory(mid, user=None):
    where, args = _owner_scope(user)
    return delete("chat_memory", f"id=%s{where}", [mid] + args)


def clear_memories(user=None):
    where, args = _owner_scope(user)
    return delete("chat_memory", "1=1" + where, args)


def retrieve_memories(question, exclude_session=None, user=None, top_k=MEMORY_TOP_K):
    """按问题相关性召回长期记忆（词元重合度 + 权重 + 时效）。"""
    where, args = _owner_scope(user)
    sql = "SELECT * FROM chat_memory WHERE status=1" + where
    if exclude_session:
        sql += " AND (session_id IS NULL OR session_id<>%s)"
        args.append(exclude_session)
    sql += " ORDER BY update_time DESC LIMIT %s"
    args.append(MEMORY_SCAN_LIMIT)
    rows = query(sql, args)

    q_tokens = _tokenize(question)
    if not q_tokens:
        return []
    scored = []
    for r in rows:
        m_tokens = _tokenize(f"{r.get('content') or ''} {r.get('keywords') or ''}")
        if not m_tokens:
            continue
        overlap = len(q_tokens & m_tokens)
        if not overlap:
            continue
        score = overlap / (len(m_tokens) ** 0.5)
        score *= float(r.get("weight") or 1)
        if r.get("kind") == "fact":
            score *= 1.2
        if score < MEMORY_MIN_SCORE:
            continue
        scored.append((score, r))

    scored.sort(key=lambda x: -x[0])
    picked = []
    for score, r in scored[:top_k]:
        item = row_to_dict(r)
        item["score"] = round(score, 4)
        picked.append(item)
    if picked:
        marks = ", ".join(["%s"] * len(picked))
        execute(f"UPDATE chat_memory SET hits=hits+1 WHERE id IN ({marks})", [p["id"] for p in picked])
    return picked


def _remember(kind, content, keywords, session_id, user_id, username, weight=1.0):
    content = (content or "").strip()
    if not content:
        return None
    # 近重复记忆直接合并，避免长期记忆膨胀
    dup = query(
        "SELECT id, content FROM chat_memory WHERE kind=%s AND status=1 AND user_id<=>%s LIMIT 200",
        (kind, user_id),
    )
    new_tokens = _tokenize(content)
    for row in dup:
        old_tokens = _tokenize(row.get("content"))
        if not new_tokens or not old_tokens:
            continue
        if len(new_tokens & old_tokens) / max(len(new_tokens | old_tokens), 1) > 0.8:
            update("chat_memory", {"content": content, "keywords": keywords, "weight": weight},
                   "id=%s", (row["id"],))
            return row["id"]
    return insert("chat_memory", {
        "kind": kind,
        "session_id": session_id,
        "content": content,
        "keywords": keywords,
        "weight": weight,
        "hits": 0,
        "user_id": user_id,
        "username": username,
        "status": 1,
    })


# --------------------------------------------------------------------------- #
# 后台记忆维护：会话摘要 + 事实抽取
# --------------------------------------------------------------------------- #
def _compact_summary(prev, pending):
    """确定性兜底摘要：历史话题清单 + 最近结论（小模型转写原文时使用）。"""
    topics = []
    for r in pending:
        if r["role"] != "user":
            continue
        q = _squash(r.get("content"), 40).strip("。？?！!；; ")
        if q and q not in topics:
            topics.append(q)
    tail = ""
    for r in reversed(pending):
        if r["role"] == "assistant":
            tail = _squash(r.get("content"), 110)
            break
    parts = []
    if prev:
        parts.append(_squash(prev, 140))
    if topics:
        parts.append("历史话题：" + "；".join(topics[-6:]))
    if tail:
        parts.append("最近结论：" + tail)
    return _squash(" ".join(parts))[:SUMMARY_MAX_LEN]


_SUMMARY_PREFIX = "SUM|"


def _valid_summary(text):
    """拒绝「逐条转写原文」或「推理过程」式的假摘要。"""
    t = (text or "").strip()
    start = t.find(_SUMMARY_PREFIX)
    if start < 0:
        return ""
    t = _squash(t[start + len(_SUMMARY_PREFIX):])
    if len(t) < 12:
        return ""
    if any(marker in t for marker in ("用户：", "助手：", "用户:", "助手:", "**", "\"")):
        return ""
    if sum(w in t for w in ("不要", "不超过", "简洁", "要求", "格式", "输出", "示例")) >= 1:
        return ""
    return t[:SUMMARY_MAX_LEN]


def _refresh_session_summary(sid, user_id, username):
    """把超出短期窗口的历史压缩进会话摘要，并同步为长期记忆。"""
    session = query("SELECT * FROM chat_session WHERE id=%s", (sid,), one=True)
    if not session:
        return
    rows = query("SELECT id, role, content FROM chat_message WHERE session_id=%s ORDER BY id ASC", (sid,))
    if not rows:
        return
    upto = int(session.get("summary_upto") or 0)
    covered_max = rows[-SHORT_TERM_MESSAGES]["id"] if len(rows) > SHORT_TERM_MESSAGES else 0
    pending = [r for r in rows if upto < int(r["id"]) <= covered_max]
    if len(pending) < SUMMARY_TRIGGER:
        return

    prev = _squash(session.get("summary"))
    body = "\n".join(
        f"{'用户' if r['role'] == 'user' else '助手'}：{_squash(r['content'], 200)}"
        for r in pending
    )
    prompt = (
        "把下面的多轮对话压缩成一段不超过 150 字的中文摘要，保留：关注主题、已确认结论、"
        "关键指标与口径、未解决问题。\n"
        "必须是一段连贯的话，禁止逐条转写，禁止出现「用户：」「助手：」这样的对话标记。\n"
        "输出格式：以 SUM| 开头，后面直接跟摘要正文，不要标题、不要解释。\n\n"
        f"示例：SUM|围绕用电负荷与气象特征展开，确认气温是主导因素，…\n\n"
        + (f"【已有摘要】\n{prev}\n\n" if prev else "")
        + f"【新增对话】\n{body}\n\n【输出】"
    )
    summary = ""
    try:
        cfg, _ = LLMService._resolve(session.get("llm_config_id"), None, None)
        summary = _valid_summary(LLMService.chat_complete(
            [
                {"role": "system", "content": "你是对话摘要器，只输出一行 SUM| 开头的摘要正文。" + _no_think_suffix(cfg)},
                {"role": "user", "content": prompt},
            ],
            {**(cfg or {}), "max_tokens": 320, "temperature": 0.2},
            think=False,
        ))
    except Exception:
        summary = ""
    if not summary:
        summary = _compact_summary(prev, pending)
    if not summary:
        return

    update("chat_session", {"summary": summary, "summary_upto": max(int(r["id"]) for r in pending)}, "id=%s", (sid,))
    # 会话摘要同时作为长期记忆，供后续跨会话召回
    title = _squash(session.get("title"), 30) or DEFAULT_TITLE
    _remember("session", f"{title}：{summary}"[:500], title, sid, user_id, username, weight=0.9)


def _extract_facts(session, user_id, username):
    """从最近若干轮对话中抽取可长期复用的事实/偏好。"""
    rows = query(
        "SELECT role, content FROM chat_message WHERE session_id=%s ORDER BY id DESC LIMIT 8",
        (session["id"],),
    )
    if len(rows) < 2:
        return
    body = "\n".join(
        f"{'用户' if r['role'] == 'user' else '助手'}：{_squash(r['content'], 300)}"
        for r in reversed(rows)
    )
    prompt = (
        "阅读下面这段人与助手的对话，提炼出「值得长期记住」的信息，"
        "例如使用者的身份岗位、长期关注的分析主题、数据口径与单位习惯、明确的偏好或约束。\n"
        "输出格式：每行必须以 MEM| 开头，写成 MEM|类别|内容\n"
        "类别不超过 6 个字，内容不超过 30 字，最多 3 条。\n"
        "绝对不要复述对话原文，不要出现「用户」「助手」「消息」「提问」这些词。\n"
        "没有值得长期记住的信息就输出「无」。不要任何解释。\n\n"
        "示例输出：\n"
        "MEM|关注主题|用电负荷与气象特征的关系\n"
        "MEM|单位习惯|负荷以 MW 计\n\n"
        f"【对话】\n{body}\n\n【输出】"
    )
    try:
        cfg, _ = LLMService._resolve(session.get("llm_config_id"), None, None)
        raw = LLMService.chat_complete(
            [
                {"role": "system", "content": "你是记忆抽取器，每行输出 MEM|类别|内容。" + _no_think_suffix(cfg)},
                {"role": "user", "content": prompt},
            ],
            {**(cfg or {}), "max_tokens": 200, "temperature": 0.1},
            think=False,
        )
    except Exception:
        return

    raw = _after_think(raw)
    kept = 0
    for line in raw.splitlines():
        # 只认带 MEM| 前缀的条目，推理过程与转写原文都会被过滤掉
        start = line.find(_MEM_PREFIX)
        if start < 0:
            continue
        parts = line[start:].split("|")
        if len(parts) < 3:
            continue
        key = parts[1].strip().strip("：: ")
        value = "|".join(parts[2:]).strip().strip("。；;，, ")
        # 模型偶尔会追加「（18字）」这类自述，去掉
        value = re.sub(r"[（(]\s*\d+\s*字\s*[)）]\s*$", "", value).strip()
        if not (1 <= len(key) <= _MEMORY_KEY_MAX):
            continue
        if not (_MEMORY_VALUE_MIN <= len(value) <= _MEMORY_VALUE_MAX):
            continue
        if any(w in key + value for w in _MEMORY_REJECT):
            continue
        got = _remember("fact", f"{key}：{value}", key, session["id"], user_id, username, weight=1.0)
        if got:
            kept += 1
        if kept >= 3:
            break


def _post_turn(sid, user_id, username, message_count):
    """一轮问答结束后的后台记忆维护（串行 + 延迟，避免抢占正在进行的对话）。"""
    time.sleep(POST_TURN_DELAY)
    if not _MEMORY_LOCK.acquire(blocking=False):
        return
    try:
        _refresh_session_summary(sid, user_id, username)
        if message_count % FACT_EVERY == 0:
            session = query("SELECT * FROM chat_session WHERE id=%s", (sid,), one=True)
            if session:
                _extract_facts(session, user_id, username)
    except Exception:
        pass
    finally:
        _MEMORY_LOCK.release()


def _spawn_post_turn(sid, user_id, username, message_count):
    threading.Thread(
        target=_post_turn,
        args=(sid, user_id, username, message_count),
        daemon=True,
        name=f"chat-mem-{sid}",
    ).start()


# --------------------------------------------------------------------------- #
# 对话：组装上下文（短期 + 摘要 + 长期记忆 + RAG）
# --------------------------------------------------------------------------- #
def _history_messages(sid):
    """短期记忆：取最近若干条原文，并按总字符预算丢弃最早的部分。"""
    rows = query(
        "SELECT role, content FROM chat_message WHERE session_id=%s ORDER BY id DESC LIMIT %s",
        (sid, SHORT_TERM_MESSAGES),
    )
    picked = []
    budget = HISTORY_BUDGET_CHARS
    for r in rows:  # 已按 id 倒序：从最新往回纳入
        content = (r.get("content") or "").strip()
        if not content:
            continue
        content = content[:SHORT_TERM_CHARS]
        if len(content) > budget:
            content = content[-budget:]
        picked.append({"role": r["role"], "content": content})
        budget -= len(content)
        if budget <= 0:
            break
    picked.reverse()
    return picked


def build_messages(session, question, history, snippets, memories, prompt_content=None):
    """组装本轮 LLM 入参。

    短期记忆 = history 原文；中长期 = 会话摘要；长期 = 跨会话记忆。
    prompt_content: 用户在本会话显式选择的提示词模板（未填充），占位符在此替换。
    """
    rag_block = "\n\n".join(
        f"[{s.get('source')}#{s.get('idx', 0)}] {(s.get('text') or '')[:RAG_SNIPPET_CHARS]}"
        for s in snippets
    )
    if not rag_block:
        # 只陈述事实，不附带策略：召回为空时怎么答由提示词决定
        rag_block = "（本次未检索到相关片段）"

    parts = []
    inline_context = False
    if prompt_content:
        # 模板自带 {context} 时片段已内联，避免重复注入
        inline_context = "{context}" in prompt_content
        parts.append(LLMService.fill_prompt(prompt_content, {
            "context": rag_block,
            "question": question,
            "metrics": "",
            "importance": "",
            "predictions": "",
        }).strip())

    # 平台规则放在提示词之后：提示词里的「片段不足即拒答」会被这里的规则覆盖
    parts.append(CHAT_SYSTEM)

    summary = (session.get("summary") or "").strip()
    if summary:
        parts.append(f"【会话历史摘要】（更早的对话已压缩）\n{summary}")

    if memories:
        lines = []
        for m in memories:
            tag = "偏好/事实" if m.get("kind") == "fact" else "历史会话"
            lines.append(f"- （{tag}）{m.get('content')}")
        parts.append("【长期记忆】（来自以往会话，仅供参考）\n" + "\n".join(lines))

    if not inline_context:
        parts.append("【知识库召回片段】（优先依据，引用请标注文件名）\n" + rag_block)

    messages = [{"role": "system", "content": "\n\n".join(p for p in parts if p)}]
    messages.extend(history)
    messages.append({"role": "user", "content": question})
    return messages


def _no_think_suffix(cfg):
    """本地 qwen3 加 /no_think 软开关，明显压缩思考长度。"""
    if not int((cfg or {}).get("is_local_llm") or 0):
        return ""
    return " /no_think" if "qwen3" in str((cfg or {}).get("model_name") or "").lower() else ""


def _with_no_think(messages, cfg):
    suffix = _no_think_suffix(cfg)
    if not suffix:
        return messages
    out = [dict(m) for m in messages]
    if out and out[0].get("role") == "system":
        out[0]["content"] = out[0]["content"].rstrip() + suffix
    return out


_UNSET = object()


def prepare_turn(sid, question, llm_config_id=_UNSET, prompt_id=_UNSET, use_rag=_UNSET, user=None):
    """保存提问、检索上下文，返回本轮 LLM 入参与元信息。

    llm_config_id / prompt_id / use_rag 用哨兵区分「未传」与「显式传 null」：
    - 未传：沿用会话上持久化的选择（然后才落到系统默认 LLM）；
    - 显式传 null：表示不使用该配置（prompt_id=null 即不套用提示词）。
    scene 固定传 None：不自动套用场景默认提示词，提示词必须由用户显式选择。
    """
    session = get_session(sid, user=user)
    if not session:
        raise ValueError("会话不存在")
    question = (question or "").strip()
    if not question:
        raise ValueError("请输入问题")

    pick_llm = session.get("llm_config_id") if llm_config_id is _UNSET else llm_config_id
    pick_prompt = session.get("prompt_id") if prompt_id is _UNSET else prompt_id
    cfg, prompt = LLMService._resolve(pick_llm, pick_prompt, None)

    history = _history_messages(sid)
    first_turn = int(session.get("message_count") or 0) == 0

    if use_rag is _UNSET or use_rag is None:
        use_rag_flag = session.get("use_rag")
    else:
        use_rag_flag = int(bool(use_rag))
    snippets = []
    if use_rag_flag:
        try:
            snippets = get_rag_service().search(question, top_k=RAG_TOP_K)
        except Exception:
            snippets = []

    try:
        memories = retrieve_memories(question, exclude_session=sid, user=user)
    except Exception:
        memories = []

    _store(sid, "user", question)
    messages = _with_no_think(
        build_messages(session, question, history, snippets, memories, (prompt or {}).get("content")),
        cfg,
    )

    return {
        "session": session,
        "question": question,
        "messages": messages,
        "cfg": cfg,
        "snippets": snippets,
        "memories": memories,
        "first_turn": first_turn,
        "use_rag": use_rag_flag,
    }


def _finish_turn(sid, prepared, answer, user=None):
    answer = _after_think(answer).strip()
    _store(sid, "assistant", answer, prepared["snippets"])

    # 仅当标题仍是默认值时才自动命名，避免覆盖用户手动改过的标题
    session = get_session(sid, with_messages=True, user=user)
    title_pending = bool(prepared["first_turn"]) and (session.get("title") or DEFAULT_TITLE) == DEFAULT_TITLE
    if title_pending:
        # 先落兜底标题，LLM 总结成功后覆盖，避免列表一直显示「新会话」
        update("chat_session", {"title": _fallback_title(prepared["question"])}, "id=%s", (sid,))
        session = get_session(sid, with_messages=True, user=user)

    return {
        "session": session,
        "answer": answer,
        "snippets": prepared["snippets"],
        "memories": [
            {"id": m.get("id"), "kind": m.get("kind"), "content": m.get("content")}
            for m in prepared["memories"]
        ],
        "title_pending": title_pending,
    }


def ask_stream(sid, question, llm_config_id=_UNSET, prompt_id=_UNSET, use_rag=_UNSET, user=None):
    """流式问答：逐段产出 {'type': delta|replace|done|error}。"""
    prepared = prepare_turn(sid, question, llm_config_id, prompt_id, use_rag, user)
    yield {
        "type": "start",
        "session_id": sid,
        "snippets": prepared["snippets"],
        "memories": [
            {"id": m.get("id"), "kind": m.get("kind"), "content": m.get("content")}
            for m in prepared["memories"]
        ],
        "has_summary": bool((prepared["session"].get("summary") or "").strip()),
    }

    acc = []
    think_len = 0
    for kind, text in LLMService.stream_chat(prepared["messages"], prepared["cfg"]):
        if kind == "thinking":
            think_len += len(text)
            yield {"type": "thinking", "length": think_len, "text": text}
            continue
        acc.append(text)
        yield {"type": "delta", "content": text}

    answer = "".join(acc)
    cleaned = _after_think(answer)
    if cleaned and cleaned != answer.strip():
        # 少数模型仍会把推理写进正文，通知前端整体替换
        yield {"type": "replace", "content": cleaned}

    result = _finish_turn(sid, prepared, answer, user)
    yield {"type": "done", **result}

    me = _ctx_user(user)
    _spawn_post_turn(sid, me.get("id"), me.get("username"), int(result["session"].get("message_count") or 0))


def ask(sid, question, llm_config_id=_UNSET, prompt_id=_UNSET, use_rag=_UNSET, user=None):
    """非流式问答（接口兼容 / 兜底）。"""
    prepared = prepare_turn(sid, question, llm_config_id, prompt_id, use_rag, user)
    answer = LLMService.chat_complete(prepared["messages"], prepared["cfg"])
    result = _finish_turn(sid, prepared, answer, user)
    me = _ctx_user(user)
    _spawn_post_turn(sid, me.get("id"), me.get("username"), int(result["session"].get("message_count") or 0))
    return result
