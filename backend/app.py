# -*- coding: utf-8 -*-
"""InsightForge 数据分析平台 - Flask 入口"""
import json
from datetime import datetime
from decimal import Decimal

from flask import Flask, jsonify
from flask_cors import CORS

from config import FLASK_HOST, FLASK_PORT, MAX_CONTENT_LENGTH
from utils.db_bootstrap import ensure_database


class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def create_app():
    app = Flask(__name__)
    app.json_encoder = CustomJSONEncoder
    app.config["JSON_AS_ASCII"] = False
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    from api.auth_api import auth_bp
    from api.chat_api import chat_bp
    from api.clean_api import clean_bp
    from api.dashboard_api import dash_bp
    from api.dataset_api import dataset_bp
    from api.graph_api import graph_bp
    from api.source_api import source_bp
    from api.llm_api import llm_bp
    from api.model_api import model_bp
    from api.power_api import power_bp
    from api.predict_api import predict_bp
    from api.project_api import project_bp
    from api.bi_api import bi_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(project_bp)
    app.register_blueprint(dataset_bp)
    app.register_blueprint(source_bp)
    app.register_blueprint(clean_bp)
    app.register_blueprint(model_bp)
    app.register_blueprint(predict_bp)
    app.register_blueprint(llm_bp)
    app.register_blueprint(dash_bp)
    app.register_blueprint(graph_bp)
    app.register_blueprint(power_bp)
    app.register_blueprint(bi_bp)
    app.register_blueprint(chat_bp)
    try:
        from services.dash_app import attach_dash
        attach_dash(app)
    except Exception as e:
        print(f"[BI] Dash 挂载失败: {e}")

    def start_scheduler():
        import threading
        import time

        def _run_one(gid):
            try:
                with app.app_context():
                    from services.graph_service import run_graph
                    run_graph(gid, trigger="schedule")
            except Exception as e:
                print(f"[调度] 流程 #{gid} 失败: {e}")

        def loop():
            time.sleep(20)
            while True:
                try:
                    with app.app_context():
                        from services.scheduler import claim_due_schedules
                        due = claim_due_schedules()
                    for item in due:
                        threading.Thread(
                            target=_run_one, args=(item["id"],), daemon=True,
                            name=f"if-sched-{item['id']}",
                        ).start()
                        print(f"[调度] 已排队 {item.get('name')} #{item['id']}")
                except Exception as e:
                    print(f"[调度] {e}")
                time.sleep(60)

        threading.Thread(target=loop, daemon=True, name="if-scheduler").start()

    start_scheduler()

    @app.route("/health")
    def health():
        return jsonify({"code": 200, "message": "服务运行正常"})

    @app.errorhandler(404)
    def handle_404(e):
        from flask import request
        if str(request.path or "").startswith("/bi-dash"):
            return e
        return jsonify({"code": 404, "message": "接口不存在"}), 404

    @app.errorhandler(Exception)
    def handle_error(e):
        from flask import request
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return e
        if str(request.path or "").startswith("/bi-dash"):
            raise e
        print("[ERROR]", e)
        return jsonify({"code": 500, "message": str(e)}), 500

    return app


if __name__ == "__main__":
    print("=" * 64)
    from config import DB_ENGINE, SQLITE_PATH
    print("Duck Insight 数据分析平台")
    print(f"数据库: {DB_ENGINE}" + (f"  {SQLITE_PATH}" if DB_ENGINE == "sqlite" else ""))
    print("=" * 64)
    try:
        ensure_database()
    except Exception as e:
        print(f"[数据库] 初始化失败: {e}")
    try:
        from services.rag_service import get_rag_service
        status = get_rag_service().status()
        print(f"[RAG] ready={status.get('ready')} chunks={status.get('chunk_count')}")
    except Exception as e:
        print(f"[RAG] {e}")
    print("服务地址: http://127.0.0.1:5000")
    print("默认账号: admin / admin123")
    print("=" * 64)
    app = create_app()
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=True, use_reloader=False, threaded=True)
