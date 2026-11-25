# -*- coding: utf-8 -*-
"""训练实验材料：种子/参数/指标/重要性/局限/图表/LLM 洞察。"""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from datetime import datetime

import numpy as np

from services.model_service import get_job, training_limitations
from utils.field_labels import feature_tick


TARGET_CN = {
    "load_mw": "用电负荷",
    "wind_mw": "风电出力",
    "solar_mw": "光伏出力",
    "renewable_mw": "风光出力",
    "price_da": "日前电价",
    "price_rt": "实时电价",
    "residual_mw": "残余负荷",
    "Sales": "销售额",
}


def _safe_filename_part(value, fallback, limit=36):
    text = re.sub(r'[\\/:*?"<>|]+', "_", str(value or fallback))
    text = re.sub(r"\s+", "_", text).strip("_")
    return (text or fallback)[:limit]


def _insight_filename(data, ext, report_id=None):
    train_name = _safe_filename_part(
        data.get("train_name") or data.get("name") or data.get("title"),
        "未命名任务",
    )
    model_type = _safe_filename_part(data.get("model_type"), "model", 24)
    target_col = _safe_filename_part(data.get("target_col"), "target", 24)
    raw_time = str(data.get("create_time") or "")
    matched = re.search(r"\d{4}[-/]?\d{2}[-/]?\d{2}", raw_time)
    date = re.sub(r"\D", "", matched.group(0)) if matched else datetime.now().strftime("%Y%m%d")
    rid = report_id or data.get("id") or "new"
    return f"洞察报告_{train_name}_{model_type}_{target_col}_{date}_#{rid}.{ext}"

TARGET_UNIT = {
    "price_da": "元/MWh",
    "price_rt": "元/MWh",
    "load_mw": "MW",
    "wind_mw": "MW",
    "solar_mw": "MW",
    "renewable_mw": "MW",
    "residual_mw": "MW",
    "Sales": "元",
}


def _target_axis(job):
    col = job.get("target_col") or ""
    zh = TARGET_CN.get(col, col or "目标值")
    unit = TARGET_UNIT.get(col)
    return f"{zh}（{unit}）" if unit else zh


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    return plt


def _png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight", facecolor="white")
    plt = _plt()
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _utf8_info(name):
    info = zipfile.ZipInfo(name)
    info.date_time = datetime.now().timetuple()[:6]
    info.compress_type = zipfile.ZIP_DEFLATED
    info.flag_bits |= 0x800
    return info


def _chart_importance(job):
    items = (job.get("importance") or [])[:15]
    if not items:
        return None
    names = [feature_tick(i.get("feature") or i.get("name") or "") for i in items][::-1]
    scores = [float(i.get("score") or i.get("importance") or 0) for i in items][::-1]
    plt = _plt()
    fig, ax = plt.subplots(figsize=(8.4, 4.8))
    ax.barh(names, scores, color="#1d6fd8")
    ax.set_title("特征重要性")
    ax.set_xlabel("重要性得分（模型增益，无量纲）")
    ax.set_ylabel("输入特征")
    fig.tight_layout()
    return _png(fig)


def _chart_actual_pred(job):
    curves = job.get("curves") or {}
    actual = curves.get("actual") or []
    pred = curves.get("pred") or []
    if not actual or not pred:
        return None
    plt = _plt()
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    xs = list(range(len(actual)))
    ax.plot(xs, actual, color="#c2410c", label="实际")
    ax.plot(xs, pred, color="#1d6fd8", label="预测")
    ax.set_title("验证集抽样：实际 vs 预测")
    ax.set_xlabel("验证样本序号（hold-out 抽样，不是时间）")
    ax.set_ylabel(_target_axis(job))
    ax.legend()
    fig.tight_layout()
    return _png(fig)


