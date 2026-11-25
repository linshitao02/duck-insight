# -*- coding: utf-8 -*-
import functools
import secrets

from flask import g, request
from werkzeug.security import check_password_hash, generate_password_hash

from utils.db import query
from utils.response import fail


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return check_password_hash(hashed, password)


def new_token() -> str:
    return secrets.token_hex(32)


def get_token():
    header = request.headers.get("Authorization") or ""
    if header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip()
    return request.args.get("token") or ""


def current_user():
    token = get_token()
    if not token:
        return None
    return query("SELECT * FROM sys_user WHERE token=%s AND status=1", (token,), one=True)


def login_required(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return fail("未登录或登录已过期", code=401)
        g.user = user
        return fn(*args, **kwargs)

    return wrapper


def admin_required(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return fail("未登录或登录已过期", code=401)
        if user.get("role") != "admin":
            return fail("无管理员权限", code=403)
        g.user = user
        return fn(*args, **kwargs)

    return wrapper
