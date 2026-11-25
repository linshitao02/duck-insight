# -*- coding: utf-8 -*-
from flask import g

from services import power_engine
from services.llm_service import LLMService
from utils.db import query
from utils.jsonx import dumps, row_to_dict


def _n(v, d=0):
    try:
        return round(float(v), d)
    except Exception:
        return 0


def facts_markdown(facts):
    k = facts.get("kpis") or {}
    st = facts.get("strategy_summary") or "暂无策略摘要"
    actions = facts.get("actions") or []
    alerts = facts.get("alerts") or []
    shocks = facts.get("shocks") or {}
    src = facts.get("sources") or "Open-Meteo"
    act_txt = "\n".join([f"- **{a.get('title')}**：{a.get('detail')}" for a in actions]) or "- 暂无"
    alert_txt = "\n".join(
        [f"- [{a.get('level')}] {a.get('title')}：{a.get('message')}" for a in alerts[:8]]
    ) or "- 未来 72h 未触发阈值告警"
    sh_txt = "、".join(
        [f"{name} Δ负荷 {v.get('delta_load_mw')} MW / Δ电价 {v.get('delta_price')} 元"
         for name, v in shocks.items()]
    ) or "无"
    return f"""# 气象-电力市场关联分析报告

> 数字均来自系统当日计算，报价/套利/对冲需交易员确认后执行，系统不下单。

## 1. 气象预测与数据治理
数据源：{src}。当前气温 {_n(k.get('temp'), 1)}℃。
已完成多源融合：ERA5 实况、ECMWF/GFS 短期至 16 日预报、去年同期气候态平移覆盖 17–45 日展望。
质控对气温、湿度、降水、风速、辐照施加物理阈值并统一单位（℃ / m/s / W/m²）。

## 2. 负荷与新能源出力
当前系统负荷 {_n(k.get('load'), 0)} MW，风电 {_n(k.get('wind'), 0)} MW，光伏 {_n(k.get('solar'), 0)} MW，新能源渗透 {k.get('renew_share')}%。
负荷由气温 HDD/CDD 与日内形状驱动；风电按切入/额定/切出曲线，光伏按辐照与高温折损。
极端天气冲击量化：{sh_txt}。

## 3. 电价预测与交易支持
日前 {_n(k.get('price_da'), 0)} 元/MWh，实时 {_n(k.get('price_rt'), 0)} 元/MWh，阻塞指数 {_n(k.get('congestion'), 2)}。
{st}
建议动作：
{act_txt}

## 4. 风险预警与决策支撑
{alert_txt}
看板已联立气象-负荷-出力-电价。突发天气以告警流即时提示，关联结论见上节策略，执行前请人工复核偏差考核风险。

## 5. 模型迭代与工具建设
本轮由电力交易 DAG 编排驱动：采集→质控→特征/冲击→负荷/风光/电价→规则与预警→报告。
建议日复盘关注：新能源预测误差、阻塞时段价差、热浪/大风切出情景；特征工程保持 HDD/CDD、风速立方、辐照可复用。
"""


def generate_decision_report():
    cockpit = power_engine.cockpit_payload()
    kpis = cockpit.get("kpis") or {}
    strategy = cockpit.get("strategy") or {}
    alerts = cockpit.get("alerts") or []
    shocks = cockpit.get("shocks") or {}
    facts = {
        "kpis": kpis,
        "strategy_summary": strategy.get("summary"),
        "actions": strategy.get("actions"),
        "alerts": [{"level": a.get("level"), "title": a.get("title"), "message": a.get("message")} for a in alerts[:8]],
        "shocks": {
            k: {"delta_load_mw": v.get("delta_load_mw"), "delta_price": v.get("delta_price")}
            for k, v in shocks.items()
        },
        "sources": (cockpit.get("meta") or {}).get("sources"),
    }
    draft = facts_markdown(facts)
    variables = {
        "metrics": dumps(facts),
        "importance": "",
        "predictions": dumps((cockpit.get("daily") or [])[-10:]),
        "question": "请润色并输出五节决策报告",
    }
    snippets = []
    answer = ""
    try:
        answer, snippets = LLMService.analyze_with_template(
            "电力 气象 负荷 新能源 电价 阻塞 报价 风险",
            variables,
            scene="power_decision",
            use_rag=True,
        )
        answer = _strip_think(answer)
    except Exception as e:
        answer = f"（本地模型调用失败：{e}）"
    if _is_usable_report(answer):
        body = answer
    else:
        note = "本地 qwen3:4b 已调用；本次输出仍为思考草稿，以下正文由系统按实测数字整理，确保覆盖岗位五节。"
        if answer and "调用失败" in answer:
            note = answer
        body = draft + f"\n\n---\n\n*{note}*"
    user = {}
    try:
        from flask import has_request_context
        if has_request_context():
            user = getattr(g, "user", None) or {}
    except Exception:
        user = {}
    rid = power_engine.save_report(
        "气象-电力市场关联分析报告",
        body,
        dumps([{"source": s.get("source"), "text": s.get("text")} for s in snippets[:6]]),
        user,
    )
    row = query("SELECT * FROM power_report WHERE id=%s", (rid,), one=True)
    return row_to_dict(row) if row else {"id": rid, "content": body}


def _is_usable_report(text):
    """判断 LLM 产出是否可直接作为报告正文。

    旧版关键词表只覆盖「气象/负荷/电价/预警/模型」，光伏、风电等单目标
    训练报告的正文里往往不含「电价/预警」，会被误判成不可用而整篇走兜底。
    这里放宽为更广的电力域词表，并要求命中 3 个。
    """
    if not text or len(text) < 240:
        return False
    head = text[:80]
    if "首先" in head or "用户要求" in head or "我需要" in head:
        return False
    keys = (
        "气象", "负荷", "电价", "预警", "模型", "光伏", "风电", "风光",
        "出力", "辐照", "风速", "预测", "特征", "偏差", "消纳", "训练",
        "调度", "考核", "功率",
    )
    return sum(k in text for k in keys) >= 3


def _strip_think(text):
    if not text:
        return ""
    out = str(text)
    if "</think>" in out:
        out = out.split("</think>", 1)[-1]
    return out.replace("<think>", "").strip()