def _chart_history(job):
    history = (job.get("curves") or {}).get("history") or {}
    train = history.get("train") or []
    valid = history.get("valid") or []
    if not train and not valid:
        return None
    metric = history.get("metric") or "rmse"
    space = history.get("space") or "raw"
    plt = _plt()
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    space_cn = "log1p 拟合空间，越小越好" if space == "log1p" else "原始量纲，越小越好"
    x_key = history.get("x_name")
    x_name = (
        "树的数量（n_estimators）" if x_key == "n_estimators"
        else "树深度（max_depth）" if x_key in ("tree_depth", "max_depth")
        else "正则系数 C" if x_key in ("svm_C", "C")
        else "正则强度 alpha" if x_key == "alpha"
        else "训练样本数" if x_key == "n_samples"
        else "训练轮次（epoch）" if x_key == "epoch"
        else "训练轮次（iteration）"
    )
    xs = history.get("x") or list(range(1, max(len(train), len(valid)) + 1))
    ax.set_title(f"训练过程 {str(metric).upper()}")
    if train:
        ax.plot(xs[:len(train)], train, color="#0f766e", label="train")
    if valid:
        ax.plot(xs[:len(valid)], valid, color="#1d6fd8", label="valid")
    ax.set_xlabel(x_name)
    ax.set_ylabel(f"{str(metric).upper()}（{space_cn}）")
    ax.legend()
    fig.tight_layout()
    return _png(fig)


def _ensure_residual_hist(curves):
    hist = (curves or {}).get("residual_hist") or {}
    if hist.get("counts"):
        return hist
    actual = np.array((curves or {}).get("actual") or [], dtype=float)
    pred = np.array((curves or {}).get("pred") or [], dtype=float)
    if not len(actual) or len(pred) != len(actual):
        return {}
    residuals = pred - actual
    n_bins = int(min(24, max(8, np.sqrt(max(len(residuals), 1)))))
    counts, bins = np.histogram(residuals, bins=n_bins)
    return {"bins": bins.tolist(), "counts": [int(v) for v in counts]}


def _chart_residual(job):
    hist = _ensure_residual_hist(job.get("curves") or {})
    counts = hist.get("counts") or []
    bins = hist.get("bins") or []
    if not counts or len(bins) < 2:
        return None
    centers = [(float(bins[i]) + float(bins[i + 1])) / 2 for i in range(len(counts))]
    width = (float(bins[1]) - float(bins[0])) if len(bins) > 1 else 1
    plt = _plt()
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    ax.bar(centers, counts, width=width * 0.92, color="#1d6fd8", align="center")
    ax.set_title("残差分布（预测 − 实际）")
    ax.set_xlabel(f"残差 = 预测 − 实际（{_target_axis(job)}）")
    ax.set_ylabel("样本频数（个）")
    fig.tight_layout()
    return _png(fig)


