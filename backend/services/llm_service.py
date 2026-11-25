# -*- coding: utf-8 -*-
import json
import re

import requests
from flask import g

from config import DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL, DEFAULT_SYSTEM_PROMPT
from services.rag_service import get_rag_service
from utils.db import delete, insert, query, update
from utils.jsonx import dumps, row_to_dict


POWER_TRAIN_SYSTEM = (
    "你是电力现货市场的预测分析岗。只输出最终中文正文，禁止思考提纲。"
    "数字必须来自【评估指标】和【特征重要性】，禁止编造。"
    "按 5 节写：1) 本轮训练与关键特征 2) 预测表现与误差形态 "
    "3) 业务含义与调度/交易影响（须写需人工确认，系统未下单）"
    "4) 数据质量、泄漏与局限 5) 论文方法节/企业附件可直接改写的结论。"
)
GENERIC_TRAIN_SYSTEM = (
    "你是通用数据分析平台的建模分析岗。只输出最终中文正文，禁止思考提纲。"
    "数字必须来自【评估指标】和【特征重要性】，禁止编造，也不要套用材料里没有的行业。"
    "按 5 节写：1) 本轮训练与关键特征 2) 预测表现与误差形态 "
    "3) 这些字段可能代表的业务含义（须写需人工确认）"
    "4) 数据质量、泄漏与局限 5) 可直接放进分析报告的结论。"
)


def train_system_for(job):
    scenario = str((job or {}).get("scenario_code") or "").lower()
    if any(key in scenario for key in ("power", "weather", "electric")):
        return POWER_TRAIN_SYSTEM
    return GENERIC_TRAIN_SYSTEM


def train_rag_query(job, label, col, question=""):
    question = (question or "").strip()
    if question:
        return question
    scenario = str((job or {}).get("scenario_code") or "").lower()
    if any(key in scenario for key in ("power", "weather", "electric")):
        return f"{label} {col} 特征重要性 评估指标 气象 电价 负荷 偏差考核 局限"
    return f"{label} {col} 特征重要性 评估指标 误差 数据质量 局限"


def _strip_think(text):
    if not text:
        return ""
    out = str(text)
    if "</think>" in out:
        out = out.split("</think>", 1)[-1]
    out = out.replace("<think>", "").strip()
    return _strip_instruction_echo(out)


_ECHO_PREFIX = (
    r"^(首先|其次|用户要求|你是|关键点|提供的材料|完成三个|禁止复述|按 \d 节"
    r"|以下是根据|以下是基于|根据您的要求|根据您提供|根据提供的|基于您提供|基于提供的"
    r"|我将|我会|下面我|本次报告将|好的|收到)"
)


def _strip_instruction_echo(text):
    """qwen 小模型常把任务说明复述一遍，截到真正正文。"""
    raw = (text or "").strip()
    if not raw:
        return ""
    heading = re.search(r"(?m)^#{1,3}\s+\S", raw)
    if heading:
        prelude = raw[:heading.start()].strip()
        # 大纲式复述一般很短；短前缀直接丢弃，正文从第一个标题开始
        if len(prelude) <= 260 or re.match(_ECHO_PREFIX, raw):
            return raw[heading.start():].strip()
    lines = raw.splitlines()
    skip = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            skip = i + 1
            continue
        if re.match(_ECHO_PREFIX, s):
            skip = i + 1
            continue
        if re.match(r"^\d+[\.、]\s*(用业务|指出可能|给出)", s):
            skip = i + 1
            continue
        break
    cleaned = "\n".join(lines[skip:]).strip()
    return cleaned or raw


def serialize_llm(row):
    if not row:
        return None
    data = row_to_dict(row)
    data["model"] = data.get("model_name")
    return data


def serialize_prompt(row):
    return row_to_dict(row) if row else None


