# -*- coding: utf-8 -*-
"""可扩展模型动物园：新增算法只需在 ZOO 注册。"""
from __future__ import annotations

import os
from contextlib import contextmanager

import numpy as np
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.neural_network import MLPClassifier, MLPRegressor
from sklearn.linear_model import Lasso, LinearRegression, LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC, SVR
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor

OPTIONAL = {}
try:
    import xgboost as xgb
    OPTIONAL["xgboost"] = xgb
except Exception:
    xgb = None
try:
    import lightgbm as lgb
    OPTIONAL["lightgbm"] = lgb
except Exception:
    lgb = None
try:
    import catboost as cb
    OPTIONAL["catboost"] = cb
except Exception:
    cb = None
try:
    from trainers.nn_est import BertClassifier, BertRegressor, SoftmaxEstimator, torch_available
    OPTIONAL["torch"] = True
except Exception:
    BertClassifier = None
    BertRegressor = None
    SoftmaxEstimator = None

    def torch_available():
        return False

_CUDA_READY = None
_NVIDIA = None
_LGB_DEVICE = None
_CAT_GPU = None


def nvidia_present():
    global _NVIDIA
    if _NVIDIA is not None:
        return _NVIDIA
    _NVIDIA = False
    try:
        import subprocess
        proc = subprocess.run(
            ["nvidia-smi", "-L"], capture_output=True, text=True, timeout=8,
        )
        _NVIDIA = proc.returncode == 0 and "GPU" in ((proc.stdout or "") + (proc.stderr or ""))
    except Exception:
        _NVIDIA = False
    return _NVIDIA


def cuda_available():
    """本机 NVIDIA GPU + 当前 XGBoost CUDA 构建是否能真正拟合。"""
    global _CUDA_READY
    if _CUDA_READY is not None:
        return _CUDA_READY
    _CUDA_READY = False
    if not nvidia_present() or "xgboost" not in OPTIONAL:
        return False
    info = {}
    try:
        info = OPTIONAL["xgboost"].build_info() or {}
    except Exception:
        info = {}
    if info and not info.get("USE_CUDA"):
        return False
    try:
        X = np.zeros((16, 4), dtype=np.float32)
        y = np.zeros(16, dtype=np.float32)
        est = OPTIONAL["xgboost"].XGBRegressor(
            n_estimators=1, max_depth=1, tree_method="hist", device="cuda", verbosity=0,
        )
        est.fit(X, y)
        _CUDA_READY = True
    except Exception:
        _CUDA_READY = False
    return _CUDA_READY


def _want_gpu(params):
    raw = str((params or {}).get("device") or (params or {}).get("task_type") or "").strip().lower()
    if raw in ("cpu", "host"):
        return False
    if raw in ("cuda", "gpu", "cuda:0"):
        return True
    return nvidia_present()


def _xgboost_device(params):
    raw = str((params or {}).get("device") or "").strip().lower()
    method = str((params or {}).get("tree_method") or "").strip().lower()
    if raw in ("cpu", "host") or method in ("exact",):
        return "cpu"
    if not _want_gpu(params) and method not in ("gpu_hist", "gpu"):
        return "cpu"
    return "cuda" if cuda_available() else "cpu"


def lightgbm_device(params=None):
    """当前 pip 版 LightGBM 多为 CPU 构建；能 GPU 就用，否则 CPU。"""
    global _LGB_DEVICE
    if not _want_gpu(params):
        return "cpu"
    if _LGB_DEVICE is not None:
        return _LGB_DEVICE
    _LGB_DEVICE = "cpu"
    if "lightgbm" not in OPTIONAL or not nvidia_present():
        return _LGB_DEVICE
    X = np.zeros((32, 4), dtype=np.float32)
    y = np.zeros(32, dtype=np.float32)
    for dev in ("cuda", "gpu"):
        try:
            est = OPTIONAL["lightgbm"].LGBMRegressor(n_estimators=1, max_depth=1, device=dev, verbosity=-1)
            with _quiet_native_stderr():
                est.fit(X, y)
            _LGB_DEVICE = dev
            return _LGB_DEVICE
        except Exception:
            continue
    return _LGB_DEVICE