def _methods_markdown(job):
    label = TARGET_CN.get(job.get("target_col"), job.get("target_col") or "目标")
    metrics = job.get("metrics") or {}
    params = job.get("params") or {}
    importance = job.get("importance") or []
    metric_lines = []
    for k, v in metrics.items():
        if isinstance(v, (int, float)):
            metric_lines.append(f"- **{k}** = {round(float(v), 6)}")
        elif v is not None:
            metric_lines.append(f"- **{k}** = {v}")
    feat_lines = []
    for i, item in enumerate(importance[:20], 1):
        name = item.get("feature") or item.get("name") or "-"
        score = item.get("score") if item.get("score") is not None else item.get("importance")
        feat_lines.append(f"{i}. `{feature_tick(name)}`：{score}")
    history = (job.get("curves") or {}).get("history") or {}
    n_rounds = max(len(history.get("train") or []), len(history.get("valid") or []))
    insight = (job.get("insight") or "").strip()
    return "\n".join([
        f"# 训练方法节草稿：{job.get('name')}",
        "",
        f"> 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}。数字来自本轮训练记录，可直接改写入论文方法/实验节或作为企业附件。系统未下单。",
        "",
        "## 1. 任务与数据",
        f"- 任务：{job.get('name')}（id={job.get('id')}）",
        f"- 目标列：`{job.get('target_col')}`（{label}）",
        f"- 任务类型：{job.get('task_type') or 'regression'}",
        f"- 算法：{job.get('model_type')}",
        f"- 参数预设：{job.get('param_preset') or '-'}",
        f"- 特征数：{len(job.get('feature_cols') or [])}",
        f"- 抽样行数：{job.get('sample_rows') or 0}（0 表示全量）",
        "",
        "## 2. 可复现设置",
        f"- random_state / 种子：`{job.get('random_state') or 42}`",
        f"- 验证集比例 test_size：`{job.get('test_size')}`",
        f"- log1p 目标：{'是' if job.get('log_target') else '否'}",
        f"- 训练耗时：{job.get('duration_sec') or '-'} s",
        "",
        "### 超参数",
        "```json",
        json.dumps(params, ensure_ascii=False, indent=2),
        "```",
        "",
        "### 特征列",
        ", ".join(f"`{c}`" for c in (job.get("feature_cols") or [])) or "（无）",
        "",
        "## 3. 评估指标",
        "\n".join(metric_lines) or "（无）",
        "",
        "## 4. 训练过程",
        f"- 逐轮记录：{n_rounds} 轮，指标 `{history.get('metric') or '-'}`，空间 `{history.get('space') or '-'}`。",
        "- 图见 `charts/`：特征重要性、实际 vs 预测、训练曲线、残差直方图。",
        "",
        "## 5. 特征重要性（Top）",
        "\n".join(feat_lines) or "（无）",
        "",
        "## 6. 局限说明",
        training_limitations(job),
        "",
        "## 7. LLM 洞察",
        insight or "（尚未生成。在训练页点击「LLM 洞察」后重新导出即可附上。）",
        "",
    ])


def build_insight_markdown(job_id):
    job = get_job(job_id)
    if not job:
        raise ValueError("训练任务不存在")
    content = (job.get("insight") or "").strip()
    if not content:
        raise ValueError("尚未生成洞察报告，请先点击「LLM 洞察」")
    title = job.get("insight_title") or f"洞察报告 - {job.get('name')}"
    text = f"# {title}\n\n{content}\n"
    bio = io.BytesIO(text.encode("utf-8-sig"))
    bio.seek(0)
    return bio, _insight_filename(job, "md", f"job-{job_id}")


def _xml_text(s):
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _w_p(text, style=None):
    pr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return (
        f"<w:p>{pr}<w:r><w:rPr><w:rFonts w:ascii=\"Calibri\" w:eastAsia=\"Microsoft YaHei\"/></w:rPr>"
        f"<w:t xml:space=\"preserve\">{_xml_text(text)}</w:t></w:r></w:p>"
    )


def markdown_to_docx_bytes(title, content, subtitle=""):
    parts = [_w_p(title or "洞察报告", "Title")]
    if subtitle:
        parts.append(_w_p(subtitle, "Subtitle"))
    for raw in (content or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            parts.append("<w:p/>")
            continue
        if line.startswith("### "):
            parts.append(_w_p(line[4:].strip(), "Heading3"))
        elif line.startswith("## "):
            parts.append(_w_p(line[3:].strip(), "Heading2"))
        elif line.startswith("# "):
            parts.append(_w_p(line[2:].strip(), "Heading1"))
        elif re.match(r"^[-*]\s+", line):
            parts.append(_w_p("• " + re.sub(r"^[-*]\s+", "", line), "ListBullet"))
        elif re.match(r"^\d+[\.、]\s+", line):
            parts.append(_w_p(re.sub(r"^(\d+)[\.、]\s+", r"\1. ", line), "ListNumber"))
        else:
            parts.append(_w_p(line))
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(parts)}<w:sectPr/></w:body></w:document>"
    )
    styles_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="44"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:rPr><w:sz w:val="21"/><w:color w:val="64748B"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:rPr><w:b/><w:sz w:val="24"/></w:rPr></w:style>
