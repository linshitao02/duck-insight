# -*- coding: utf-8 -*-
from flask import Blueprint, request

from services import power_engine, power_service
from utils.auth import login_required
from utils.response import fail, ok

power_bp = Blueprint("power", __name__, url_prefix="/api/power")


@power_bp.route("/ingest", methods=["POST"])
@login_required
def ingest():
    try:
        return ok(power_engine.ingest_and_materialize(), "气象与电力序列已更新")
    except Exception as e:
        return fail(str(e))


@power_bp.route("/cockpit", methods=["GET"])
@login_required
def cockpit():
    try:
        data = power_engine.cockpit_payload()
        if not data.get("series"):
            return ok({**data, "empty": True}, "暂无数据，请先同步气象")
        return ok(data)
    except Exception as e:
        return fail(str(e))


@power_bp.route("/alerts", methods=["GET"])
@login_required
def alerts():
    return ok(power_engine.list_alerts())


@power_bp.route("/shock", methods=["POST"])
@login_required
def shock():
    body = request.get_json(silent=True) or {}
    return ok(power_engine.shock_scenario(body.get("kind") or "heatwave"))


@power_bp.route("/report", methods=["POST"])
@login_required
def report():
    try:
        return ok(power_service.generate_decision_report(), "报告已生成")
    except Exception as e:
        return fail(str(e))


@power_bp.route("/report/latest", methods=["GET"])
@login_required
def report_latest():
    from utils.jsonx import row_to_dict
    row = power_engine.latest_report()
    return ok(row_to_dict(row) if row else None)
