# -*- coding: utf-8 -*-
from flask import Response

from utils.jsonx import dumps


def ok(data=None, message="成功"):
    return Response(
        dumps({"code": 200, "message": message, "data": data}),
        mimetype="application/json",
    )


def fail(message="失败", code=400, http_status=None):
    body = Response(
        dumps({"code": code, "message": message, "data": None}),
        mimetype="application/json",
    )
    return body, (http_status or (401 if code == 401 else 200))
