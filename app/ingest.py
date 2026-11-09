"""上传文件解析：识别表头、字段类型、缺失值与数据质量，并落地为 Parquet。"""

from __future__ import annotations

import csv
import re
import shutil
import uuid
from pathlib import Path
from typing import Any, Iterable

import duckdb
import numpy as np
import pandas as pd

from . import db
from .config import ALLOWED_EXTENSIONS, MAX_ROWS, MAX_SHEETS, MAX_UPLOAD_BYTES, UPLOAD_DIR
from .utils import json_safe, quote_ident, safe_float

DATE_HINTS = ("日期", "时间", "年月", "月份", "date", "time", "month", "week", "day")
ID_HINTS = ("id", "uuid", "编号", "序号", "代码", "单号", "条码", "sku", "工号", "手机号", "身份证")
YEAR_HINTS = ("年份", "年度", "year")
PERCENT_HINTS = ("率", "占比", "percent", "ratio")


class IngestError(Exception):
    pass


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and np.isnan(value):
        return True
    return isinstance(value, str) and not value.strip()


def _normalize_columns(columns: Iterable[Any]) -> list[str]:
    names: list[str] = []
    seen: dict[str, int] = {}
    for index, raw in enumerate(columns):
        name = "" if raw is None else str(raw)
        name = re.sub(r"\s+", " ", name.replace("\u3000", " ")).strip()
        name = name.replace("\n", " ").replace("\r", " ")
        if not name or name.lower().startswith("unnamed:"):
            name = f"列{index + 1}"
        if len(name) > 80:
            name = name[:80]
        if name in seen:
            seen[name] += 1
            name = f"{name} ({seen[name]})"
        else:
            seen[name] = 1
        names.append(name)
    return names


def _detect_header_row(raw: pd.DataFrame) -> int:
    """在前 15 行中寻找最像表头的一行。"""
    if raw.empty:
        return 0
    best_row = 0
    best_score = float("-inf")
    for index in range(min(15, len(raw))):
        values = [value for value in raw.iloc[index].tolist() if not _is_blank(value)]
        if len(values) < 2:
            continue
        strings = sum(1 for value in values if isinstance(value, str) and not _looks_numeric(value))
        uniqueness = len({str(value) for value in values}) / len(values)
        used = [i for i, value in enumerate(raw.iloc[index].tolist()) if not _is_blank(value)]
        below = raw.iloc[index + 1 : index + 6, used]
        fill_ratio = float(below.notna().mean().mean()) if below.size else 0.0
        score = (
            len(values) * 0.5
            + strings * 1.4
            + uniqueness * 2.0
            + fill_ratio * 3.0
            - index * 0.2
        )
        if score > best_score:
            best_score = score
            best_row = index
    return best_row


def _looks_numeric(value: str) -> bool:
    cleaned = value.replace(",", "").replace(" ", "").replace("%", "").replace("¥", "").replace("$", "")
    try:
        float(cleaned)
        return True
    except ValueError:
        return False


