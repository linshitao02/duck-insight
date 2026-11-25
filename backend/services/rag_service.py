# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import os
import pickle
import re
import threading
from datetime import datetime

import faiss
import numpy as np

from config import (
    KNOWLEDGE_DOCS_DIR, RAG_CHUNK_OVERLAP, RAG_CHUNK_SIZE,
    RAG_INDEX_DIR, RAG_SCORE_THRESHOLD, RAG_TOP_K,
)

_LOCK = threading.Lock()
ALLOWED_EXTS = {".pdf", ".md", ".txt", ".docx"}
PROTECTED = {"readme.md"}
CHUNKER_VERSION = "recursive-v2"
INDEX_FILE = "index.faiss"
META_FILE = "meta.pkl"

# LangChain RecursiveCharacterTextSplitter 同款：先大后小的分隔符 + 窗口重叠
_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", ". ", "! ", "? ", "; ", "，", ",", " ", ""]


class HashingEmbedder:
    def __init__(self, dim=384):
        self.dim = dim

    def encode(self, texts, normalize_embeddings=True):
        vecs = np.stack([self._embed_one(t) for t in texts]).astype(np.float32)
        if normalize_embeddings:
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            vecs = vecs / np.maximum(norms, 1e-8)
        return vecs

    def _embed_one(self, text):
        vec = np.zeros(self.dim, dtype=np.float32)
        raw = (text or "").strip().lower()
        if not raw:
            return vec
        for n in (1, 2, 3):
            for i in range(len(raw) - n + 1):
                gram = raw[i:i + n]
                h = hashlib.md5(gram.encode("utf-8")).digest()
                idx = int.from_bytes(h[:4], "little") % self.dim
                vec[idx] += 1.0 if n == 1 else float(n)
        for token in re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9_]+", raw):
            h = hashlib.md5(token.encode("utf-8")).digest()
            idx = int.from_bytes(h[:4], "little") % self.dim
            vec[idx] += 3.0
        return vec


