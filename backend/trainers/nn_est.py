# -*- coding: utf-8 -*-
"""Softmax / BERT：有 CUDA 就用显卡，否则 CPU。"""
from __future__ import annotations

import re

import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin, RegressorMixin

_TORCH = None
_TORCH_ERR = None


def torch_available():
    global _TORCH, _TORCH_ERR
    if _TORCH is False:
        return False
    if _TORCH is not None:
        return True
    try:
        import torch  # noqa: F401
        _TORCH = True
        return True
    except Exception as exc:
        _TORCH = False
        _TORCH_ERR = exc
        return False


def resolve_torch_device(pref="auto"):
    import torch
    raw = str(pref or "auto").strip().lower()
    if raw in ("cpu", "host"):
        return torch.device("cpu")
    if raw not in ("auto", "cuda", "gpu", "cuda:0", ""):
        return torch.device("cpu")
    if not torch.cuda.is_available():
        return torch.device("cpu")
    try:
        torch.zeros(1, device="cuda")
        return torch.device("cuda")
    except Exception:
        return torch.device("cpu")


def _softmax_module(torch, n_in, n_out):
    class Net(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.fc = torch.nn.Linear(n_in, n_out)

        def forward(self, x):
            return self.fc(x)

    return Net()


class SoftmaxEstimator(BaseEstimator, ClassifierMixin):
    """多分类 Softmax：Linear + CrossEntropy。有 GPU 用 GPU。"""

    def __init__(
        self,
        epochs=80,
        learning_rate=0.05,
        batch_size=256,
        C=1.0,
        random_state=42,
        device="auto",
    ):
        self.epochs = int(epochs)
        self.learning_rate = float(learning_rate)
        self.batch_size = int(batch_size)
        self.C = float(C)
        self.random_state = int(random_state)
        self.device = device

    def fit(self, X, y, X_valid=None, y_valid=None, bump=None):
        if not torch_available():
            raise RuntimeError("Softmax GPU 实现需要 PyTorch")
        import torch

        X = np.asarray(X, dtype=np.float32)
        y = np.asarray(y)
        enc, y_idx = np.unique(y, return_inverse=True)
        self.classes_ = enc
        n_out = int(len(enc))
        if n_out < 2:
            raise ValueError("Softmax 至少需要 2 个类别")
        device = resolve_torch_device(self.device)
        self.used_device_ = str(device)
        torch.manual_seed(self.random_state)
        net = _softmax_module(torch, X.shape[1], n_out).to(device)
        wd = 0.0 if self.C <= 0 else 1.0 / max(self.C, 1e-6)
        opt = torch.optim.Adam(net.parameters(), lr=self.learning_rate, weight_decay=wd)
        crit = torch.nn.CrossEntropyLoss()
        xt = torch.tensor(X, dtype=torch.float32, device=device)
        yt = torch.tensor(y_idx, dtype=torch.long, device=device)
        n = len(X)
        bs = max(8, min(int(self.batch_size or 256), n))
        train_hist, valid_hist = [], []
        net.train()
        for epoch in range(max(1, self.epochs)):
            perm = torch.randperm(n, device=device)
            total = 0.0
            for start in range(0, n, bs):
                idx = perm[start:start + bs]
                opt.zero_grad(set_to_none=True)
                logits = net(xt[idx])
                loss = crit(logits, yt[idx])
                loss.backward()
                opt.step()
                total += float(loss.item()) * len(idx)
            train_hist.append(total / max(n, 1))
            if X_valid is not None and y_valid is not None and len(X_valid):
                valid_hist.append(self._loss_on(net, crit, X_valid, y_valid, device, torch))
            if bump:
                bump((epoch + 1) / max(self.epochs, 1))
        self.net_ = net.cpu()
        self.n_features_in_ = int(X.shape[1])
        w = self.net_.fc.weight.detach().cpu().numpy()
        self.coef_ = w
        self.intercept_ = self.net_.fc.bias.detach().cpu().numpy()
        self.history_ = {
            "metric": "loss",
            "train": train_hist,
            "valid": valid_hist,
            "x": list(range(1, len(train_hist) + 1)),
            "x_name": "epoch",
        }
        return self

    def _loss_on(self, net, crit, X, y, device, torch):
        mapping = {c: i for i, c in enumerate(self.classes_)}
        idx = np.array([mapping.get(v, 0) for v in np.asarray(y).ravel()], dtype=np.int64)
        xt = torch.tensor(np.asarray(X, dtype=np.float32), device=device)
        yt = torch.tensor(idx, dtype=torch.long, device=device)
        net.eval()
        with torch.no_grad():
            loss = crit(net(xt), yt)
        net.train()
        return float(loss.item())

    def _logits(self, X):
        import torch
        X = np.asarray(X, dtype=np.float32)
        device = resolve_torch_device(getattr(self, "used_device_", "cpu"))
        net = self.net_.to(device)
        net.eval()
        with torch.no_grad():
            out = net(torch.tensor(X, dtype=torch.float32, device=device)).detach().cpu().numpy()
        self.net_ = net.cpu()
        return out

    def predict_proba(self, X):
        z = self._logits(X)
        z = z - z.max(axis=1, keepdims=True)
        e = np.exp(z)
        return e / np.clip(e.sum(axis=1, keepdims=True), 1e-12, None)

    def predict(self, X):
        return self.classes_[np.argmax(self.predict_proba(X), axis=1)]

    def __getstate__(self):
        state = dict(self.__dict__)
        net = state.pop("net_", None)
        if net is not None:
            state["_state_dict"] = {k: v.detach().cpu() for k, v in net.state_dict().items()}
            state["_n_in"] = int(net.fc.in_features)
            state["_n_out"] = int(net.fc.out_features)
        return state

    def __setstate__(self, state):
        sd = state.pop("_state_dict", None)
        n_in = state.pop("_n_in", None)
        n_out = state.pop("_n_out", None)
        self.__dict__.update(state)
        if sd is not None and torch_available():
            import torch
            net = _softmax_module(torch, int(n_in), int(n_out))
            net.load_state_dict(sd)
            self.net_ = net


_TOKEN_RE = re.compile(r"[A-Za-z_]+|\d+\.?\d*|[^\s]")
_PAD, _UNK, _CLS, _SEP = 0, 1, 2, 3


def _row_text(row, names):
    parts = []
    for name, val in zip(names, row):
        if isinstance(val, (float, np.floating)):
            if not np.isfinite(val):
                val = 0.0
            text = f"{float(val):.4g}"
        else:
            text = str(val)
        parts.append(f"{name}={text}")
    return " ; ".join(parts)


def _nhead(d_model):
    for h in (8, 4, 2, 1):
        if int(d_model) % h == 0:
            return h
    return 1


def _bert_module(torch, vocab, d_model, n_layers, nhead, max_len, n_out):
    class BertTiny(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.tok = torch.nn.Embedding(vocab, d_model, padding_idx=_PAD)
            self.pos = torch.nn.Embedding(max_len, d_model)
            layer = torch.nn.TransformerEncoderLayer(
                d_model=d_model, nhead=nhead, dim_feedforward=d_model * 4,
                dropout=0.1, activation="gelu", batch_first=True, norm_first=True,
            )
            self.enc = torch.nn.TransformerEncoder(layer, num_layers=n_layers, enable_nested_tensor=False)
            self.norm = torch.nn.LayerNorm(d_model)
            self.head = torch.nn.Linear(d_model, n_out)

        def forward(self, ids):
            b, t = ids.shape
            pos = torch.arange(t, device=ids.device).unsqueeze(0).expand(b, t)
            x = self.tok(ids) + self.pos(pos)
            x = self.enc(x, src_key_padding_mask=ids.eq(_PAD))
            return self.head(self.norm(x[:, 0]))

    return BertTiny()


class BertTabularEstimator(BaseEstimator):
    """把表格行拼成文本，用 BERT-Tiny（Transformer + CLS）训练。有 GPU 用 GPU。"""

    def __init__(
        self,
        epochs=4,
        learning_rate=0.0003,
        batch_size=32,
        max_length=64,
        n_layers=2,
        d_model=128,
        pretrained="scratch",
        task="regression",
        random_state=42,
        device="auto",
    ):
        self.epochs = int(epochs)
        self.learning_rate = float(learning_rate)
        self.batch_size = int(batch_size)
        self.max_length = int(max_length)
        self.n_layers = int(n_layers)
        self.d_model = int(d_model)
        self.pretrained = str(pretrained or "scratch")
        self.task = str(task or "regression")
        self.random_state = int(random_state)
        self.device = device

    def _names(self, n):
        return [f"x{i}" for i in range(n)]

    def _build_vocab(self, texts, max_size=4096):
        freq = {}
        for text in texts:
            for tok in _TOKEN_RE.findall(text):
                freq[tok] = freq.get(tok, 0) + 1
        items = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[: max(8, max_size - 4)]
        stoi = {"[PAD]": _PAD, "[UNK]": _UNK, "[CLS]": _CLS, "[SEP]": _SEP}
        for tok, _ in items:
            if tok not in stoi:
                stoi[tok] = len(stoi)
        return stoi

    def _encode(self, texts, stoi, max_len):
        rows = np.zeros((len(texts), max_len), dtype=np.int64)
        for i, text in enumerate(texts):
            ids = [_CLS]
            for tok in _TOKEN_RE.findall(text):
                ids.append(stoi.get(tok, _UNK))
                if len(ids) >= max_len - 1:
                    break
            ids.append(_SEP)
            ids = ids[:max_len]
            rows[i, :len(ids)] = ids
        return rows

    def _texts(self, X):
        X = np.asarray(X)
        names = getattr(self, "feature_names_in_", None) or self._names(X.shape[1] if X.ndim == 2 else 1)
        if X.ndim == 1:
            X = X.reshape(-1, 1)
        return [_row_text(row, names) for row in X]

    def fit(self, X, y, X_valid=None, y_valid=None, bump=None):
        if not torch_available():
            raise RuntimeError("BERT 需要 PyTorch，请在 conda 环境 data-analysis 中安装 torch")
        import torch

        X = np.asarray(X)
        y = np.asarray(y)
        self.n_features_in_ = int(X.shape[1]) if X.ndim == 2 else 1
        self.feature_names_in_ = self._names(self.n_features_in_)
        texts = self._texts(X)
        is_clf = self.task == "classification"
        if is_clf:
            self.classes_, y_arr = np.unique(y, return_inverse=True)
            n_out = int(len(self.classes_))
            y_arr = y_arr.astype(np.int64)
            if n_out < 2:
                raise ValueError("BERT 分类至少需要 2 个类别")
        else:
            y_arr = np.asarray(y, dtype=np.float32).ravel()
            n_out = 1
            self.classes_ = None

        if self.pretrained and self.pretrained not in ("scratch", "none", "from_scratch"):
            try:
                return self._fit_hf(texts, y_arr, n_out, is_clf, X_valid, y_valid, bump)
            except Exception as exc:
                # 预训练权重拿不到时退回 BERT-Tiny，保证任务能跑完
                self._hf_fallback_ = str(exc)

        self.stoi_ = self._build_vocab(texts)
        max_len = max(8, min(int(self.max_length or 64), 128))
        ids = self._encode(texts, self.stoi_, max_len)
        device = resolve_torch_device(self.device)
        self.used_device_ = str(device)
        torch.manual_seed(self.random_state)
        d_model = int(self.d_model or 128)
        nhead = _nhead(d_model)
        net = _bert_module(
            torch, len(self.stoi_), d_model, max(1, int(self.n_layers or 2)),
            nhead, max_len, n_out,
        ).to(device)
        opt = torch.optim.AdamW(net.parameters(), lr=self.learning_rate, weight_decay=0.01)
        crit = torch.nn.CrossEntropyLoss() if is_clf else torch.nn.MSELoss()
        xt = torch.tensor(ids, dtype=torch.long, device=device)
        yt = torch.tensor(y_arr, dtype=torch.long if is_clf else torch.float32, device=device)
        if not is_clf:
            yt = yt.view(-1, 1)
        n = len(ids)
        bs = max(4, min(int(self.batch_size or 32), n))
        train_hist, valid_hist = [], []
        net.train()
        for epoch in range(max(1, self.epochs)):
            perm = torch.randperm(n, device=device)
            total = 0.0
            for start in range(0, n, bs):
                idx = perm[start:start + bs]
                opt.zero_grad(set_to_none=True)
                out = net(xt[idx])
                loss = crit(out, yt[idx])
                loss.backward()
                torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
                opt.step()
                total += float(loss.item()) * len(idx)
            train_hist.append(total / max(n, 1))
            if X_valid is not None and y_valid is not None and len(X_valid):
                valid_hist.append(self._eval_loss(net, crit, X_valid, y_valid, is_clf, device, torch, max_len))
            if bump:
                bump((epoch + 1) / max(self.epochs, 1))
        self.net_ = net.cpu()
        self.max_len_ = max_len
        self.n_out_ = n_out
        self.is_clf_ = is_clf
        self.backend_ = "scratch"
        self.history_ = {
            "metric": "loss",
            "train": train_hist,
            "valid": valid_hist,
            "x": list(range(1, len(train_hist) + 1)),
            "x_name": "epoch",
        }
        return self

    def _eval_loss(self, net, crit, X, y, is_clf, device, torch, max_len):
        texts = self._texts(X)
        ids = self._encode(texts, self.stoi_, max_len)
        if is_clf:
            mapping = {c: i for i, c in enumerate(self.classes_)}
            y_arr = np.array([mapping.get(v, 0) for v in np.asarray(y).ravel()], dtype=np.int64)
        else:
            y_arr = np.asarray(y, dtype=np.float32).ravel()
        xt = torch.tensor(ids, dtype=torch.long, device=device)
        yt = torch.tensor(y_arr, dtype=torch.long if is_clf else torch.float32, device=device)
        if not is_clf:
            yt = yt.view(-1, 1)
        net.eval()
        total = 0.0
        bs = 64
        with torch.no_grad():
            for start in range(0, len(ids), bs):
                out = net(xt[start:start + bs])
                loss = crit(out, yt[start:start + bs])
                total += float(loss.item()) * (min(start + bs, len(ids)) - start)
        net.train()
        return total / max(len(ids), 1)

    def _fit_hf(self, texts, y_arr, n_out, is_clf, X_valid, y_valid, bump):
        import torch
        from transformers import AutoModel, AutoTokenizer

        name = "distilbert-base-uncased"
        tokenizer = AutoTokenizer.from_pretrained(name)
        enc = AutoModel.from_pretrained(name)
        device = resolve_torch_device(self.device)
        self.used_device_ = str(device)
        max_len = max(8, min(int(self.max_length or 64), 128))
        head = torch.nn.Linear(enc.config.hidden_size, n_out)
        enc.to(device)
        head.to(device)
        params = list(head.parameters())
        freeze = self.pretrained in ("distilbert", "distilbert-frozen", "hf-frozen")
        if freeze:
            for p in enc.parameters():
                p.requires_grad = False
        else:
            params += [p for p in enc.parameters() if p.requires_grad]
        opt = torch.optim.AdamW(params, lr=self.learning_rate)
        crit = torch.nn.CrossEntropyLoss() if is_clf else torch.nn.MSELoss()
        y_t = torch.tensor(y_arr, dtype=torch.long if is_clf else torch.float32)
        if not is_clf:
            y_t = y_t.view(-1, 1)
        n = len(texts)
        bs = max(4, min(int(self.batch_size or 16), n))
        train_hist = []
        enc.train()
        head.train()
        rng = np.random.RandomState(self.random_state)
        for epoch in range(max(1, self.epochs)):
            order = rng.permutation(n)
            total = 0.0
            for start in range(0, n, bs):
                idx = order[start:start + bs]
                batch = [texts[i] for i in idx]
                tok = tokenizer(batch, padding=True, truncation=True, max_length=max_len, return_tensors="pt")
                tok = {k: v.to(device) for k, v in tok.items()}
                yb = y_t[idx].to(device)
                opt.zero_grad(set_to_none=True)
                hidden = enc(**tok).last_hidden_state[:, 0]
                out = head(hidden)
                loss = crit(out, yb)
                loss.backward()
                opt.step()
                total += float(loss.item()) * len(idx)
            train_hist.append(total / max(n, 1))
            if bump:
                bump((epoch + 1) / max(self.epochs, 1))
        self.tokenizer_name_ = name
        self.hf_state_ = {
            "encoder": {k: v.detach().cpu() for k, v in enc.state_dict().items()},
            "head": {k: v.detach().cpu() for k, v in head.state_dict().items()},
            "hidden": int(enc.config.hidden_size),
            "n_out": n_out,
        }
        self.max_len_ = max_len
        self.is_clf_ = is_clf
        self.backend_ = "hf"
        self.n_out_ = n_out
        self.history_ = {
            "metric": "loss",
            "train": train_hist,
            "valid": [],
            "x": list(range(1, len(train_hist) + 1)),
            "x_name": "epoch",
        }
        return self

    def _forward_np(self, X):
        import torch
        texts = self._texts(X)
        device = resolve_torch_device(getattr(self, "used_device_", "cpu"))
        if getattr(self, "backend_", "scratch") == "hf":
            from transformers import AutoModel, AutoTokenizer
            tokenizer = AutoTokenizer.from_pretrained(self.tokenizer_name_)
            enc = AutoModel.from_pretrained(self.tokenizer_name_)
            head = torch.nn.Linear(self.hf_state_["hidden"], self.hf_state_["n_out"])
            enc.load_state_dict(self.hf_state_["encoder"])
            head.load_state_dict(self.hf_state_["head"])
            enc.to(device).eval()
            head.to(device).eval()
            outs = []
            bs = 32
            with torch.no_grad():
                for start in range(0, len(texts), bs):
                    tok = tokenizer(
                        texts[start:start + bs], padding=True, truncation=True,
                        max_length=self.max_len_, return_tensors="pt",
                    )
                    tok = {k: v.to(device) for k, v in tok.items()}
                    hidden = enc(**tok).last_hidden_state[:, 0]
                    outs.append(head(hidden).detach().cpu().numpy())
            return np.concatenate(outs, axis=0)
        ids = self._encode(texts, self.stoi_, self.max_len_)
        net = self.net_.to(device).eval()
        xt = torch.tensor(ids, dtype=torch.long, device=device)
        outs = []
        with torch.no_grad():
            for start in range(0, len(ids), 64):
                outs.append(net(xt[start:start + 64]).detach().cpu().numpy())
        self.net_ = net.cpu()
        return np.concatenate(outs, axis=0)

    def predict(self, X):
        raw = self._forward_np(X)
        if getattr(self, "is_clf_", False):
            return self.classes_[np.argmax(raw, axis=1)]
        return raw.ravel()

    def predict_proba(self, X):
        if not getattr(self, "is_clf_", False):
            raise AttributeError("回归 BERT 没有 predict_proba")
        z = self._forward_np(X)
        z = z - z.max(axis=1, keepdims=True)
        e = np.exp(z)
        return e / np.clip(e.sum(axis=1, keepdims=True), 1e-12, None)

    def __getstate__(self):
        state = dict(self.__dict__)
        net = state.pop("net_", None)
        if net is not None:
            state["_state_dict"] = {k: v.detach().cpu() for k, v in net.state_dict().items()}
            state["_vocab"] = len(getattr(self, "stoi_", {}) or {})
        return state

    def __setstate__(self, state):
        sd = state.pop("_state_dict", None)
        vocab = state.pop("_vocab", None)
        self.__dict__.update(state)
        if sd is not None and torch_available() and getattr(self, "backend_", "scratch") == "scratch":
            import torch
            net = _bert_module(
                torch, int(vocab or len(self.stoi_)), int(self.d_model),
                max(1, int(self.n_layers)), _nhead(int(self.d_model)),
                int(getattr(self, "max_len_", self.max_length)), int(getattr(self, "n_out_", 1)),
            )
            net.load_state_dict(sd)
            self.net_ = net


# mixin 让 sklearn 识别回归 BERT
class BertRegressor(BertTabularEstimator, RegressorMixin):
    pass


class BertClassifier(BertTabularEstimator, ClassifierMixin):
    pass