def catboost_task_type(params=None):
    global _CAT_GPU
    if not _want_gpu(params):
        return "CPU"
    if _CAT_GPU is not None:
        return "GPU" if _CAT_GPU else "CPU"
    _CAT_GPU = False
    if "catboost" not in OPTIONAL or not nvidia_present():
        return "CPU"
    try:
        X = np.zeros((32, 4), dtype=np.float32)
        y = np.zeros(32, dtype=np.float32)
        est = OPTIONAL["catboost"].CatBoostRegressor(iterations=2, depth=2, task_type="GPU", devices="0", verbose=False)
        with _quiet_native_stderr():
            est.fit(X, y)
        _CAT_GPU = True
    except Exception:
        _CAT_GPU = False
    return "GPU" if _CAT_GPU else "CPU"


ZOO = {
    "linear": {
        "key": "linear",
        "name": "线性回归",
        "family": "线性模型",
        "available": True,
        "tasks": ["regression"],
        "presets": {
            "fast": {"fit_intercept": True},
            "balanced": {"fit_intercept": True},
            "accurate": {"fit_intercept": True},
        },
        "params": [
            {"key": "fit_intercept", "label": "拟合截距", "type": "select", "default": True, "options": [True, False]},
        ],
        "tips": "只支持回归。sklearn OLS，无 CUDA 接口，始终用 CPU。",
    },
    "ridge": {
        "key": "ridge",
        "name": "岭回归",
        "family": "线性模型",
        "available": True,
        "tasks": ["regression"],
        "presets": {
            "fast": {"alpha": 10.0, "fit_intercept": True},
            "balanced": {"alpha": 1.0, "fit_intercept": True},
            "accurate": {"alpha": 0.1, "fit_intercept": True},
        },
        "params": [
            {"key": "alpha", "label": "L2 强度 alpha", "type": "float", "default": 1.0, "min": 0.0001, "max": 1000, "step": 0.01},
            {"key": "fit_intercept", "label": "拟合截距", "type": "select", "default": True, "options": [True, False]},
        ],
        "tips": "只支持回归。L2 正则线性模型，sklearn 实现，始终用 CPU。",
    },
    "lasso": {
        "key": "lasso",
        "name": "Lasso 回归",
        "family": "线性模型",
        "available": True,
        "tasks": ["regression"],
        "presets": {
            "fast": {"alpha": 0.01, "max_iter": 2000, "fit_intercept": True},
            "balanced": {"alpha": 0.001, "max_iter": 4000, "fit_intercept": True},
            "accurate": {"alpha": 0.0001, "max_iter": 8000, "fit_intercept": True},
        },
        "params": [
            {"key": "alpha", "label": "L1 强度 alpha", "type": "float", "default": 0.001, "min": 0.00001, "max": 10, "step": 0.0001},
            {"key": "max_iter", "label": "最大迭代", "type": "int", "default": 4000, "min": 200, "max": 20000},
            {"key": "fit_intercept", "label": "拟合截距", "type": "select", "default": True, "options": [True, False]},
        ],
        "tips": "只支持回归。L1 稀疏线性模型，sklearn 实现，始终用 CPU。",
    },
    "logistic": {
        "key": "logistic",
        "name": "逻辑回归",
        "family": "线性模型",
        "available": True,
        "tasks": ["classification"],
        "presets": {
            "fast": {"C": 0.5, "max_iter": 200},
            "balanced": {"C": 1.0, "max_iter": 400},
            "accurate": {"C": 4.0, "max_iter": 800},
        },
        "params": [
            {"key": "C", "label": "正则系数 C", "type": "float", "default": 1.0, "min": 0.01, "max": 100},
            {"key": "max_iter", "label": "最大迭代", "type": "int", "default": 400, "min": 50, "max": 4000},
        ],
        "tips": "只支持分类。sklearn LogisticRegression，无 CUDA 接口，始终用 CPU。",
    },
    "softmax": {
        "key": "softmax",
        "name": "Softmax",
        "family": "线性模型",
        "available": True,
        "tasks": ["classification"],
        "presets": {
            "fast": {"C": 1.0, "epochs": 40, "learning_rate": 0.05, "batch_size": 256, "max_iter": 200},
            "balanced": {"C": 1.0, "epochs": 80, "learning_rate": 0.03, "batch_size": 256, "max_iter": 400},
            "accurate": {"C": 4.0, "epochs": 160, "learning_rate": 0.01, "batch_size": 128, "max_iter": 800},
        },
        "params": [
            {"key": "C", "label": "正则系数 C", "type": "float", "default": 1.0, "min": 0.01, "max": 100},
            {"key": "epochs", "label": "训练轮数", "type": "int", "default": 80, "min": 10, "max": 400},
            {"key": "learning_rate", "label": "学习率", "type": "float", "default": 0.03, "min": 0.0001, "max": 0.5, "step": 0.001},
            {"key": "batch_size", "label": "批大小", "type": "int", "default": 256, "min": 16, "max": 2048},
            {"key": "max_iter", "label": "CPU 最大迭代", "type": "int", "default": 400, "min": 50, "max": 4000},
        ],
        "tips": "只支持分类。已安装 PyTorch 且有 NVIDIA 时用显卡 Softmax；否则回退 sklearn 多项式逻辑回归（CPU）。",
    },
    "svm": {
        "key": "svm",
        "name": "支持向量机",
        "family": "经典机器学习",
        "available": True,
        "tasks": ["regression", "classification"],
        "presets": {
            "fast": {"C": 1.0, "kernel": "linear", "epsilon": 0.2, "gamma": "scale"},
            "balanced": {"C": 1.0, "kernel": "rbf", "epsilon": 0.1, "gamma": "scale"},
            "accurate": {"C": 10.0, "kernel": "rbf", "epsilon": 0.05, "gamma": "scale"},
        },
        "params": [
            {"key": "C", "label": "正则系数 C", "type": "float", "default": 1.0, "min": 0.01, "max": 100},
            {"key": "kernel", "label": "核函数", "type": "select", "default": "rbf", "options": ["linear", "rbf", "poly"]},
            {"key": "epsilon", "label": "SVR epsilon", "type": "float", "default": 0.1, "min": 0.01, "max": 1},
            {"key": "gamma", "label": "gamma", "type": "select", "default": "scale", "options": ["scale", "auto"]},
        ],
        "tips": "sklearn 实现，无 CUDA 接口，始终用 CPU 多核。",
    },
    "mlp": {
        "key": "mlp",
        "name": "神经网络",
        "family": "深度学习",
        "available": True,
        "tasks": ["regression", "classification"],
        "presets": {
            "fast": {"hidden_layer_sizes": "64,32", "max_iter": 80, "learning_rate_init": 0.001, "activation": "relu", "alpha": 0.001},
            "balanced": {"hidden_layer_sizes": "128,64", "max_iter": 200, "learning_rate_init": 0.001, "activation": "relu", "alpha": 0.0001},
            "accurate": {"hidden_layer_sizes": "256,128,64", "max_iter": 400, "learning_rate_init": 0.0005, "activation": "relu", "alpha": 0.0001},
        },
        "params": [
            {"key": "hidden_layer_sizes", "label": "隐藏层", "type": "string", "default": "128,64"},
            {"key": "activation", "label": "激活函数", "type": "select", "default": "relu", "options": ["relu", "tanh", "logistic"]},
            {"key": "learning_rate_init", "label": "学习率", "type": "float", "default": 0.001, "min": 0.0001, "max": 0.1, "step": 0.0001},
            {"key": "max_iter", "label": "最大迭代", "type": "int", "default": 200, "min": 50, "max": 2000},
            {"key": "alpha", "label": "L2 正则", "type": "float", "default": 0.0001, "min": 0, "max": 0.1, "step": 0.0001},
        ],
        "tips": "sklearn MLP 无 CUDA；有 NVIDIA 时请改用 XGBoost / CatBoost / BERT。对标准化敏感。",
    },
    "bert": {
        "key": "bert",
        "name": "BERT",
        "family": "深度学习",
        "available": True,
        "tasks": ["regression", "classification"],
        "presets": {
            "fast": {"epochs": 2, "learning_rate": 0.0005, "batch_size": 32, "max_length": 48, "n_layers": 2, "d_model": 128, "pretrained": "scratch"},
            "balanced": {"epochs": 4, "learning_rate": 0.0003, "batch_size": 32, "max_length": 64, "n_layers": 2, "d_model": 128, "pretrained": "scratch"},
            "accurate": {"epochs": 8, "learning_rate": 0.0002, "batch_size": 16, "max_length": 96, "n_layers": 4, "d_model": 128, "pretrained": "scratch"},
        },
        "params": [
            {"key": "epochs", "label": "训练轮数", "type": "int", "default": 4, "min": 1, "max": 20},
            {"key": "learning_rate", "label": "学习率", "type": "float", "default": 0.0003, "min": 0.00001, "max": 0.01, "step": 0.0001},
            {"key": "batch_size", "label": "批大小", "type": "int", "default": 32, "min": 4, "max": 128},
            {"key": "max_length", "label": "最大文本长度", "type": "int", "default": 64, "min": 16, "max": 128},
            {"key": "n_layers", "label": "Transformer 层数", "type": "int", "default": 2, "min": 1, "max": 6},
            {"key": "d_model", "label": "隐层维度", "type": "int", "default": 128, "min": 64, "max": 256},
            {"key": "pretrained", "label": "权重来源", "type": "select", "default": "scratch", "options": ["scratch", "distilbert"]},
        ],
        "tips": "表格行会拼成文本后用 BERT-Tiny（Transformer + CLS）训练。检测到 NVIDIA 且已装 PyTorch 时走 CUDA，否则 CPU。CPU 建议抽样 5000~20000 行。选 distilbert 需另装 transformers。",
    },
    "decision_tree": {
        "key": "decision_tree",
        "name": "决策树",
        "family": "树模型",
        "available": True,
        "tasks": ["regression", "classification"],
        "presets": {
            "fast": {"max_depth": 6, "min_samples_split": 20, "min_samples_leaf": 10},
            "balanced": {"max_depth": 10, "min_samples_split": 10, "min_samples_leaf": 5},
            "accurate": {"max_depth": 16, "min_samples_split": 4, "min_samples_leaf": 2},
        },
        "params": [
            {"key": "max_depth", "label": "最大深度", "type": "int", "default": 10, "min": 2, "max": 32},
            {"key": "min_samples_split", "label": "分裂最小样本", "type": "int", "default": 10, "min": 2, "max": 200},
            {"key": "min_samples_leaf", "label": "叶节点最小样本", "type": "int", "default": 5, "min": 1, "max": 100},
        ],
        "tips": "sklearn 实现，无 CUDA 接口，始终用 CPU。",
    },
    "random_forest": {
        "key": "random_forest",
        "name": "随机森林",
        "family": "树模型",
        "available": True,
        "tasks": ["regression", "classification"],
        "presets": {
            "fast": {"n_estimators": 80, "max_depth": 8, "min_samples_leaf": 5, "max_features": "sqrt"},
            "balanced": {"n_estimators": 200, "max_depth": 12, "min_samples_leaf": 2, "max_features": "sqrt"},
            "accurate": {"n_estimators": 400, "max_depth": 16, "min_samples_leaf": 1, "max_features": "sqrt"},
        },
        "params": [
            {"key": "n_estimators", "label": "树的数量", "type": "int", "default": 200, "min": 20, "max": 1000},
            {"key": "max_depth", "label": "最大深度", "type": "int", "default": 12, "min": 2, "max": 40},
            {"key": "min_samples_leaf", "label": "叶节点最小样本", "type": "int", "default": 2, "min": 1, "max": 50},
            {"key": "max_features", "label": "特征采样", "type": "select", "default": "sqrt", "options": ["sqrt", "log2", None]},
        ],
        "tips": "sklearn 实现，无 CUDA 接口，用 CPU 多核并行。",
    },
    "gbdt": {
        "key": "gbdt",
        "name": "GBDT",
        "family": "提升树",
        "available": True,
        "tasks": ["regression", "classification"],
        "presets": {
            "fast": {"n_estimators": 80, "learning_rate": 0.1, "max_depth": 3, "subsample": 0.8},
            "balanced": {"n_estimators": 200, "learning_rate": 0.05, "max_depth": 4, "subsample": 0.8},
            "accurate": {"n_estimators": 400, "learning_rate": 0.03, "max_depth": 5, "subsample": 0.9},
        },
        "params": [
            {"key": "n_estimators", "label": "迭代轮数", "type": "int", "default": 200, "min": 50, "max": 1500},
            {"key": "learning_rate", "label": "学习率", "type": "float", "default": 0.05, "min": 0.001, "max": 0.5},
            {"key": "max_depth", "label": "最大深度", "type": "int", "default": 4, "min": 1, "max": 8},
            {"key": "subsample", "label": "样本采样率", "type": "float", "default": 0.8, "min": 0.4, "max": 1},
        ],
        "tips": "sklearn 实现，无 CUDA 接口，始终用 CPU。GPU 请用 XGBoost / CatBoost。",
    },
    "catboost": {
        "key": "catboost",
        "name": "CatBoost",
        "family": "提升树",
        "available": "catboost" in OPTIONAL,
        "tasks": ["regression", "classification"],
        "presets": {
            "fast": {"iterations": 200, "learning_rate": 0.08, "depth": 6, "l2_leaf_reg": 3.0},
            "balanced": {"iterations": 500, "learning_rate": 0.05, "depth": 8, "l2_leaf_reg": 3.0},
            "accurate": {"iterations": 1000, "learning_rate": 0.03, "depth": 8, "l2_leaf_reg": 2.0},
        },
        "params": [
            {"key": "iterations", "label": "迭代轮数", "type": "int", "default": 500, "min": 50, "max": 4000},
            {"key": "learning_rate", "label": "学习率", "type": "float", "default": 0.05, "min": 0.001, "max": 0.5},
            {"key": "depth", "label": "树深度", "type": "int", "default": 8, "min": 2, "max": 12},
            {"key": "l2_leaf_reg", "label": "L2 正则", "type": "float", "default": 3.0, "min": 1, "max": 10},
        ],
        "tips": "检测到 NVIDIA GPU 时自动 task_type=GPU，失败则回退 CPU。",
    },
    "lightgbm": {
        "key": "lightgbm",
        "name": "LightGBM",
        "family": "提升树",
        "available": "lightgbm" in OPTIONAL,
        "tasks": ["regression", "classification"],
        "presets": {
            "fast": {"n_estimators": 200, "learning_rate": 0.08, "num_leaves": 31, "max_depth": -1, "subsample": 0.8, "colsample_bytree": 0.8},
            "balanced": {"n_estimators": 500, "learning_rate": 0.05, "num_leaves": 48, "max_depth": -1, "subsample": 0.8, "colsample_bytree": 0.8},
            "accurate": {"n_estimators": 1200, "learning_rate": 0.03, "num_leaves": 64, "max_depth": -1, "subsample": 0.9, "colsample_bytree": 0.8},
        },
        "params": [
            {"key": "n_estimators", "label": "迭代轮数", "type": "int", "default": 500, "min": 50, "max": 5000},
            {"key": "learning_rate", "label": "学习率", "type": "float", "default": 0.05, "min": 0.001, "max": 0.5},
            {"key": "num_leaves", "label": "叶子数", "type": "int", "default": 48, "min": 8, "max": 256},
            {"key": "max_depth", "label": "最大深度(-1不限)", "type": "int", "default": -1, "min": -1, "max": 20},
            {"key": "subsample", "label": "样本采样", "type": "float", "default": 0.8, "min": 0.4, "max": 1},
            {"key": "colsample_bytree", "label": "特征采样", "type": "float", "default": 0.8, "min": 0.4, "max": 1},
        ],
        "tips": "当前环境 LightGBM 为 CPU 构建时会自动回退 CPU；若安装了 GPU/CUDA 版则走显卡。",
    },
    "xgboost": {
        "key": "xgboost",
        "name": "XGBoost",
        "family": "提升树",
        "available": "xgboost" in OPTIONAL,
        "tasks": ["regression", "classification"],
        "presets": {
            "fast": {"n_estimators": 200, "max_depth": 6, "learning_rate": 0.08, "min_child_weight": 3, "subsample": 0.8, "colsample_bytree": 0.8},
            "balanced": {"n_estimators": 500, "max_depth": 8, "learning_rate": 0.05, "min_child_weight": 3, "subsample": 0.9, "colsample_bytree": 0.7},
            "accurate": {"n_estimators": 8000, "max_depth": 13, "learning_rate": 0.01, "min_child_weight": 3, "subsample": 0.9, "colsample_bytree": 0.7},
        },
        "params": [
            {"key": "n_estimators", "label": "树的数量", "type": "int", "default": 500, "min": 50, "max": 8000},
            {"key": "max_depth", "label": "最大深度", "type": "int", "default": 8, "min": 2, "max": 16},
            {"key": "learning_rate", "label": "学习率 eta", "type": "float", "default": 0.05, "min": 0.001, "max": 0.5},
            {"key": "min_child_weight", "label": "最小子节点权重", "type": "int", "default": 3, "min": 1, "max": 20},
            {"key": "subsample", "label": "样本采样率", "type": "float", "default": 0.9, "min": 0.4, "max": 1},
            {"key": "colsample_bytree", "label": "特征采样率", "type": "float", "default": 0.7, "min": 0.4, "max": 1},
        ],
        "tips": "检测到 NVIDIA GPU 时自动用 CUDA 训练。高精度预设 8000 棵树，无显卡时会较慢。",
    },
}