</w:styles>"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
    doc_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document_xml)
        zf.writestr("word/styles.xml", styles_xml)
        zf.writestr("word/_rels/document.xml.rels", doc_rels)
    bio.seek(0)
    return bio


def export_insight_report(report, fmt="md"):
    if not report:
        raise ValueError("洞察报告不存在")
    title = report.get("title") or "洞察报告"
    content = (report.get("content") or "").strip()
    if not content:
        raise ValueError("报告内容为空")
    bits = []
    if report.get("train_name"):
        bits.append(f"关联训练：{report.get('train_name')}")
    if report.get("target_col"):
        bits.append(f"目标：{report.get('target_col')}")
    if report.get("create_time"):
        bits.append(f"生成时间：{report.get('create_time')}")
    subtitle = "  ·  ".join(str(x) for x in bits)
    rid = report.get("id") or "insight"
    if fmt == "docx":
        bio = markdown_to_docx_bytes(title, content, subtitle)
        return bio, _insight_filename(report, "docx", rid)
    text = f"# {title}\n\n"
    if subtitle:
        text += f"> {subtitle}\n\n"
    text += content + "\n"
    bio = io.BytesIO(text.encode("utf-8-sig"))
    bio.seek(0)
    return bio, _insight_filename(report, "md", rid)


def _csv_importance(job):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["rank", "feature", "label", "score"])
    for i, item in enumerate(job.get("importance") or [], 1):
        name = item.get("feature") or item.get("name") or ""
        writer.writerow([
            i,
            name,
            feature_tick(name),
            item.get("score") if item.get("score") is not None else item.get("importance"),
        ])
    return buf.getvalue()


def build_export_zip(job_id):
    job = get_job(job_id)
    if not job:
        raise ValueError("训练任务不存在")
    if job.get("status") != "success":
        raise ValueError("仅成功完成的训练任务可导出实验材料")
    config = {
        "id": job.get("id"),
        "name": job.get("name"),
        "model_type": job.get("model_type"),
        "task_type": job.get("task_type"),
        "target_col": job.get("target_col"),
        "feature_cols": job.get("feature_cols"),
        "param_preset": job.get("param_preset"),
        "params": job.get("params"),
        "random_state": job.get("random_state") or 42,
        "test_size": job.get("test_size"),
        "sample_rows": job.get("sample_rows"),
        "log_target": bool(job.get("log_target")),
        "duration_sec": job.get("duration_sec"),
        "create_time": str(job.get("create_time") or ""),
    }
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        def put(name, data):
            payload = data if isinstance(data, (bytes, bytearray)) else str(data).encode("utf-8")
            zf.writestr(_utf8_info(name), payload)

        put("00-methods.md", _methods_markdown(job))
        put("01-config.json", json.dumps(config, ensure_ascii=False, indent=2))
        put("02-metrics.json", json.dumps(job.get("metrics") or {}, ensure_ascii=False, indent=2))
        put("03-feature-importance.csv", _csv_importance(job))
        put("04-limitations.md", training_limitations(job) + "\n")
        insight = (job.get("insight") or "").strip()
        if insight:
            put("05-llm-insight.md", f"# {job.get('insight_title') or job.get('name')}\n\n{insight}\n")
        charts = [
            ("charts/feature-importance.png", _chart_importance),
            ("charts/actual-vs-pred.png", _chart_actual_pred),
            ("charts/train-curve.png", _chart_history),
            ("charts/residual-hist.png", _chart_residual),
        ]
        for name, fn in charts:
            try:
                png = fn(job)
            except Exception:
                png = None
            if png:
                put(name, png)
    bio.seek(0)
    safe = re.sub(r"[\\/:*?\"<>|\s]+", "_", str(job.get("name") or "训练任务")).strip("_")[:40] or "训练任务"
    mt = re.sub(r"[^\w-]+", "_", str(job.get("model_type") or "model"))
    return bio, f"实验材料_{safe}_{mt}_#{job_id}.zip"
