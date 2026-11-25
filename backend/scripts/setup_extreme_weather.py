# -*- coding: utf-8 -*-
"""导入极端天气数据集、清洗规则，并训练负荷 / 风光两个模型。"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import create_app
from flask import g
from services.extreme_weather_pipeline import sync
from utils.db import query


def main():
    app = create_app()
    with app.app_context():
        g.user = query("SELECT * FROM sys_user WHERE username=%s", ("admin",), one=True) or {"id": 1, "username": "admin", "role": "admin"}
        result = sync(force_rebuild=False, train=True, wait=True)
        import json
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