def list_zoo():
    items = []
    for key, meta in ZOO.items():
        item = dict(meta)
        if key == "bert":
            item["available"] = bool(torch_available())
        else:
            item["available"] = bool(meta.get("available"))
        items.append(item)
    return items


def coerce_task_type(model_type, task):
    meta = ZOO.get(model_type) or {}
    allowed = list(meta.get("tasks") or ["regression", "classification"])
    t = str(task or "").strip() or (allowed[0] if allowed else "regression")
    if t not in allowed:
        t = allowed[0] if allowed else "regression"
    return t


def _as_bool(params, key, default=True):
    raw = (params or {}).get(key, default)
    if raw in (False, 0, "0", "false", "False", "no", "否"):
        return False
    if raw in (True, 1, "1", "true", "True", "yes", "是"):
        return True
    return bool(default)


def _hidden_tuple(value):
    if isinstance(value, (list, tuple)):
        return tuple(int(x) for x in value)
    text = str(value or "128,64")
    parts = [int(p.strip()) for p in text.split(",") if p.strip()]
    return tuple(parts or [128, 64])


def _as_num(params, key, default, cast=float):
    raw = (params or {}).get(key, default)
    if raw is None or raw == "":
        raw = default
    try:
        return cast(raw)
    except (TypeError, ValueError):
        return cast(default)


