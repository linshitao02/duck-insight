# -*- coding: utf-8 -*-
from flask import Blueprint, g, request
from werkzeug.security import generate_password_hash

from utils.auth import admin_required, hash_password, login_required, new_token, verify_password
from utils.db import delete, insert, query, update
from utils.jsonx import row_to_dict
from utils.paging import paginate_args
from utils.response import fail, ok

auth_bp = Blueprint("auth", __name__, url_prefix="/api")


def _public_user(row):
    if not row:
        return None
    data = row_to_dict(row)
    data.pop("password", None)
    return data


@auth_bp.route("/user/login", methods=["POST"])
def login():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    user = query("SELECT * FROM sys_user WHERE username=%s AND status=1", (username,), one=True)
    if not user or not verify_password(password, user["password"]):
        return fail("用户名或密码错误")
    token = new_token()
    update("sys_user", {"token": token}, "id=%s", (user["id"],))
    user["token"] = token
    return ok({"token": token, "user": _public_user(user)})


@auth_bp.route("/user/register", methods=["POST"])
def register():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        return fail("请填写用户名和密码")
    if query("SELECT id FROM sys_user WHERE username=%s", (username,), one=True):
        return fail("用户名已存在")
    uid = insert("sys_user", {
        "username": username,
        "password": hash_password(password),
        "nickname": body.get("nickname") or username,
        "email": body.get("email"),
        "phone": body.get("phone"),
        "role": "user",
        "status": 1,
    })
    return ok({"id": uid}, "注册成功")


@auth_bp.route("/user/list", methods=["GET"])
@admin_required
def user_list():
    rows = query("SELECT id, username, nickname, email, phone, role, status, create_time FROM sys_user ORDER BY id DESC")
    return ok(paginate_args([row_to_dict(r) for r in rows], request.args))


@auth_bp.route("/user/<int:uid>", methods=["PUT"])
@login_required
def user_update(uid):
    body = request.get_json(silent=True) or {}
    if g.user.get("role") != "admin" and g.user.get("id") != uid:
        return fail("无权修改", 403)
    data = {k: body[k] for k in ("nickname", "email", "phone", "status") if k in body}
    if body.get("password"):
        data["password"] = generate_password_hash(body["password"])
    if g.user.get("role") == "admin" and body.get("role"):
        data["role"] = body["role"]
    update("sys_user", data, "id=%s", (uid,))
    return ok(message="已更新")


@auth_bp.route("/user/<int:uid>", methods=["DELETE"])
@admin_required
def user_delete(uid):
    if uid == g.user.get("id"):
        return fail("不能删除当前登录用户")
    delete("sys_user", "id=%s", (uid,))
    return ok(message="已删除")


@auth_bp.route("/scenario/list", methods=["GET"])
@login_required
def scenario_list():
    from services.scenario_service import list_scenarios
    return ok(list_scenarios())


@auth_bp.route("/scenario", methods=["POST"])
@login_required
def scenario_create():
    try:
        body = request.get_json(silent=True) or {}
        name = (body.get("name") or body.get("code") or "").strip()
        code = (body.get("code") or "").strip() or None
        if not name:
            return fail("请填写场景名称")
        from services.scenario_service import ensure_scenario
        return ok(ensure_scenario(name, code), "场景已保存")
    except Exception as e:
        return fail(str(e))
