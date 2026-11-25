#!/bin/sh
set -e
cd /app/backend
python - <<'PY'
from utils.db_bootstrap import ensure_database
ensure_database()
try:
    from services.rag_service import get_rag_service
    status = get_rag_service().status()
    print(f"[RAG] ready={status.get('ready')} chunks={status.get('chunk_count')}")
except Exception as exc:
    print(f"[RAG] {exc}")
PY
exec gunicorn \
    --workers 1 \
    --threads 8 \
    --timeout 600 \
    --bind 0.0.0.0:5000 \
    --access-logfile - \
    --error-logfile - \
    "app:create_app()"