def build_estimator(model_type, task, params):
    params = params or {}
    meta = ZOO.get(model_type)
    if not meta:
        raise ValueError(f"未知模型: {model_type}")
    if not meta.get("available"):
        raise ValueError(f"{meta['name']} 当前环境未安装，请先在 conda 环境 data-analysis 中安装对应包")

    is_reg = task != "classification"
    allowed = list(meta.get("tasks") or ["regression", "classification"])
    if is_reg and "regression" not in allowed:
        raise ValueError(f"{meta['name']} 只支持分类任务，请把任务类型改为分类")
    if (not is_reg) and "classification" not in allowed:
        raise ValueError(f"{meta['name']} 只支持回归任务，请把任务类型改为回归")
    p = params

    if model_type == "svm":
        common = dict(
            C=_as_num(p, "C", 1.0),
            kernel=p.get("kernel") or "rbf",
            gamma=p.get("gamma") or "scale",
        )
        est = SVR(epsilon=_as_num(p, "epsilon", 0.1), **common) if is_reg else SVC(probability=True, **common)
        return _with_scaler(est)

    if model_type == "mlp":
        common = dict(
            hidden_layer_sizes=_hidden_tuple(p.get("hidden_layer_sizes", "128,64")),
            activation=p.get("activation") or "relu",
            learning_rate_init=_as_num(p, "learning_rate_init", 0.001),
            max_iter=int(_as_num(p, "max_iter", 200, int)),
            alpha=_as_num(p, "alpha", 0.0001),
            early_stopping=True,
            random_state=int(_as_num(p, "random_state", 42, int)),
        )
        est = MLPRegressor(**common) if is_reg else MLPClassifier(**common)
        return _with_scaler(est, scale_target=is_reg)

    if model_type == "decision_tree":
        common = dict(
            max_depth=int(_as_num(p, "max_depth", 10, int)),
            min_samples_split=int(_as_num(p, "min_samples_split", 10, int)),
            min_samples_leaf=int(_as_num(p, "min_samples_leaf", 5, int)),
            random_state=int(_as_num(p, "random_state", 42, int)),
        )
        return DecisionTreeRegressor(**common) if is_reg else DecisionTreeClassifier(**common)

    if model_type == "random_forest":
        mf = p.get("max_features", "sqrt")
        if mf in ("None", "none", ""):
            mf = None
        common = dict(
            n_estimators=int(_as_num(p, "n_estimators", 200, int)),
            max_depth=int(_as_num(p, "max_depth", 12, int)),
            min_samples_leaf=int(_as_num(p, "min_samples_leaf", 2, int)),
            max_features=mf if mf is not None else "sqrt",
            n_jobs=-1,
            random_state=int(_as_num(p, "random_state", 42, int)),
        )
        return RandomForestRegressor(**common) if is_reg else RandomForestClassifier(**common)

    if model_type == "gbdt":
        common = dict(
            n_estimators=int(_as_num(p, "n_estimators", 200, int)),
            learning_rate=_as_num(p, "learning_rate", 0.05),
            max_depth=int(_as_num(p, "max_depth", 4, int)),
            subsample=_as_num(p, "subsample", 0.8),
            random_state=int(_as_num(p, "random_state", 42, int)),
        )
        return GradientBoostingRegressor(**common) if is_reg else GradientBoostingClassifier(**common)

    if model_type == "xgboost":
        device = _xgboost_device(p)
        common = dict(
            n_estimators=int(_as_num(p, "n_estimators", 500, int)),
            max_depth=int(_as_num(p, "max_depth", 8, int)),
            learning_rate=_as_num(p, "learning_rate", 0.05),
            min_child_weight=int(_as_num(p, "min_child_weight", 3, int)),
            subsample=_as_num(p, "subsample", 0.9),
            colsample_bytree=_as_num(p, "colsample_bytree", 0.7),
            n_jobs=-1,
            random_state=int(_as_num(p, "random_state", 42, int)),
            tree_method="hist",
            device=device,
        )
        return OPTIONAL["xgboost"].XGBRegressor(**common) if is_reg else OPTIONAL["xgboost"].XGBClassifier(**common)

    if model_type == "lightgbm":
        device = lightgbm_device(p)
        common = dict(
            n_estimators=int(_as_num(p, "n_estimators", 500, int)),
            learning_rate=_as_num(p, "learning_rate", 0.05),
            num_leaves=int(_as_num(p, "num_leaves", 48, int)),
            max_depth=int(_as_num(p, "max_depth", -1, int)),
            subsample=_as_num(p, "subsample", 0.8),
            colsample_bytree=_as_num(p, "colsample_bytree", 0.8),
            random_state=int(_as_num(p, "random_state", 42, int)),
            verbose=-1,
            device=device,
        )
        return OPTIONAL["lightgbm"].LGBMRegressor(**common) if is_reg else OPTIONAL["lightgbm"].LGBMClassifier(**common)

    if model_type == "catboost":
        task_type = catboost_task_type(p)
        common = dict(
            iterations=int(_as_num(p, "iterations", 500, int)),
            learning_rate=_as_num(p, "learning_rate", 0.05),
            depth=int(_as_num(p, "depth", 8, int)),
            l2_leaf_reg=_as_num(p, "l2_leaf_reg", 3.0),
            verbose=False,
            random_state=int(_as_num(p, "random_state", 42, int)),
            task_type=task_type,
        )
        if task_type == "GPU":
            common["devices"] = "0"
        return OPTIONAL["catboost"].CatBoostRegressor(**common) if is_reg else OPTIONAL["catboost"].CatBoostClassifier(**common)

    if model_type == "linear":
        return LinearRegression(fit_intercept=_as_bool(p, "fit_intercept", True))

    if model_type == "ridge":
        return Ridge(
            alpha=_as_num(p, "alpha", 1.0),
            fit_intercept=_as_bool(p, "fit_intercept", True),
            random_state=int(_as_num(p, "random_state", 42, int)),
        )

    if model_type == "lasso":
        return Lasso(
            alpha=_as_num(p, "alpha", 0.001),
            max_iter=int(_as_num(p, "max_iter", 4000, int)),
            fit_intercept=_as_bool(p, "fit_intercept", True),
            random_state=int(_as_num(p, "random_state", 42, int)),
        )

    if model_type == "logistic":
        return LogisticRegression(
            C=_as_num(p, "C", 1.0),
            max_iter=int(_as_num(p, "max_iter", 400, int)),
            solver="lbfgs",
            random_state=int(_as_num(p, "random_state", 42, int)),
        )

    if model_type == "softmax":
        if torch_available() and SoftmaxEstimator is not None:
            return SoftmaxEstimator(
                epochs=int(_as_num(p, "epochs", 80, int)),
                learning_rate=_as_num(p, "learning_rate", 0.03),
                batch_size=int(_as_num(p, "batch_size", 256, int)),
                C=_as_num(p, "C", 1.0),
                random_state=int(_as_num(p, "random_state", 42, int)),
                device=p.get("device") or "auto",
            )
        return LogisticRegression(
            C=_as_num(p, "C", 1.0),
            max_iter=int(_as_num(p, "max_iter", 400, int)),
            solver="lbfgs",
            random_state=int(_as_num(p, "random_state", 42, int)),
        )

    if model_type == "bert":
        if not torch_available() or BertRegressor is None:
            raise ValueError("BERT 需要 PyTorch。请在 conda 环境 data-analysis 中安装 torch 后再训练")
        common = dict(
            epochs=int(_as_num(p, "epochs", 4, int)),
            learning_rate=_as_num(p, "learning_rate", 0.0003),
            batch_size=int(_as_num(p, "batch_size", 32, int)),
            max_length=int(_as_num(p, "max_length", 64, int)),
            n_layers=int(_as_num(p, "n_layers", 2, int)),
            d_model=int(_as_num(p, "d_model", 128, int)),
            pretrained=p.get("pretrained") or "scratch",
            task="regression" if is_reg else "classification",
            random_state=int(_as_num(p, "random_state", 42, int)),
            device=p.get("device") or "auto",
        )
        return BertRegressor(**common) if is_reg else BertClassifier(**common)

    raise ValueError(f"未实现模型: {model_type}")


