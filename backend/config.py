# -*- coding: utf-8 -*-
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
STORAGE_DIR = os.path.join(ROOT_DIR, "storage")
KNOWLEDGE_DOCS_DIR = os.path.join(BASE_DIR, "knowledge_docs")
RAG_INDEX_DIR = os.path.join(KNOWLEDGE_DOCS_DIR, ".faiss_index")
SQLITE_PATH = os.path.join(STORAGE_DIR, "duck_insight.sqlite")
DB_LOCAL_FILE = os.path.join(BASE_DIR, "db.local.json")

for path in (STORAGE_DIR, KNOWLEDGE_DOCS_DIR, RAG_INDEX_DIR):
    os.makedirs(path, exist_ok=True)


def _load_local_db():
    if not os.path.isfile(DB_LOCAL_FILE):
        return {}
    try:
        with open(DB_LOCAL_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def resolve_database():
    """没有环境变量或 backend/db.local.json 时使用 SQLite。

    显式 DB_ENGINE=mysql，或提供了 MYSQL_HOST / db.local.json 的 host，才连接 MySQL。
    """
    local = _load_local_db()
    engine = (os.environ.get("DB_ENGINE") or local.get("engine") or "").strip().lower()
    mysql_host = (os.environ.get("MYSQL_HOST") or local.get("host") or "").strip()
    if engine != "mysql" and not mysql_host:
        return {"engine": "sqlite", "path": SQLITE_PATH}
    return {
        "engine": "mysql",
        "host": mysql_host or "127.0.0.1",
        "database": (os.environ.get("MYSQL_DATABASE") or local.get("database") or "insight_forge").strip(),
        "user": (os.environ.get("MYSQL_USER") or local.get("user") or "root").strip(),
        "password": os.environ.get("MYSQL_PASSWORD") if os.environ.get("MYSQL_PASSWORD") is not None else (local.get("password") if "password" in local else "root"),
        "port": int(os.environ.get("MYSQL_PORT") or local.get("port") or 3306),
        "charset": "utf8mb4",
    }


DB_CONFIG = resolve_database()
DB_ENGINE = DB_CONFIG.get("engine") or "sqlite"

FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5000
MAX_CONTENT_LENGTH = 400 * 1024 * 1024

ALLOWED_DATA_EXTENSIONS = {"csv", "txt", "xls", "xlsx"}
ALLOWED_DOC_EXTENSIONS = {"pdf", "md", "txt", "docx"}

RAG_TOP_K = 4
RAG_SCORE_THRESHOLD = 0.18
RAG_CHUNK_SIZE = 480
RAG_CHUNK_OVERLAP = 80

# 安全提示：不再内置任何 LLM API Key。
# 模型、Base URL 与密钥均由用户在「LLM 配置」页面自行添加。
# 下面的模型/地址仅作为字段缺失时的兜底，不含任何敏感凭据。
DEFAULT_LLM_MODEL = "qwen-plus"
DEFAULT_LLM_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_SYSTEM_PROMPT = (
    "你是数据分析助手。请结合当前数据给出可落地的中文分析，"
    "避免编造未提供的数字，结论必须对应已给指标、特征或预测结果。"
    "涉及业务决策时必须注明需人工确认。"
)

DEMO_ROSSMANN_DIR = os.path.normpath(
    os.path.join(os.path.dirname(ROOT_DIR), "..", "..", "project", "data-analysis", "rossmann_store", "data")
)
# 兼容本机常见路径
DEMO_ROSSMANN_CANDIDATES = [
    r"C:\Users\shita\AI\project\data-analysis\rossmann_store\data",
    os.path.join(os.path.dirname(ROOT_DIR), "project", "data-analysis", "rossmann_store", "data"),
    DEMO_ROSSMANN_DIR,
]


def get_user_dir(username, subdir=""):
    path = os.path.join(STORAGE_DIR, username or "anonymous", subdir)
    os.makedirs(path, exist_ok=True)
    return path


def to_rel(path: str):
    if not path:
        return path
    if os.path.isabs(path):
        try:
            return os.path.relpath(path, STORAGE_DIR).replace("\\", "/")
        except Exception:
            return str(path).replace("\\", "/")
    return str(path).replace("\\", "/")


def to_abs(path: str):
    if not path:
        return path
    if os.path.isabs(path):
        return os.path.normpath(path)
    parts = [p for p in str(path).replace("\\", "/").split("/") if p]
    return os.path.normpath(os.path.join(STORAGE_DIR, *parts))
