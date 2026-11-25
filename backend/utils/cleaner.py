# -*- coding: utf-8 -*-
import re
from collections import Counter

import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder, StandardScaler, MinMaxScaler

_TOKEN_SPLIT = re.compile(r"[,;|/&+，、\n\t]+")
# 预测时不能按训练集那样丢行，否则手填一条会被过滤掉
SCORE_SKIP_OPS = {"filter", "drop_duplicates", "drop_null_rows"}


def _scale_label_exclude():
    """负荷/电价/销量等标签列不能随特征一起标准化，否则预测值会停在 z 分数上。"""
    extra = {"Sales", "Customers", "sales", "target", "label", "y"}
    try:
        from utils.power_features import LABEL_COLS
        extra |= set(LABEL_COLS)
    except Exception:
        extra |= {"load_mw", "wind_mw", "solar_mw", "renewable_mw", "price_da", "price_rt"}
    return extra


def discover_tokens(series, max_tokens=40):
    """从文本列探查可打标词：按逗号/分号等切分后统计频次。"""
    counter = Counter()
    texts = series.dropna().astype(str)
    for raw in texts.head(8000):
        s = str(raw).strip()
        if not s or s.lower() in ("nan", "none", "null", "nat"):
            continue
        parts = [p.strip() for p in _TOKEN_SPLIT.split(s) if p.strip()]
        if len(parts) <= 1 and " " in s and len(s) < 80:
            parts = [p.strip() for p in re.split(r"\s+", s) if p.strip()]
        if not parts:
            parts = [s]
        for p in parts:
            if 1 <= len(p) <= 32:
                counter[p] += 1
    return [{"token": t, "count": int(c)} for t, c in counter.most_common(max_tokens)]


OPS = [
    {
        "op": "filter",
        "label": "条件过滤",
        "category": "clean",
        "desc": "按列条件保留行，如 Sales > 0（参考 Rossmann）",
        "fields": "single",
        "ui": ["column", "operator", "value"],
    },
    {
        "op": "drop_duplicates",
        "label": "去除重复行",
        "category": "clean",
        "desc": "按全部或指定列去重",
        "fields": "multi",
        "ui": ["columns"],
    },
    {
        "op": "drop_null_rows",
        "label": "删除空值行",
        "category": "clean",
        "desc": "指定列存在空值则删除整行",
        "fields": "multi",
        "ui": ["columns"],
    },
    {
        "op": "fill_missing",
        "label": "缺失值填充",
        "category": "clean",
        "desc": "默认自动：数值均值、非数值众数；也可按字段覆盖策略",
        "fields": "multi",
        "ui": ["columns", "strategy", "column_strategies", "value"],
    },
    {
        "op": "clip_outlier",
        "label": "异常值裁剪",
        "category": "clean",
        "desc": "一个节点里可为不同字段配置不同上下限",
        "fields": "multi",
        "ui": ["ranges", "method", "low", "high"],
    },
    {
        "op": "parse_date",
        "label": "日期拆解",
        "category": "feature",
        "desc": "从日期时间列提取年/月/日/星期/时/分/秒",
        "fields": "single",
        "ui": ["column", "extract"],
    },
    {
        "op": "split_flags",
        "label": "文本打标",
        "category": "feature",
        "desc": "如 PromoInterval 拆成月份 0/1 标记",
        "fields": "single",
        "ui": ["column", "tokens", "prefix"],
    },
    {
        "op": "drop_columns",
        "label": "删除列",
        "category": "feature",
        "desc": "去掉 ID、原始日期、泄漏列等",
        "fields": "multi",
        "ui": ["columns"],
    },
    {
        "op": "cast",
        "label": "类型转换",
        "category": "feature",
        "desc": "转为数值或字符串",
        "fields": "multi",
        "ui": ["columns", "to"],
    },
    {
        "op": "label_encode",
        "label": "类别编码",
        "category": "encode",
        "desc": "LabelEncoder 离散特征转整数（参考 Rossmann）",
        "fields": "multi",
        "ui": ["columns", "auto_mode"],
    },
    {
        "op": "scale",
        "label": "数值标准化",
        "category": "normalize",
        "desc": "StandardScaler / MinMax（参考 Rossmann）",
        "fields": "multi",
        "ui": ["columns", "method", "auto_mode"],
    },
    {
        "op": "log1p",
        "label": "对数变换 log1p",
        "category": "normalize",
        "desc": "对目标或偏态数值做 log(1+x)，常用于 Sales",
        "fields": "multi",
        "ui": ["columns"],
    },
]

