# -*- coding: utf-8 -*-
from flask import g

from services.llm_service import LLMService, train_rag_query, train_system_for
from services.model_service import get_job
from utils.db import delete, insert, query
from utils.jsonx import dumps, loads, row_to_dict


def list_reports(keyword=None, target_col=None, model_type=None):
    user = getattr(g, "user", {}) or {}
    sql = (
        "SELECT r.*, j.name AS train_name, j.model_type, j.target_col "
        "FROM insight_report r "
        "LEFT JOIN train_job j ON j.id = r.train_job_id "
        "WHERE 1=1"
    )
    args = []
    if user.get("role") != "admin":
        sql += " AND r.user_id=%s"
        args.append(user.get("id"))
    if keyword and str(keyword).strip():
        like = f"%{str(keyword).strip()}%"
        sql += (
            " AND (IFNULL(r.title,'') LIKE %s OR IFNULL(j.name,'') LIKE %s"
            " OR IFNULL(r.username,'') LIKE %s OR IFNULL(j.target_col,'') LIKE %s"
            " OR IFNULL(j.model_type,'') LIKE %s)"
        )
        args.extend([like, like, like, like, like])
    if target_col:
        sql += " AND j.target_col=%s"
        args.append(target_col)
    if model_type:
        sql += " AND j.model_type=%s"
        args.append(model_type)
    sql += " ORDER BY r.id DESC"
    return [row_to_dict(r) for r in query(sql, args)]


def get_report(report_id):
    if not report_id:
        return None
    user = getattr(g, "user", {}) or {}
    sql = (
        "SELECT r.*, j.name AS train_name, j.model_type, j.target_col, j.metrics_json "
        "FROM insight_report r "
        "LEFT JOIN train_job j ON j.id = r.train_job_id "
        "WHERE r.id=%s"
    )
    args = [report_id]
    if user.get("role") != "admin":
        sql += " AND r.user_id=%s"
        args.append(user.get("id"))
    row = query(sql, args, one=True)
    if not row:
        return None
    data = row_to_dict(row)
    data["metrics"] = loads(row.get("metrics_json"), default={}) if row.get("metrics_json") else {}
    return data


def latest_for_job(train_job_id):
    if not train_job_id:
        return None
    return query(
        "SELECT * FROM insight_report WHERE train_job_id=%s ORDER BY id DESC",
        (train_job_id,), one=True,
    )


def create_raw(title, content, train_job_id=None, predict_job_id=None, rag_context=None,
               llm_config_id=None, prompt_id=None, user=None):
    """不调用大模型，直接把已有正文写入洞察报告（DAG 已生成内容时用）。"""
    user = user or getattr(g, "user", {}) or {}
    return insert("insight_report", {
        "title": title,
        "train_job_id": train_job_id,
        "predict_job_id": predict_job_id,
        "content": content or "",
        "rag_context": rag_context,
        "llm_config_id": llm_config_id,
        "prompt_id": prompt_id,
        "user_id": user.get("id"),
        "username": user.get("username"),
    })


def create_from_train(train_job_id, llm_config_id=None, prompt_id=None, use_rag=True,
                      question=None, system_prompt=None):
    """训练任务生成洞察报告。

    - prompt_id：平台「系统提示词」模板，内容作为指令主体；
    - system_prompt：用户自定义系统提示词，优先级高于 prompt_id；
    - question：用户短问题，可选、允许为空，召回为空也不影响输出。
    """
    user = getattr(g, "user", {}) or {}
    job = get_job(train_job_id)
    if not job:
        raise ValueError("训练任务不存在")
    col = job.get("target_col") or ""
    label = LLMService.TARGET_CN.get(col, col or "目标")

    instruction = (system_prompt or "").strip()
    if not instruction and prompt_id:
        tpl = LLMService.get_prompt(prompt_id) or {}
        instruction = (tpl.get("content") or "").strip()
    if not instruction:
        instruction = train_system_for(job)

    question = (question or "").strip()
    rag_query = train_rag_query(job, label, col, question)
    content, snippets, _, _ = LLMService.generate_report(
        instruction,
        question,
        {
            "metrics": dumps(job.get("metrics") or {}),
            "importance": dumps((job.get("importance") or [])[:15]),
            "predictions": "",
        },
        llm_config_id=llm_config_id,
        use_rag=use_rag,
        top_k=6,
        rag_query=rag_query,
    )
    rid = insert("insight_report", {
        "title": f"洞察报告 - {job.get('name')}",
        "train_job_id": train_job_id,
        "content": content,
        "rag_context": dumps(snippets),
        "llm_config_id": llm_config_id,
        "prompt_id": prompt_id,
        "user_id": user.get("id"),
        "username": user.get("username"),
    })
    return query("SELECT * FROM insight_report WHERE id=%s", (rid,), one=True)


def delete_report(report_id):
    row = get_report(report_id)
    if not row:
        raise ValueError("洞察报告不存在")
    delete("insight_report", "id=%s", (report_id,))
    return True


def delete_reports(ids):
    user = getattr(g, "user", {}) or {}
    wanted = []
    for raw in ids or []:
        try:
            wanted.append(int(raw))
        except (TypeError, ValueError):
            continue
    wanted = list(dict.fromkeys(wanted))
    if not wanted:
        return {"deleted": 0}
    rows = []
    for rid in wanted:
        row = get_report(rid)
        if row:
            rows.append(row)
    if user.get("role") != "admin":
        uid = user.get("id")
        rows = [r for r in rows if r.get("user_id") == uid]
    n = 0
    for row in rows:
        n += int(delete("insight_report", "id=%s", (row["id"],)) or 0)
    return {"deleted": n}
