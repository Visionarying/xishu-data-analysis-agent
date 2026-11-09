"""通用工具：JSON 安全化、数值展示、SQL 标识符转义。"""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd


def json_safe(value: Any) -> Any:
    """把 pandas / numpy / 日期对象转换为可 JSON 序列化的值。"""
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        if pd.isna(value):
            return None
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    if pd.isna(value):
        return None
    return str(value)


def fmt_number(value: float | int | None, digits: int = 2) -> str:
    """按中文习惯格式化数字：万 / 亿，并保留有效精度。"""
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "—"
    absolute = abs(number)
    if absolute >= 1e8:
        return f"{number / 1e8:,.{digits}f} 亿"
    if absolute >= 1e4:
        return f"{number / 1e4:,.{digits}f} 万"
    if absolute >= 100:
        return f"{number:,.{digits - 1 if digits > 1 else digits}f}"
    if absolute >= 1:
        return f"{number:,.{digits}f}"
    if absolute == 0:
        return "0"
    return f"{number:.4f}"


def fmt_percent(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def quote_ident(name: str) -> str:
    """DuckDB 标识符转义，字段名只能来自已校验的元数据。"""
    return '"' + name.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def compact_text(text: str, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def extract_numbers(text: str) -> set[str]:
    """提取文本中的数字 token，用于核对模型结论是否引入了新数字。"""
    numbers: set[str] = set()
    for match in re.findall(r"-?\d+(?:,\d{3})*(?:\.\d+)?", text or ""):
        token = match.replace(",", "")
        if token.startswith("-"):
            continue
        try:
            number = float(token)
        except ValueError:
            continue
        numbers.add(_normalize_number(number))
    return numbers


def _normalize_number(number: float) -> str:
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return f"{number:.6f}".rstrip("0").rstrip(".")
