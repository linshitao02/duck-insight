# -*- coding: utf-8 -*-
import os
from io import BytesIO

import pandas as pd

from config import ALLOWED_DATA_EXTENSIONS


def read_table(path_or_file, filename=None, sheet_name=0, nrows=None):
    name = filename or (getattr(path_or_file, "filename", None)) or str(path_or_file)
    ext = os.path.splitext(name)[1].lower().lstrip(".")
    if ext not in ALLOWED_DATA_EXTENSIONS:
        raise ValueError(f"不支持的文件格式: {ext}")

    if hasattr(path_or_file, "read"):
        data = path_or_file.read()
        if hasattr(path_or_file, "seek"):
            try:
                path_or_file.seek(0)
            except Exception:
                pass
        buffer = BytesIO(data)
        source = buffer
    else:
        source = path_or_file

    if ext in ("xlsx", "xls"):
        engine = "openpyxl" if ext == "xlsx" else None
        return pd.read_excel(source, sheet_name=sheet_name, nrows=nrows, engine=engine)

    encodings = ["utf-8-sig", "utf-8", "gbk", "gb18030", "latin1"]
    seps = [",", "\t", ";", "|"]
    last_err = None
    for enc in encodings:
        for sep in seps:
            try:
                df = pd.read_csv(source, sep=sep, encoding=enc, nrows=nrows, engine="python")
                if hasattr(source, "seek"):
                    source.seek(0)
                if df.shape[1] == 1 and sep != "\t":
                    # 可能分隔符不对，继续尝试
                    if ext == "txt" and sep == ",":
                        continue
                return df
            except Exception as e:
                last_err = e
                if hasattr(source, "seek"):
                    source.seek(0)
                continue
    raise ValueError(f"无法解析文件: {last_err}")


def excel_sheet_names(path_or_file):
    try:
        xl = pd.ExcelFile(path_or_file)
        return xl.sheet_names
    except Exception:
        return []


def save_dataframe(df, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ext = os.path.splitext(path)[1].lower()
    if ext == ".parquet":
        try:
            df.to_parquet(path, index=False)
            return path
        except Exception:
            path = os.path.splitext(path)[0] + ".csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def load_dataframe(path, nrows=None):
    if not path or not os.path.exists(path):
        raise FileNotFoundError("数据文件不存在")
    ext = os.path.splitext(path)[1].lower()
    if ext == ".parquet":
        return pd.read_parquet(path)
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path, nrows=nrows)
    return pd.read_csv(path, nrows=nrows, encoding="utf-8-sig")
