# -*- coding: utf-8 -*-
"""为指定数据集配置补全字段中文释义。"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import create_app
from flask import g
from services.dataset_service import fill_zh_labels_for_project
from utils.db import query

PROJECT_NAME = "极端天气负荷与风光出力"


def main():
    app = create_app()
    with app.app_context():
        g.user = query("SELECT * FROM sys_user WHERE username=%s", ("admin",), one=True) or {
            "id": 1, "username": "admin", "role": "admin",
        }
        row = query(
            "SELECT * FROM data_project WHERE name=%s AND status=1",
            (PROJECT_NAME,),
            one=True,
        )
        if not row:
            raise SystemExit(f"未找到数据集配置：{PROJECT_NAME}")
        datasets = fill_zh_labels_for_project(row["id"], overwrite=True)
        print(f"project_id={row['id']} tables={len(datasets)}")
        for ds in datasets:
            cols = (ds.get("profile") or {}).get("columns") or []
            labeled = [c for c in cols if c.get("label_zh")]
            print(f"  [{ds['id']}] {ds['name']}: {len(labeled)}/{len(cols)} 已有中文")
            for c in cols:
                print(f"    {c.get('name')} = {c.get('label_zh')}")


if __name__ == "__main__":
    main()