def _read_file(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in {".md", ".txt"}:
        return open(path, encoding="utf-8", errors="ignore").read()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(path)
            return "\n".join([(p.extract_text() or "") for p in reader.pages])
        except Exception:
            return ""
    if ext == ".docx":
        try:
            import docx
            doc = docx.Document(path)
            return "\n".join([p.text for p in doc.paragraphs])
        except Exception:
            return ""
    return ""


def _split_keep(text, sep):
    if sep == "":
        return list(text)
    parts = text.split(sep)
    out = []
    for i, part in enumerate(parts):
        if i < len(parts) - 1:
            out.append(part + sep)
        elif part:
            out.append(part)
    return [p for p in out if p]


def _merge_splits(splits, size, overlap):
    chunks = []
    current = []
    total = 0
    for piece in splits:
        plen = len(piece)
        if current and total + plen > size:
            joined = "".join(current).strip()
            if joined:
                chunks.append(joined)
            while current and (total > overlap or total + plen > size):
                dropped = current.pop(0)
                total -= len(dropped)
            if total + plen > size:
                current = []
                total = 0
        current.append(piece)
        total += plen
    if current:
        joined = "".join(current).strip()
        if joined:
            chunks.append(joined)
    return chunks


def _recursive_split(text, separators, size, overlap):
    if len(text) <= size:
        return [text] if text.strip() else []
    sep = ""
    rest = []
    for i, candidate in enumerate(separators):
        if candidate == "" or candidate in text:
            sep = candidate
            rest = separators[i + 1:]
            break
    pieces = _split_keep(text, sep)
    acc = []
    small = []
    for piece in pieces:
        if len(piece) <= size:
            small.append(piece)
            continue
        if small:
            acc.extend(_merge_splits(small, size, overlap))
            small = []
        acc.extend(_recursive_split(piece, rest or [""], size, overlap))
    if small:
        acc.extend(_merge_splits(small, size, overlap))
    return acc


def _chunk_text(text, size=RAG_CHUNK_SIZE, overlap=RAG_CHUNK_OVERLAP):
    raw = (text or "").replace("\r\n", "\n").strip()
    if not raw:
        return []
    return _recursive_split(raw, list(_SEPARATORS), size, overlap)


class RagService:
    _instance = None

    def __init__(self):
        self.docs_dir = KNOWLEDGE_DOCS_DIR
        self.index_dir = RAG_INDEX_DIR
        self.chunks = []
        self.vectors = None
        self.index = None
        self.embedder = HashingEmbedder()
        self.ready = False
        self.error = None
        os.makedirs(self.docs_dir, exist_ok=True)
        os.makedirs(self.index_dir, exist_ok=True)

    def _files(self):
        if not os.path.isdir(self.docs_dir):
            return []
        files = []
        for name in os.listdir(self.docs_dir):
            if os.path.splitext(name)[1].lower() in ALLOWED_EXTS and name.lower() not in PROTECTED:
                files.append(os.path.join(self.docs_dir, name))
        return sorted(files)

    @classmethod
    def instance(cls):
        if cls._instance is None:
            with _LOCK:
                if cls._instance is None:
                    svc = cls()
                    svc.load_or_build()
                    cls._instance = svc
        return cls._instance

    def _fingerprint(self):
        parts = []
        for path in self._files():
            st = os.stat(path)
            parts.append(f"{os.path.basename(path)}:{int(st.st_mtime)}:{st.st_size}")
        return "|".join(parts) + f"|{CHUNKER_VERSION}|dim={self.embedder.dim}|size={RAG_CHUNK_SIZE}|overlap={RAG_CHUNK_OVERLAP}"

    def status(self):
        return {
            "ready": self.ready,
            "file_count": len(self._files()),
            "chunk_count": len(self.chunks),
            "embedder": "hashing-384",
            "embedder_label": "哈希向量 384 维",
            "index": "faiss",
            "index_label": "FAISS IndexFlatIP",
            "chunker": CHUNKER_VERSION,
            "chunker_label": "Recursive Character Splitter",
            "chunk_size": RAG_CHUNK_SIZE,
            "chunk_overlap": RAG_CHUNK_OVERLAP,
            "supported": ["pdf", "md", "txt", "docx"],
            "error": self.error,
        }

    def list_docs(self, page=1, page_size=10, keyword=None):
        keyword = (keyword or "").strip().lower()
        counts = {}
        for c in self.chunks:
            src = c.get("source")
            counts[src] = counts.get(src, 0) + 1
        items = []
        for path in self._files():
            name = os.path.basename(path)
            if keyword and keyword not in name.lower():
                continue
            st = os.stat(path)
            items.append({
                "name": name,
                "size": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(),
                "chunk_count": counts.get(name, 0),
            })
        total = len(items)
        page = max(int(page or 1), 1)
        page_size = min(max(int(page_size or 10), 1), 100)
        start = (page - 1) * page_size
        return {
            "items": items[start:start + page_size],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def get_doc(self, name):
        name = os.path.basename(name or "")
        path = os.path.join(self.docs_dir, name)
        if not os.path.isfile(path):
            return None
        st = os.stat(path)
        chunks = [c for c in self.chunks if c.get("source") == name]
        chunks = sorted(chunks, key=lambda x: int(x.get("idx") or 0))
        return {
            "name": name,
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(),
            "text": _read_file(path),
            "chunk_count": len(chunks),
            "chunks": chunks,
        }

    def list_chunks(self, source=None, page=1, page_size=20):
        rows = list(self.chunks)
        if source:
            rows = [c for c in rows if c.get("source") == os.path.basename(source)]
        total = len(rows)
        page = max(int(page or 1), 1)
        page_size = min(max(int(page_size or 20), 1), 200)
        start = (page - 1) * page_size
        return {
            "items": rows[start:start + page_size],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def save_doc(self, file_storage):
        name = os.path.basename(file_storage.filename)
        ext = os.path.splitext(name)[1].lower()
        if ext not in ALLOWED_EXTS:
            raise ValueError("仅支持 pdf/md/txt/docx")
        path = os.path.join(self.docs_dir, name)
        file_storage.save(path)
        self.rebuild()
        return {"name": name}

    def delete_doc(self, name):
        path = os.path.join(self.docs_dir, os.path.basename(name))
        if os.path.isfile(path):
            os.remove(path)
        self.rebuild()

    def _index_path(self):
        return os.path.join(self.index_dir, INDEX_FILE)

    def _meta_path(self):
        return os.path.join(self.index_dir, META_FILE)

    def _write_index(self, index):
        blob = faiss.serialize_index(index)
        with open(self._index_path(), "wb") as f:
            np.save(f, blob)

    def _read_index(self):
        with open(self._index_path(), "rb") as f:
            blob = np.load(f)
        return faiss.deserialize_index(blob)

    def _new_index(self):
        return faiss.IndexFlatIP(int(self.embedder.dim))

    def load_or_build(self):
        try:
            if os.path.exists(self._index_path()) and os.path.exists(self._meta_path()):
                with open(self._meta_path(), "rb") as f:
                    payload = pickle.load(f)
                if payload.get("fingerprint") == self._fingerprint() and payload.get("chunks"):
                    self.chunks = payload.get("chunks") or []
                    self.index = self._read_index()
                    self.ready = True
                    return
        except Exception as e:
            self.error = str(e)
        self.rebuild()

    def rebuild(self):
        chunks = []
        for path in self._files():
            text = _read_file(path)
            for i, part in enumerate(_chunk_text(text)):
                chunks.append({
                    "source": os.path.basename(path),
                    "idx": i,
                    "text": part,
                    "char_len": len(part),
                })
        self.chunks = chunks
        self.index = self._new_index()
        if chunks:
            vectors = self.embedder.encode([c["text"] for c in chunks])
            self.vectors = np.ascontiguousarray(vectors, dtype=np.float32)
            self.index.add(self.vectors)
        else:
            self.vectors = np.zeros((0, self.embedder.dim), dtype=np.float32)
        self._write_index(self.index)
        with open(self._meta_path(), "wb") as f:
            pickle.dump({
                "chunks": self.chunks,
                "fingerprint": self._fingerprint(),
                "chunker": CHUNKER_VERSION,
            }, f)
        self.ready = True
        self.error = None

    def search(self, query_text, top_k=None):
        if self.index is None or self.index.ntotal == 0 or not self.chunks:
            return []
        q = np.ascontiguousarray(self.embedder.encode([query_text or ""]), dtype=np.float32)
        k = min(top_k or RAG_TOP_K, int(self.index.ntotal))
        scores, idxs = self.index.search(q, k)
        out = []
        for score, i in zip(scores[0].tolist(), idxs[0].tolist()):
            if i < 0:
                continue
            if float(score) < RAG_SCORE_THRESHOLD:
                continue
            item = dict(self.chunks[int(i)])
            item["score"] = round(float(score), 4)
            out.append(item)
        return out


def get_rag_service():
    return RagService.instance()