CATEGORY_LABELS = {
    "clean": "清洗",
    "feature": "特征工程",
    "encode": "编码",
    "normalize": "归一化",
}


class CleanEngine:
    def __init__(self):
        self.fill_values = {}
        self.encoders = {}
        self.scaler = None
        self.scale_cols = []
        self.logs = []

    def has_preprocess(self):
        return bool(self.encoders or self.scaler is not None or self.fill_values)

    def log(self, msg):
        self.logs.append(msg)

    def fit_transform(self, df: pd.DataFrame, steps):
        out = df.copy()
        for step in steps or []:
            out = self._apply(out, step, fit=True)
        return out

    def transform(self, df: pd.DataFrame, steps):
        out = df.copy()
        ran = False
        for step in steps or []:
            if step.get("op") in SCORE_SKIP_OPS:
                self.log(f"预测跳过会丢行的步骤: {step.get('op')}")
                continue
            out = self._apply(out, step, fit=False)
            ran = True
        # 旧产物可能只存了 encoder/scaler、没有 steps：仍按训练冻结的列变换
        if not ran and self.has_preprocess():
            out = self._apply_fitted_preprocess(out)
        return out

    def _apply_fitted_preprocess(self, df):
        if self.encoders:
            df = self.op_label_encode(df, {"auto_mode": True}, fit=False)
        if self.scaler is not None:
            df = self.op_scale(df, {"auto_mode": True, "method": "standard"}, fit=False)
        return df

    def _apply(self, df, step, fit=True):
        op = step.get("op")
        if hasattr(self, f"op_{op}"):
            return getattr(self, f"op_{op}")(df, step, fit)
        self.log(f"未知规则 {op}，已跳过")
        return df

    def _coerce_compare_value(self, series, value):
        if value is None or value == "":
            return value
        if pd.api.types.is_numeric_dtype(series):
            try:
                return float(value)
            except Exception:
                return value
        return value

    def op_filter(self, df, step, fit):
        col = step.get("column")
        if col not in df.columns:
            if step.get("skip_if_missing", True):
                self.log(f"过滤跳过：列 {col} 不存在")
                return df
            raise ValueError(f"过滤列不存在: {col}")
        op = step.get("operator", ">")
        value = step.get("value")
        series = df[col]
        value = self._coerce_compare_value(series, value)
        if op == ">":
            mask = series > value
        elif op == ">=":
            mask = series >= value
        elif op == "<":
            mask = series < value
        elif op == "<=":
            mask = series <= value
        elif op == "==":
            mask = series.astype(str) == str(value)
        elif op == "!=":
            mask = series.astype(str) != str(value)
        elif op == "notnull":
            mask = series.notna()
        else:
            return df
        before = len(df)
        df = df.loc[mask].copy()
        self.log(f"过滤 {col} {op} {value}: {before} -> {len(df)}")
        return df

    def op_drop_duplicates(self, df, step, fit):
        cols = step.get("columns") or None
        if cols == []:
            cols = None
        if cols:
            cols = [c for c in cols if c in df.columns]
            if not cols:
                self.log("去重跳过：指定列不存在")
                return df
        before = len(df)
        df = df.drop_duplicates(subset=cols)
        self.log(f"去重: {before} -> {len(df)}")
        return df

    def op_drop_null_rows(self, df, step, fit):
        cols = step.get("columns") or None
        if cols == []:
            cols = None
        if cols:
            cols = [c for c in cols if c in df.columns]
            if not cols:
                self.log("删除空值行跳过：指定列不存在")
                return df
        before = len(df)
        df = df.dropna(subset=cols)
        self.log(f"删除空值行: {before} -> {len(df)}")
        return df

    def _parse_column_strategies(self, step):
        raw = step.get("column_strategies") or {}
        values = dict(step.get("column_values") or {})
        mapped = {}
        if isinstance(raw, list):
            for row in raw:
                if not isinstance(row, dict):
                    continue
                col = row.get("column")
                if not col:
                    continue
                mapped[col] = row.get("strategy") or "auto"
                if row.get("strategy") == "constant" and "value" in row:
                    values[col] = row.get("value")
        elif isinstance(raw, dict):
            mapped = {str(k): v for k, v in raw.items()}
        return mapped, values

    def _compute_fill_value(self, series, strategy, constant=None):
        if strategy == "mean" and pd.api.types.is_numeric_dtype(series):
            return series.mean()
        if strategy == "median" and pd.api.types.is_numeric_dtype(series):
            return series.median()
        if strategy == "mode":
            vc = series.dropna().astype(str).value_counts()
            return vc.index[0] if len(vc) else ""
        if strategy == "constant":
            return 0 if constant is None else constant
        if strategy == "zero":
            return 0
        if pd.api.types.is_numeric_dtype(series):
            return series.mean()
        vc = series.dropna().astype(str).value_counts()
        return vc.index[0] if len(vc) else ""

    def op_fill_missing(self, df, step, fit):
        default = step.get("strategy", "auto")
        overrides, col_values = self._parse_column_strategies(step)
        cols = step.get("columns") or list(df.columns)
        used = []
        for col in cols:
            if col not in df.columns:
                continue
            strategy = overrides.get(col) or default
            if fit:
                self.fill_values[col] = self._compute_fill_value(
                    df[col], strategy, col_values.get(col, step.get("value", 0))
                )
            if col in self.fill_values:
                df[col] = df[col].fillna(self.fill_values[col])
                used.append(f"{col}:{strategy}")
        self.log(f"已填充缺失值 default={default} " + (", ".join(used[:12]) if used else f"cols={len(cols)}"))
        return df

    def op_clip_outlier(self, df, step, fit):
        groups = step.get("ranges")
        if not isinstance(groups, list) or not groups:
            cols = step.get("columns") or [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
            groups = [{
                "columns": cols,
                "method": step.get("method", "iqr"),
                "low": step.get("low"),
                "high": step.get("high"),
            }]
        used = []
        for group in groups:
            method = group.get("method") or step.get("method", "iqr")
            cols = group.get("columns") or []
            for col in cols:
                if col not in df.columns or not pd.api.types.is_numeric_dtype(df[col]):
                    continue
                if method == "range":
                    low_raw = group.get("low")
                    if low_raw is None:
                        low_raw = step.get("low", 0)
                    high_raw = group.get("high")
                    if high_raw is None:
                        high_raw = step.get("high")
                    low = float(0 if low_raw is None else low_raw)
                    high = float(1e9 if high_raw is None else high_raw)
                elif not fit:
                    # 分位数/IQR 边界只在训练 fit 时有意义，预测不再按当前批次重算
                    continue
                elif method == "quantile":
                    low = df[col].quantile(float(group.get("low", 0.01) or 0.01))
                    high = df[col].quantile(float(group.get("high", 0.99) or 0.99))
                else:
                    q1, q3 = df[col].quantile(0.25), df[col].quantile(0.75)
                    iqr = q3 - q1
                    low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
                df[col] = df[col].clip(low, high)
                used.append(col)
        self.log("已裁剪异常值 " + (", ".join(used[:16]) if used else ""))
        return df

    def op_parse_date(self, df, step, fit):
        col = step.get("column", "Date")
        if col not in df.columns:
            if step.get("skip_if_missing", True):
                self.log(f"日期拆解跳过：列 {col} 不存在")
                return df
            raise ValueError(f"日期列不存在: {col}")
        dt = pd.to_datetime(df[col], errors="coerce")
        extract = step.get("extract")
        if extract is None:
            extract = ["year", "month", "day", "weekday", "hour", "minute", "second"]
        mapping = {
            "year": dt.dt.year,
            "month": dt.dt.month,
            "day": dt.dt.day,
            "hour": dt.dt.hour,
            "minute": dt.dt.minute,
            "second": dt.dt.second,
            "weekday": dt.dt.dayofweek + 1,
            "week": dt.dt.isocalendar().week.astype(float),
            "quarter": dt.dt.quarter,
        }
        for name in extract:
            if name in mapping:
                df[name] = mapping[name]
        self.log(f"已从 {col} 拆解 {extract}")
        return df

    def op_split_flags(self, df, step, fit):
        col = step.get("column")
        if col not in df.columns:
            if step.get("skip_if_missing", True):
                self.log(f"文本打标跳过：列 {col} 不存在")
                return df
            raise ValueError(f"打标列不存在: {col}")
        tokens = step.get("tokens") or []
        if isinstance(tokens, str):
            tokens = [t.strip() for t in tokens.replace("，", ",").split(",") if t.strip()]
        prefix = step.get("prefix") or col.lower()
        text = df[col].fillna("").astype(str)
        for tok in tokens:
            df[f"{prefix}{tok.lower()}"] = text.apply(lambda x, t=tok: 1 if t in x else 0)
        self.log(f"已将 {col} 拆为 {len(tokens)} 个标记列")
        return df

    def op_drop_columns(self, df, step, fit):
        cols = [c for c in (step.get("columns") or []) if c in df.columns]
        if cols:
            df = df.drop(columns=cols)
            self.log(f"已删除列 {cols}")
        return df

    def op_cast(self, df, step, fit):
        to = step.get("to", "numeric")
        for col in step.get("columns") or []:
            if col not in df.columns:
                continue
            if to == "numeric":
                df[col] = pd.to_numeric(df[col], errors="coerce")
            else:
                df[col] = df[col].astype(str)
        return df

    def _auto_categorical(self, df):
        cols = []
        for c in df.columns:
            if pd.api.types.is_numeric_dtype(df[c]):
                continue
            cols.append(c)
        return cols

    def _auto_numeric(self, df, exclude=None):
        exclude = set(exclude or []) | _scale_label_exclude()
        return [c for c in df.columns if c not in exclude and pd.api.types.is_numeric_dtype(df[c])]

    def _is_auto_encode(self, step):
        cols = step.get("columns")
        return bool(step.get("auto_mode") or cols in (None, [], "auto_categorical"))

    def _is_auto_scale(self, step):
        cols = step.get("columns")
        return bool(step.get("auto_mode") or cols in (None, [], "auto_numeric"))

    def op_label_encode(self, df, step, fit):
        auto = self._is_auto_encode(step)
        if not fit:
            # 预测用训练时冻结的列，避免手填少列时自动模式扫不到
            cols = list(self.encoders.keys()) if auto else list(step.get("columns") or [])
        elif auto:
            cols = self._auto_categorical(df)
        else:
            cols = list(step.get("columns") or [])
        for col in cols:
            if col not in df.columns:
                continue
            series = df[col].astype(str)
            if fit:
                le = LabelEncoder()
                df[col] = le.fit_transform(series)
                self.encoders[col] = le
            else:
                le = self.encoders.get(col)
                if not le:
                    continue
                known = set(le.classes_)
                mapped = series.apply(lambda x: x if x in known else le.classes_[0])
                df[col] = le.transform(mapped)
        self.log(f"类别编码: {cols}")
        return df

    def op_scale(self, df, step, fit):
        method = step.get("method", "standard")
        step_exclude = set(step.get("exclude") or [])
        if not fit:
            if self.scaler is None:
                return df
            use = [c for c in (self.scale_cols or []) if c not in step_exclude]
            if not use:
                return df
            aligned = pd.DataFrame(index=df.index)
            for c in use:
                if c in df.columns:
                    aligned[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
                else:
                    aligned[c] = 0.0
            transformed = self.scaler.transform(aligned[use].astype(float).fillna(0))
            for i, c in enumerate(use):
                df[c] = transformed[:, i]
            self.log(f"已标准化({method}) {len(use)} 列（训练冻结）")
            return df
        exclude = step_exclude | _scale_label_exclude()
        auto = self._is_auto_scale(step)
        if auto:
            cols = self._auto_numeric(df, exclude)
        else:
            cols = list(step.get("columns") or [])
        cols = [c for c in cols if c in df.columns and c not in exclude and pd.api.types.is_numeric_dtype(df[c])]
        if not cols:
            return df
        values = df[cols].astype(float).replace([np.inf, -np.inf], np.nan).fillna(0)
        self.scaler = StandardScaler() if method != "minmax" else MinMaxScaler()
        self.scale_cols = cols
        df[cols] = self.scaler.fit_transform(values)
        self.log(f"已标准化({method}) {len(cols)} 列")
        return df

    def op_log1p(self, df, step, fit):
        cols = step.get("columns") or []
        done = []
        for col in cols:
            if col not in df.columns:
                continue
            s = pd.to_numeric(df[col], errors="coerce").clip(lower=0)
            df[col] = np.log1p(s)
            done.append(col)
        self.log(f"log1p: {done}")
        return df

    def state(self):
        return {
            "fill_values": self.fill_values,
            "encoders": self.encoders,
            "scaler": self.scaler,
            "scale_cols": self.scale_cols,
            "logs": self.logs,
        }

    def load_state(self, state):
        self.fill_values = state.get("fill_values") or {}
        self.encoders = state.get("encoders") or {}
        self.scaler = state.get("scaler")
        self.scale_cols = state.get("scale_cols") or []
        self.logs = state.get("logs") or []

    def inverse_scaled(self, df):
        """把当前 scaler 覆盖的列还原成拟合前的量纲。"""
        if self.scaler is None or not self.scale_cols or df is None:
            return df
        use = list(self.scale_cols)
        aligned = pd.DataFrame(index=df.index)
        for c in use:
            if c in df.columns:
                aligned[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
            else:
                aligned[c] = 0.0
        inv = self.scaler.inverse_transform(aligned[use].astype(float).fillna(0))
        out = df.copy()
        for i, c in enumerate(use):
            if c in out.columns:
                out[c] = inv[:, i]
        return out

    def restrict_scaler_to_features(self, df, feature_cols, exclude=None):
        """训练时取「清洗标准化列 ∩ DAG 已选特征」，目标列和其他未选列不缩放。"""
        exclude = set(exclude or [])
        method = "minmax" if isinstance(self.scaler, MinMaxScaler) else "standard"
        clean_cols = list(self.scale_cols or [])
        had_scaler = self.scaler is not None and bool(clean_cols)
        if had_scaler:
            df = self.inverse_scaled(df)
        feat_set = set()
        feat_order = []
        for c in feature_cols or []:
            if not c or c in feat_set:
                continue
            feat_set.add(c)
            feat_order.append(c)
        clean_set = set(clean_cols)
        ordered = []
        for c in feat_order:
            if c in exclude or c not in df.columns:
                continue
            if clean_set and c not in clean_set:
                continue
            if not pd.api.types.is_numeric_dtype(df[c]):
                continue
            ordered.append(c)
        if not ordered:
            self.scaler = None
            self.scale_cols = []
            if had_scaler:
                self.log("清洗标准化列与训练特征无交集，已跳过标准化")
            return df
        if not had_scaler:
            return df
        values = df[ordered].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0)
        self.scaler = StandardScaler() if method != "minmax" else MinMaxScaler()
        self.scale_cols = ordered
        out = df.copy()
        out[ordered] = self.scaler.fit_transform(values)
        skipped = [c for c in feat_order if c not in ordered and c not in exclude]
        msg = f"标准化取交集 {len(ordered)} 列（清洗 ∩ 训练特征）"
        if skipped:
            msg += f"；未进入标准化 {len(skipped)} 列"
        self.log(msg)
        return out
