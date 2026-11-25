# -*- coding: utf-8 -*-
import hashlib
import re

from utils.db import insert, query, update
from utils.jsonx import row_to_dict


def list_scenarios():
    rows = query("SELECT * FROM sys_scenario WHERE status=1 ORDER BY is_default DESC, id")
    return [row_to_dict(r) for r in rows]


def _code_from_name(name):
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name or "").strip("_").lower()
    if slug and re.match(r"^[a-z][a-z0-9_]{0,62}$", slug):
        return slug[:64]
    digest = hashlib.md5((name or "").encode("utf-8")).hexdigest()[:12]
    return f"s_{digest}"


def ensure_scenario(name_or_code, code=None):
    name = (name_or_code or "").strip()
    code = (code or "").strip() or None
    if not name:
        raise ValueError("场景名称不能为空")

    if code:
        row = query("SELECT * FROM sys_scenario WHERE code=%s", (code,), one=True)
        if row:
            if not row.get("status"):
                update("sys_scenario", {"status": 1}, "id=%s", (row["id"],))
                row = query("SELECT * FROM sys_scenario WHERE id=%s", (row["id"],), one=True)
            return row_to_dict(row)

    row = query("SELECT * FROM sys_scenario WHERE code=%s", (name,), one=True)
    if row:
        if not row.get("status"):
            update("sys_scenario", {"status": 1}, "id=%s", (row["id"],))
            row = query("SELECT * FROM sys_scenario WHERE id=%s", (row["id"],), one=True)
        return row_to_dict(row)

    row = query("SELECT * FROM sys_scenario WHERE name=%s AND status=1", (name,), one=True)
    if row:
        return row_to_dict(row)

    new_code = code or _code_from_name(name)
    existed = query("SELECT * FROM sys_scenario WHERE code=%s", (new_code,), one=True)
    if existed and existed.get("name") != name:
        suffix = hashlib.md5(name.encode("utf-8")).hexdigest()[:6]
        new_code = f"{new_code[:57]}_{suffix}"
        existed = query("SELECT * FROM sys_scenario WHERE code=%s", (new_code,), one=True)
    if existed:
        patch = {"status": 1}
        if not existed.get("name"):
            patch["name"] = name[:128]
        update("sys_scenario", patch, "id=%s", (existed["id"],))
        return row_to_dict(query("SELECT * FROM sys_scenario WHERE id=%s", (existed["id"],), one=True))

    sid = insert("sys_scenario", {
        "code": new_code[:64],
        "name": name[:128],
        "description": "",
        "icon": "DataAnalysis",
        "is_default": 0,
        "status": 1,
    })
    return row_to_dict(query("SELECT * FROM sys_scenario WHERE id=%s", (sid,), one=True))