class LLMService:
    @staticmethod
    def list_llm():
        return [serialize_llm(r) for r in query("SELECT * FROM llm_config ORDER BY is_default DESC, id DESC")]

    @staticmethod
    def get_llm(cid):
        return serialize_llm(query("SELECT * FROM llm_config WHERE id=%s", (cid,), one=True))

    @staticmethod
    def default_llm():
        row = query("SELECT * FROM llm_config WHERE is_default=1 AND status=1 ORDER BY id DESC", one=True)
        return serialize_llm(row) or (LLMService.list_llm()[0] if LLMService.list_llm() else None)

    @staticmethod
    def save_llm(payload, cid=None):
        user = getattr(g, "user", {}) or {}
        data = {
            "name": payload.get("name"),
            "model_name": payload.get("model") or payload.get("model_name"),
            "api_key": payload.get("api_key"),
            "base_url": payload.get("base_url"),
            "temperature": payload.get("temperature", 0.7),
            "max_tokens": payload.get("max_tokens", 2000),
            "is_local_llm": payload.get("is_local_llm", 0),
            "is_default": payload.get("is_default", 0),
            "status": payload.get("status", 1),
            "user_id": user.get("id"),
            "username": user.get("username"),
        }
        # 系统提示词已不在「LLM 配置」里维护：显式传入才更新，新建时才落平台默认值，
        # 避免每次保存都把库中已有值重置成默认值。
        if payload.get("system_prompt") is not None:
            data["system_prompt"] = payload.get("system_prompt")
        elif not cid:
            data["system_prompt"] = DEFAULT_SYSTEM_PROMPT
        if data.get("is_default"):
            update("llm_config", {"is_default": 0}, "1=1", [])
        if cid:
            update("llm_config", data, "id=%s", (cid,))
            return LLMService.get_llm(cid)
        return LLMService.get_llm(insert("llm_config", data))

    @staticmethod
    def delete_llm(cid):
        delete("llm_config", "id=%s", (cid,))

    @staticmethod
    def list_prompts(scene=None, qa_only=None, prompt_kind=None):
        sql = "SELECT * FROM prompt_template WHERE status=1"
        args = []
        if scene:
            sql += " AND scene=%s"
            args.append(scene)
        if qa_only is not None:
            sql += " AND qa_only=%s"
            args.append(qa_only)
        if prompt_kind:
            sql += " AND prompt_kind=%s"
            args.append(prompt_kind)
        sql += " ORDER BY is_default DESC, id DESC"
        return [serialize_prompt(r) for r in query(sql, args)]

    @staticmethod
    def get_prompt(pid):
        return serialize_prompt(query("SELECT * FROM prompt_template WHERE id=%s", (pid,), one=True))

    @staticmethod
    def save_prompt(payload, pid=None):
        user = getattr(g, "user", {}) or {}
        data = {
            "name": payload.get("name"),
            "scene": payload.get("scene"),
            "content": payload.get("content"),
            "placeholders": payload.get("placeholders") or "{metrics},{importance},{predictions},{context},{question}",
            "is_default": payload.get("is_default", 0),
            "qa_only": payload.get("qa_only", 0),
            "prompt_kind": payload.get("prompt_kind") or "system",
            "status": payload.get("status", 1),
            "user_id": user.get("id"),
            "username": user.get("username"),
        }
        if pid:
            update("prompt_template", data, "id=%s", (pid,))
            return LLMService.get_prompt(pid)
        return LLMService.get_prompt(insert("prompt_template", data))

    @staticmethod
    def delete_prompt(pid):
        delete("prompt_template", "id=%s", (pid,))

    @staticmethod
    def _resolve(llm_config_id=None, prompt_id=None, scene=None):
        cfg = LLMService.get_llm(llm_config_id) if llm_config_id else LLMService.default_llm()
        if not cfg:
            cfg = {
                "model_name": DEFAULT_LLM_MODEL,
                "base_url": DEFAULT_LLM_BASE_URL,
                "temperature": 0.5,
                "max_tokens": 2000,
                "system_prompt": DEFAULT_SYSTEM_PROMPT,
                "is_local_llm": 0,
            }
        prompt = None
        if prompt_id:
            prompt = LLMService.get_prompt(prompt_id)
        elif scene:
            rows = LLMService.list_prompts(scene=scene)
            prompt = rows[0] if rows else None
        return cfg, prompt

    @staticmethod
    def chat_complete(messages, cfg, think=True):
        """一次性补全。

        think=True 时推理走 message.thinking，content 只保留干净正文（默认）；
        短小的结构化任务（标题/摘要/记忆抽取）建议 think=False —— 这类任务的
        思考会占满 num_predict，导致正文为空。
        """
        base = (cfg.get("base_url") or DEFAULT_LLM_BASE_URL).rstrip("/")
        model = cfg.get("model_name") or cfg.get("model") or DEFAULT_LLM_MODEL
        api_key = cfg.get("api_key") or ""
        temperature = float(cfg.get("temperature") or 0.7)
        max_tokens = int(cfg.get("max_tokens") or 2000)
        is_local = int(cfg.get("is_local_llm") or 0)

        if not is_local and not api_key:
            raise RuntimeError("尚未配置 LLM API Key：请在「LLM 配置」页面新增模型并填写 Key")

        if is_local and "11434" in base and not base.endswith("/v1"):
            payload = {
                "model": model,
                "messages": messages,
                # 推理走 message.thinking，content 只保留最终结果
                "options": {
                    "temperature": temperature,
                    # 报告类生成需要留足预算：思考型模型（qwen3 等）的 reasoning 也计入
                    # num_predict，预算太小会出现正文只写了一半就被截断的情况。
                    "num_predict": max(max_tokens, 8000 if think else 800),
                },
                "stream": False,
                "think": bool(think),
            }
            resp = requests.post("http://localhost:11434/api/chat", json=payload, timeout=600)
            resp.raise_for_status()
            data = resp.json()
            return _strip_think((data.get("message") or {}).get("content") or "")

        if not base.endswith("/v1") and "compatible-mode" not in base:
            if "dashscope.aliyuncs.com" in base:
                base = DEFAULT_LLM_BASE_URL
        url = base + "/chat/completions" if not base.endswith("/chat/completions") else base
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=300)
        if resp.status_code >= 400:
            raise RuntimeError(f"LLM 调用失败 {resp.status_code}: {resp.text[:400]}")
        data = resp.json()
        return _strip_think(data["choices"][0]["message"]["content"])

    @staticmethod
    def stream_chat(messages, cfg):
        """逐段产出 (kind, text)，kind 为 'thinking' 或 'content'。

        思考型模型（qwen3 等）的推理过程放在独立的 thinking 通道，
        与正文分离，避免推理内容混入回答。
        """
        base = (cfg.get("base_url") or DEFAULT_LLM_BASE_URL).rstrip("/")
        model = cfg.get("model_name") or cfg.get("model") or DEFAULT_LLM_MODEL
        api_key = cfg.get("api_key") or ""
        is_local = int(cfg.get("is_local_llm") or 0)

        if not is_local and not api_key:
            raise RuntimeError("尚未配置 LLM API Key：请在「LLM 配置」页面新增模型并填写 Key")

        if is_local and "11434" in base:
            payload = {
                "model": model,
                "messages": messages,
                "stream": True,
                # 开启 think：ollama 会把推理放进 message.thinking，正文只留最终回答
                "think": True,
                "options": {
                    "temperature": float(cfg.get("temperature") or 0.7),
                    # 思考也占用 num_predict，留足预算避免正文被截断
                    "num_predict": max(int(cfg.get("max_tokens") or 2000), 4096),
                },
            }
            with requests.post("http://localhost:11434/api/chat", json=payload, stream=True, timeout=600) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    data = json.loads(line.decode("utf-8"))
                    msg = data.get("message") or {}
                    if msg.get("thinking"):
                        yield "thinking", msg["thinking"]
                    if msg.get("content"):
                        yield "content", msg["content"]
                    if data.get("done"):
                        break
            return
        if "dashscope.aliyuncs.com" in base and not base.endswith("/v1"):
            base = DEFAULT_LLM_BASE_URL
        url = base + "/chat/completions" if not base.endswith("/chat/completions") else base
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": float(cfg.get("temperature") or 0.7),
            "max_tokens": int(cfg.get("max_tokens") or 2000),
        }
        with requests.post(url, headers=headers, json=payload, stream=True, timeout=600) as resp:
            resp.raise_for_status()
            for raw in resp.iter_lines():
                if not raw:
                    continue
                line = raw.decode("utf-8")
                if not line.startswith("data:"):
                    continue
                body = line[5:].strip()
                if body == "[DONE]":
                    break
                try:
                    data = json.loads(body)
                    delta = data["choices"][0].get("delta") or {}
                    # 部分厂商（如 dashscope 的 qwen3）用 reasoning_content 返回推理
                    if delta.get("reasoning_content"):
                        yield "thinking", delta["reasoning_content"]
                    if delta.get("content"):
                        yield "content", delta["content"]
                except Exception:
                    continue

    @staticmethod
    def stream_complete(messages, cfg):
        """只产出正文（兼容旧调用方）。"""
        for kind, text in LLMService.stream_chat(messages, cfg):
            if kind == "content":
                yield text

    @staticmethod
    def fill_prompt(template, variables):
        text = template or ""
        for k, v in variables.items():
            text = text.replace("{" + k + "}", v if isinstance(v, str) else dumps(v))
        return text

    # 数据块模板：指令里没写占位符时，作为兜底把数字喂给模型
    DATA_BLOCK_TEMPLATE = (
        "【评估指标】\n{metrics}\n\n"
        "【特征重要性】\n{importance}\n\n"
        "【预测切片】\n{predictions}\n\n"
        "【知识库召回片段】\n{context}"
    )
    DATA_SLOTS = ("{metrics}", "{importance}", "{predictions}", "{context}")
    NO_SNIPPET = "（本次未检索到相关片段，请仅依据上方数据作答）"

    @staticmethod
    def retrieve(query, use_rag=True, top_k=None):
        """短问题为空 / 不需要召回时直接返回空片段，不阻塞输出。"""
        text = (query or "").strip()
        if not use_rag or not text:
            return []
        try:
            return get_rag_service().search(text, top_k=top_k) or []
        except Exception:
            return []

    @staticmethod
    def render_context(snippets):
        return "\n\n".join(
            f"[{s.get('source')}#{s.get('idx', 0)}] {s.get('text', '')}" for s in (snippets or [])
        ) or LLMService.NO_SNIPPET

    @staticmethod
    def generate_report(prompt_text, question, variables, llm_config_id=None,
                        use_rag=True, top_k=6, rag_query=None, default_system=None):
        """DAG / 模型洞察统一的报告生成。

        - 「系统提示词」prompt_text 是唯一指令来源（平台模板或用户自定义），
          可写 {metrics}/{importance}/{predictions}/{context}/{question} 占位符；
        - 「用户短问题」question 可选，允许为空；
        - 召回允许为空，都不影响报告输出。

        返回 (answer, snippets, system_prompt, question)。
        """
        cfg, _ = LLMService._resolve(llm_config_id, None, None)
        question = (question or "").strip()
        prompt_text = (prompt_text or "").strip() or (default_system or "").strip() or DEFAULT_SYSTEM_PROMPT
        snippets = LLMService.retrieve(rag_query or question, use_rag=use_rag, top_k=int(top_k or 6))

        values = dict(variables or {})
        values["context"] = LLMService.render_context(snippets)
        values["question"] = question

        system = LLMService.fill_prompt(prompt_text, values)
        if not any(slot in prompt_text for slot in LLMService.DATA_SLOTS):
            system = f"{system}\n\n{LLMService.fill_prompt(LLMService.DATA_BLOCK_TEMPLATE, values)}"
        user = question or "请依据系统提示与数据，直接输出最终中文报告正文。"
        if snippets:
            user += f"\n\n（知识库召回 {len(snippets)} 条，见上方片段）"

        answer = LLMService.chat_complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}], cfg,
        )
        return answer, snippets, system, question

    @staticmethod
    def analyze_with_template(query_text, variables, llm_config_id=None, prompt_id=None, scene="insight",
                              use_rag=True, system_prompt=None, rag_query=None, top_k=None):
        cfg, prompt = LLMService._resolve(llm_config_id, prompt_id, scene)
        rag_text = (rag_query or query_text or variables.get("question") or "").strip()
        snippets = LLMService.retrieve(rag_text, use_rag=use_rag, top_k=top_k)
        context = LLMService.render_context(snippets)
        variables = dict(variables)
        variables["context"] = context
        content = LLMService.fill_prompt((prompt or {}).get("content") or cfg.get("system_prompt"), variables)
        if int(cfg.get("is_local_llm") or 0):
            content += "\n\n直接输出最终中文正文，不要输出思考提纲或草稿。"
        sys_msg = (system_prompt or "").strip() or cfg.get("system_prompt") or DEFAULT_SYSTEM_PROMPT
        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": content},
        ]
        answer = LLMService.chat_complete(messages, cfg)
        return answer, snippets

    @staticmethod
    def analyze_predictions(records, llm_config_id=None, prompt_id=None, use_rag=True,
                            question=None, system_prompt=None):
        """预测结果的业务解读。

        - system_prompt（用户自定义系统提示词）优先，其次 prompt_id 模板，最后按 predict 场景取默认；
        - 用户短问题可选、允许为空；
        - 知识库召回为空也照常输出，不做拒答。
        """
        text = dumps(records[:40])
        _cfg, tpl = LLMService._resolve(llm_config_id, prompt_id, "predict")
        instruction = (system_prompt or "").strip() or ((tpl or {}).get("content") or "").strip()
        question = (question or "").strip()
        rag_query = question or f"{tpl.get('name') if tpl else '预测结果'} 预测结果 评估指标 特征重要性 气象 电价 负荷 偏差考核"
        answer, snippets, _system, _question = LLMService.generate_report(
            instruction,
            question,
            {"predictions": text, "metrics": "", "importance": ""},
            llm_config_id=llm_config_id,
            use_rag=use_rag,
            top_k=6,
            rag_query=rag_query,
        )
        return answer, snippets

    TARGET_CN = {
        "load_mw": "用电负荷",
        "wind_mw": "风电出力",
        "solar_mw": "光伏出力",
        "renewable_mw": "风光出力",
        "price_da": "日前电价",
    }

    @staticmethod
    def analyze_training(job, llm_config_id=None, prompt_id=None, use_rag=True,
                         question=None, system_prompt=None):
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
        answer, snippets, _, _ = LLMService.generate_report(
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
        return answer, snippets

    @staticmethod
    def ask(question, llm_config_id=None, prompt_id=None, use_rag=True):
        return LLMService.analyze_with_template(
            question, {"question": question, "metrics": "", "importance": "", "predictions": ""},
            llm_config_id, prompt_id, scene="qa", use_rag=use_rag,
        )