def _read_csv_sample(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()[:65536]
    encoding = "utf-8-sig"
    for candidate in ("utf-8-sig", "gb18030", "utf-16", "latin1"):
        try:
            text = raw.decode(candidate)
            encoding = candidate
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover
        text = raw.decode("latin1", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
        separator = dialect.delimiter
    except csv.Error:
        separator = ","
    return encoding, separator


def _parse_datetime(series: pd.Series, name: str) -> tuple[pd.Series | None, int]:
    """在类型安全的前提下尝试识别日期列。"""
    non_null = series.dropna()
    if non_null.empty:
        return None, 0
    lowered = name.lower()
    name_hint = any(hint in lowered for hint in DATE_HINTS)
    values = non_null.astype(str).str.strip()
    sample = values.head(300)
    separator_ratio = float(sample.str.contains(r"[-/年月日:T]", regex=True).mean())

    if pd.api.types.is_numeric_dtype(series):
        if not name_hint:
            return None, 0
        # 202401 / 20240115 这类数字型年月，按格式显式解析
        text = non_null.astype("int64", errors="ignore").astype(str)
        for pattern in ("%Y%m%d", "%Y%m", "%Y-%m", "%Y/%m"):
            try:
                parsed = pd.to_datetime(text, format=pattern, errors="coerce")
            except (ValueError, TypeError):
                continue
            if parsed.notna().mean() >= 0.85:
                years = parsed.dropna().dt.year
                if years.between(1990, 2100).all():
                    full = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
                    full.loc[parsed.index] = parsed
                    return full, int(series.notna().sum() - parsed.notna().sum())
        return None, 0

    if not (name_hint or separator_ratio >= 0.6):
        return None, 0
    try:
        parsed = pd.to_datetime(series, errors="coerce", format="mixed")
    except (ValueError, TypeError):
        parsed = pd.to_datetime(series, errors="coerce")
    if parsed.notna().mean() >= 0.85:
        coerced = int(series.notna().sum() - parsed.notna().sum())
        return parsed, max(coerced, 0)
    return None, 0


def _parse_numeric(series: pd.Series, name: str) -> tuple[pd.Series | None, int, bool]:
    non_null = series.dropna()
    if non_null.empty:
        return None, 0, False
    text = non_null.astype(str).str.strip()
    is_percent = bool(text.str.endswith("%").mean() > 0.5) or (
        any(hint in name.lower() for hint in PERCENT_HINTS) and bool(text.str.endswith("%").any())
    )
    cleaned = (
        text.str.replace(",", "", regex=False)
        .str.replace("，", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace("¥", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.replace("€", "", regex=False)
        .str.replace("£", "", regex=False)
        .str.replace("%", "", regex=False)
        .str.replace(r"^\((.*)\)$", r"-\1", regex=True)
    )
    converted = pd.to_numeric(cleaned, errors="coerce")
    if converted.notna().mean() >= 0.85:
        if is_percent:
            converted = converted / 100.0
        full = pd.Series(np.nan, index=series.index, dtype="float64")
        full.loc[converted.index] = converted
        coerced = int(series.notna().sum() - converted.notna().sum())
        return full, max(coerced, 0), is_percent
    return None, 0, False


def _column_role(name: str, dtype: str) -> str:
    lowered = name.lower()
    if dtype == "datetime":
        return "time"
    if any(hint in lowered for hint in ID_HINTS):
        return "id"
    if dtype == "number":
        return "metric"
    if any(hint in lowered for hint in YEAR_HINTS):
        return "dimension"
    if dtype == "category":
        return "dimension"
    return "text"


def _infer_column(series: pd.Series, name: str, row_count: int) -> tuple[pd.Series, dict]:
    original_missing = int(series.isna().sum())
    dtype = "text"
    converted: pd.Series = series
    coerced = 0
    is_percent = False

    if pd.api.types.is_datetime64_any_dtype(series):
        dtype = "datetime"
        converted = pd.to_datetime(series, errors="coerce")
    elif pd.api.types.is_bool_dtype(series):
        dtype = "category"
        converted = series.astype("string")
    elif pd.api.types.is_numeric_dtype(series):
        dtype = "number"
        converted = pd.to_numeric(series, errors="coerce").astype("float64")
    else:
        parsed_time, time_coerced = _parse_datetime(series, name)
        if parsed_time is not None:
            dtype = "datetime"
            converted = parsed_time
            coerced = time_coerced
        else:
            parsed_number, num_coerced, percent = _parse_numeric(series, name)
            if parsed_number is not None:
                dtype = "number"
                converted = parsed_number
                coerced = num_coerced
                is_percent = percent
            else:
                converted = series.astype("string")
                non_null = converted.dropna()
                unique = int(non_null.nunique())
                threshold = min(50, max(2, int(row_count * 0.05)))
                dtype = "category" if unique <= threshold or unique <= 20 else "text"

    missing = int(converted.isna().sum())
    non_null = converted.dropna()
    unique = int(non_null.nunique())

    info: dict[str, Any] = {
        "name": name,
        "dtype": dtype,
        "role": _column_role(name, dtype),
        "missing": missing,
        "missing_ratio": round(missing / row_count, 4) if row_count else 0,
        "coerced": coerced,
        "unique": unique,
        "is_percent": is_percent,
        "sample": [json_safe(value) for value in non_null.head(3).tolist()],
    }

    if dtype == "number":
        values = non_null.astype("float64")
        info.update(
            {
                "min": safe_float(values.min()),
                "max": safe_float(values.max()),
                "mean": safe_float(values.mean()),
                "median": safe_float(values.median()),
                "sum": safe_float(values.sum()),
            }
        )
    elif dtype == "datetime":
        info.update({"min": json_safe(non_null.min()), "max": json_safe(non_null.max())})
    else:
        counts = non_null.astype(str).value_counts().head(5)
        info["top_values"] = [
            {"value": str(key), "count": int(value)} for key, value in counts.items()
        ]

    return converted, info


def _column_warnings(info: dict, row_count: int) -> list[dict]:
    warnings: list[dict] = []
    name = info["name"]
    if info["missing"] > 0:
        ratio = info["missing"] / max(row_count, 1)
        level = "warning" if ratio >= 0.2 else "info"
        warnings.append(
            {
                "level": level,
                "message": f"字段「{name}」缺失 {info['missing']:,} 行（{ratio * 100:.1f}%）。",
            }
        )
    if info.get("coerced", 0) > 0:
        warnings.append(
            {
                "level": "warning",
                "message": f"字段「{name}」有 {info['coerced']:,} 个值无法按{('日期' if info['dtype'] == 'datetime' else '数值')}解析，已置空。",
            }
        )
    if info["unique"] == 1 and row_count > 1:
        warnings.append({"level": "info", "message": f"字段「{name}」只有 1 个取值，分析价值有限。"})
    return warnings


def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.register("sheet_df", df)
        con.execute(
            f"COPY (SELECT * FROM sheet_df) TO '{path.as_posix().replace(chr(39), chr(39) * 2)}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    finally:
        con.close()


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    for column in frame.columns:
        series = frame[column]
        if pd.api.types.is_datetime64_any_dtype(series):
            continue
        if pd.api.types.is_numeric_dtype(series):
            frame[column] = pd.to_numeric(series, errors="coerce").astype("float64")
        else:
            frame[column] = series.astype("string").astype(object).where(series.notna(), None)
    return frame


def _parse_sheet(
    frame: pd.DataFrame,
    sheet_name: str,
    position: int,
    header_row: int,
    folder: Path,
) -> dict | None:
    if frame is None or frame.empty:
        return None

    frame = frame.dropna(axis=0, how="all")
    unnamed = [
        column
        for column in frame.columns
        if str(column).lower().startswith("unnamed:") and frame[column].isna().all()
    ]
    if unnamed:
        frame = frame.drop(columns=unnamed)
    frame = frame.dropna(axis=1, how="all")
    if frame.empty or frame.shape[1] == 0:
        return None

    if frame.shape[1] > 200:
        frame = frame.iloc[:, :200]

    if len(frame) > MAX_ROWS:
        raise IngestError(
            f"工作表「{sheet_name}」有 {len(frame):,} 行，超过 {MAX_ROWS:,} 行上限，请先聚合或抽样后再上传。"
        )

    frame = frame.reset_index(drop=True)
    frame.columns = _normalize_columns(frame.columns)
    row_count = len(frame)

    converted_columns: dict[str, pd.Series] = {}
    columns_meta: list[dict] = []
    quality: list[dict] = []
    for column in frame.columns:
        converted, info = _infer_column(frame[column], column, row_count)
        converted_columns[column] = converted
        columns_meta.append(info)
        quality.extend(_column_warnings(info, row_count))

    clean = pd.DataFrame(converted_columns, index=frame.index)
    clean = _prepare_frame(clean)

    duplicate_rows = int(clean.duplicated().sum())
    if duplicate_rows > 0:
        quality.append(
            {
                "level": "info" if duplicate_rows / max(row_count, 1) < 0.05 else "warning",
                "message": f"检测到 {duplicate_rows:,} 行完全重复的数据。",
            }
        )
    if row_count > 100_000:
        quality.append(
            {
                "level": "warning",
                "message": f"工作表共 {row_count:,} 行，超过建议的 10 万行；分析会按全量聚合执行，建议必要时先抽样。",
            }
        )
    if header_row > 0:
        quality.append(
            {
                "level": "info",
                "message": f"已跳过表头上方的 {header_row} 行说明文字（表头位于第 {header_row + 1} 行）。",
            }
        )

    sheet_id = f"sh_{uuid.uuid4().hex[:20]}"
    parquet_path = folder / f"{position}.parquet"
    _write_parquet(clean, parquet_path)

    date_columns = [c for c in columns_meta if c["dtype"] == "datetime"]
    if len(date_columns) > 1:
        quality.append(
            {
                "level": "info",
                "message": "检测到多个日期字段：" + "、".join(c["name"] for c in date_columns) + "。",
            }
        )

    return {
        "id": sheet_id,
        "name": sheet_name,
        "position": position,
        "header_row": header_row,
        "row_count": row_count,
        "col_count": int(clean.shape[1]),
        "columns": columns_meta,
        "quality": quality,
        "parquet_path": str(parquet_path),
    }


def ingest_file(
    temp_path: Path,
    original_name: str,
    session_id: str,
    size_bytes: int,
) -> dict:
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise IngestError("仅支持 .xlsx / .xls / .csv 文件。")
    if size_bytes > MAX_UPLOAD_BYTES:
        raise IngestError(f"文件超过 {MAX_UPLOAD_BYTES // 1024 // 1024}MB 上限。")

    file_id = f"fl_{uuid.uuid4().hex[:20]}"
    folder = UPLOAD_DIR / file_id
    folder.mkdir(parents=True, exist_ok=True)
    stored_name = f"{file_id}{extension}"
    stored_path = folder / stored_name
    shutil.move(str(temp_path), stored_path)

    try:
        sheets: list[dict] = []
        if extension == ".csv":
            sheets = _parse_csv(stored_path, folder)
        else:
            sheets = _parse_excel(stored_path, extension, folder)
        if not sheets:
            raise IngestError("文件中没有可解析的数据表，请检查表头与内容。")
    except IngestError:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    except Exception as exc:  # pragma: no cover - 防御性提示
        shutil.rmtree(folder, ignore_errors=True)
        raise IngestError(f"文件解析失败：{exc}") from exc

    total_rows = sum(sheet["row_count"] for sheet in sheets)
    quality: list[dict] = []
    for sheet in sheets:
        for item in sheet["quality"]:
            if len(sheets) > 1:
                message = f"「{sheet['name']}」{item['message']}"
            else:
                message = item["message"]
            quality.append({**item, "message": message})
        quality.append(
            {
                "level": "info",
                "message": f"「{sheet['name']}」共 {sheet['row_count']:,} 行 × {sheet['col_count']} 列。",
            }
        )

    now = db.utc_now()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO files(id, session_id, original_name, stored_name, extension, size_bytes, "
            "row_count, sheet_count, status, quality_json, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                file_id,
                session_id,
                Path(original_name).name,
                stored_name,
                extension,
                size_bytes,
                total_rows,
                len(sheets),
                "ready",
                db.dumps(quality),
                now,
            ),
        )
        for sheet in sheets:
            conn.execute(
                "INSERT INTO sheets(id, file_id, name, position, header_row, row_count, col_count, "
                "columns_json, quality_json, parquet_path, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    sheet["id"],
                    file_id,
                    sheet["name"],
                    sheet["position"],
                    sheet["header_row"],
                    sheet["row_count"],
                    sheet["col_count"],
                    db.dumps(sheet["columns"]),
                    db.dumps(sheet["quality"]),
                    sheet["parquet_path"],
                    now,
                ),
            )

    return {
        "id": file_id,
        "name": Path(original_name).name,
        "extension": extension,
        "size_bytes": size_bytes,
        "row_count": total_rows,
        "sheet_count": len(sheets),
        "status": "ready",
        "quality": quality,
        "created_at": now,
        "sheets": [_public_sheet(sheet) for sheet in sheets],
    }


def _parse_excel(path: Path, extension: str, folder: Path) -> list[dict]:
    engine = "openpyxl" if extension == ".xlsx" else "xlrd"
    excel = pd.ExcelFile(path, engine=engine)
    sheets: list[dict] = []
    for position, sheet_name in enumerate(excel.sheet_names[:MAX_SHEETS]):
        raw = excel.parse(sheet_name, header=None, nrows=15)
        if raw.empty:
            continue
        header_row = _detect_header_row(raw)
        frame = excel.parse(sheet_name, header=header_row)
        parsed = _parse_sheet(frame, sheet_name, position, header_row, folder)
        if parsed:
            sheets.append(parsed)
    return sheets


def _parse_csv(path: Path, folder: Path) -> list[dict]:
    encoding, separator = _read_csv_sample(path)
    raw = pd.read_csv(
        path, encoding=encoding, sep=separator, header=None, nrows=15, dtype=object
    )
    if raw.empty:
        raise IngestError("CSV 文件为空。")
    header_row = _detect_header_row(raw)
    frame = pd.read_csv(path, encoding=encoding, sep=separator, header=header_row, low_memory=False)
    parsed = _parse_sheet(frame, "数据", 0, header_row, folder)
    return [parsed] if parsed else []


def _public_sheet(sheet: dict) -> dict:
    return {
        "id": sheet["id"],
        "name": sheet["name"],
        "row_count": sheet["row_count"],
        "col_count": sheet["col_count"],
        "columns": sheet.get("columns", []),
        "quality": sheet.get("quality", []),
    }


def get_file(session_id: str, file_id: str) -> dict | None:
    row = db.query_one("SELECT * FROM files WHERE id=? AND session_id=?", (file_id, session_id))
    if row is None:
        return None
    file = dict(row)
    file["name"] = Path(file["original_name"]).name
    sheets = db.query_all("SELECT * FROM sheets WHERE file_id=? ORDER BY position", (file_id,))
    file["quality"] = db.loads(file.pop("quality_json"), [])
    file["sheets"] = [
        {
            "id": sheet["id"],
            "name": sheet["name"],
            "row_count": sheet["row_count"],
            "col_count": sheet["col_count"],
            "columns": db.loads(sheet["columns_json"], []),
            "quality": db.loads(sheet["quality_json"], []),
        }
        for sheet in sheets
    ]
    return file


def list_files(session_id: str) -> list[dict]:
    rows = db.query_all(
        "SELECT id, original_name, extension, size_bytes, row_count, sheet_count, status, created_at "
        "FROM files WHERE session_id=? ORDER BY created_at DESC",
        (session_id,),
    )
    return [
        {
            "id": row["id"],
            "name": row["original_name"],
            "extension": row["extension"],
            "size_bytes": row["size_bytes"],
            "row_count": row["row_count"],
            "sheet_count": row["sheet_count"],
            "status": row["status"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def get_sheet(file_id: str, sheet_id: str) -> dict | None:
    row = db.query_one("SELECT * FROM sheets WHERE id=? AND file_id=?", (sheet_id, file_id))
    if row is None:
        return None
    sheet = dict(row)
    sheet["columns"] = db.loads(sheet.pop("columns_json"), [])
    sheet["quality"] = db.loads(sheet.pop("quality_json"), [])
    return sheet


def preview_sheet(sheet: dict, limit: int = 20) -> dict:
    path = sheet.get("parquet_path")
    if not path or not Path(path).exists():
        return {"columns": [], "rows": [], "total": 0}
    con = duckdb.connect()
    try:
        cursor = con.execute(
            f"SELECT * FROM read_parquet('{Path(path).as_posix().replace(chr(39), chr(39) * 2)}') LIMIT ?",
            [limit],
        )
        columns = [item[0] for item in cursor.description]
        rows = cursor.fetchall()
    finally:
        con.close()
    column_meta = {column["name"]: column for column in sheet["columns"]}
    return {
        "columns": [
            {
                "name": name,
                "dtype": column_meta.get(name, {}).get("dtype", "text"),
                "is_percent": column_meta.get(name, {}).get("is_percent", False),
            }
            for name in columns
        ],
        "rows": [[json_safe(value) for value in row] for row in rows],
        "total": sheet["row_count"],
    }


def delete_file(session_id: str, file_id: str) -> bool:
    row = db.query_one("SELECT id FROM files WHERE id=? AND session_id=?", (file_id, session_id))
    if row is None:
        return False
    db.execute("DELETE FROM files WHERE id=?", (file_id,))
    shutil.rmtree(UPLOAD_DIR / file_id, ignore_errors=True)
    return True


def clear_session(session_id: str) -> None:
    rows = db.query_all("SELECT id FROM files WHERE session_id=?", (session_id,))
    for row in rows:
        shutil.rmtree(UPLOAD_DIR / row["id"], ignore_errors=True)
    with db.connect() as conn:
        conn.execute("DELETE FROM analyses WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM files WHERE session_id=?", (session_id,))