@contextmanager
def _quiet_native_stderr():
    """GPU 探测失败时，LightGBM / CatBoost 会往 C 层的 stderr 打 Fatal，探测本身还会继续回退。"""
    devnull = os.open(os.devnull, os.O_WRONLY)
    saved = os.dup(2)
    try:
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(saved, 2)
        os.close(saved)
        os.close(devnull)


def _with_scaler(est, scale_target=False):
    """SVM / MLP 对特征量纲敏感。回归 MLP 同时缩放目标，避免销量这种大数值训不收敛。"""
    pipe = Pipeline([("scale", StandardScaler()), ("model", est)])
    if not scale_target:
        return pipe
    return TransformedTargetRegressor(regressor=pipe, transformer=StandardScaler())


def _leaf_estimator(model):
    if hasattr(model, "named_steps"):
        return model.named_steps.get("model") or list(model.named_steps.values())[-1]
    return model


def native_importance(model, feature_names):
    names = list(feature_names)
    model = _leaf_estimator(model)
    if hasattr(model, "feature_importances_"):
        values = np.array(model.feature_importances_, dtype=float)
    elif hasattr(model, "coef_"):
        coef = np.array(model.coef_, dtype=float)
        values = np.abs(coef).mean(axis=0) if coef.ndim > 1 else np.abs(coef)
    else:
        return None
    if values.sum() > 0:
        values = values / values.sum()
    items = [{"feature": n, "score": float(v)} for n, v in zip(names, values)]
    items.sort(key=lambda x: x["score"], reverse=True)
    return items


def perm_importance(model, X, y, feature_names, n_repeats=3, n_max=2500):
    n = min(len(X), int(n_max or 2500))
    rng = np.random.RandomState(42)
    idx = rng.choice(len(X), n, replace=False)
    result = permutation_importance(model, X[idx], y[idx], n_repeats=n_repeats, random_state=42, n_jobs=-1)
    values = np.array(result.importances_mean, dtype=float)
    values = np.clip(values, 0, None)
    if values.sum() > 0:
        values = values / values.sum()
    items = [{"feature": n, "score": float(v)} for n, v in zip(feature_names, values)]
    items.sort(key=lambda x: x["score"], reverse=True)
    return items
