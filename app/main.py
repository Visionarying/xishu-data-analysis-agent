"""FastAPI 入口：上传、预览、分析、历史、导出与静态页面。"""

from __future__ import annotations

import csv
import io
import logging
import re
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.base import BaseHTTPMiddleware

from . import analyzer, db, ingest, narrative, notes, planner, report
from .config import (
    APP_VERSION,
    DATA_DIR,
    DB_PATH,
    MAX_SHEETS,
    MAX_UPLOAD_BYTES,
    MAX_UPLOAD_MB,
    UPLOAD_DIR,
    WEB_DIR,
    llm_configured,
    public_settings,
)
from .ingest import IngestError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

SESSION_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    db.init_db()
    logger.info("Data Analyst ready · data=%s · ai=%s", DATA_DIR, llm_configured())
    yield


app = FastAPI(title="数据分析 Agent", version=APP_VERSION, lifespan=lifespan, docs_url="/api/docs", redoc_url=None)


class SessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        session_id = request.headers.get("x-session-id", "")
        if not SESSION_PATTERN.match(session_id):
            session_id = "sess_" + uuid.uuid4().hex[:24]
        request.state.session_id = session_id
        if request.url.path.startswith("/api/"):
            db.ensure_session(session_id)
        response = await call_next(request)
        response.headers["X-Session-Id"] = session_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; font-src 'self'; object-src 'none'; "
            "base-uri 'self'; frame-ancestors 'none'",
        )
        if request.url.path in {"/", "/index.html"}:
            response.headers["Cache-Control"] = "no-store"
        return response


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(SessionMiddleware)


def get_session(request: Request) -> str:
    return request.state.session_id


Session = Annotated[str, Depends(get_session)]


class FollowUpContext(BaseModel):
    """上一轮分析的口径，用于追问继承。"""

    question: str | None = Field(None, max_length=500)
    intent: str | None = None
    time_field: str | None = None
    metric_field: str | None = None
    group_field: str | None = None
    aggregation: str | None = None
    granularity: str | None = None
    period_value: int | None = None
    period_unit: str | None = None
    filters: list[dict] = Field(default_factory=list)


class AnalyzeRequest(BaseModel):
    file_id: str = Field(..., min_length=4, max_length=40)
    sheet_id: str | None = Field(None, min_length=4, max_length=40)
    question: str = Field(..., min_length=1, max_length=500)
    context: FollowUpContext | None = None

    @field_validator("question")
    @classmethod
    def clean_question(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("问题不能为空")
        return cleaned


class ColumnNoteRequest(BaseModel):
    note: str = Field("", max_length=notes.NOTE_MAX_LENGTH)


class FavoriteRequest(BaseModel):
    analysis_id: str = Field(..., min_length=4, max_length=40)
    title: str | None = Field(None, max_length=80)


class FavoriteRenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=80)


def _http_error(status: int, message: str, code: str = "error") -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _analysis_summary(row) -> dict:
    return {
        "id": row["id"],
        "question": row["question"],
        "intent": row["intent"],
        "intent_label": planner.INTENT_LABELS.get(row["intent"], "分析"),
        "file_id": row["file_id"],
        "file_name": row["file_name"] if "file_name" in row.keys() else "",
        "sheet_name": row["sheet_name"] if "sheet_name" in row.keys() else "",
        "model_used": row["model_used"],
        "created_at": row["created_at"],
        "status": row["status"],
    }


def _suggested_questions(sheet: dict) -> list[str]:
    columns = sheet.get("columns") or []
    metric = planner._pick_metric(columns, "")
    time_field = planner._pick_time(columns, "")
    group = planner._pick_group(columns, "", metric)
    questions: list[str] = []
    if time_field and metric:
        questions.append(f"近12个月{metric}趋势如何？")
        questions.append(f"找出{metric}异常波动的月份。")
    if group and metric:
        questions.append(f"对比各{group}的{metric}并排名。")
    if metric and group:
        questions.append(f"{group}的{metric}占比分布如何？")
    if not questions:
        questions.append("数据整体情况如何？")
    questions.append("数据整体情况如何？")
    seen: set[str] = set()
    return [question for question in questions if not (question in seen or seen.add(question))][:4]


@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "version": APP_VERSION}


@app.get("/health")
def health_alias():
    return health()


@app.get("/api/settings")
def settings():
    return public_settings()


def _favorite_items(session: str) -> list[dict]:
    rows = db.query_all(
        "SELECT fav.id, fav.analysis_id, fav.question, fav.title, fav.one_liner, fav.file_id, fav.sheet_id, "
        "fav.created_at, fav.updated_at, f.original_name AS file_name, s.name AS sheet_name "
        "FROM favorites fav JOIN files f ON f.id=fav.file_id JOIN sheets s ON s.id=fav.sheet_id "
        "WHERE fav.session_id=? ORDER BY fav.created_at DESC LIMIT 100",
        (session,),
    )
    return [dict(row) for row in rows]


@app.get("/api/bootstrap")
def bootstrap(session: Session):
    files = ingest.list_files(session)
    rows = db.query_all(
        "SELECT a.id, a.question, a.intent, a.file_id, a.model_used, a.created_at, a.status, "
        "f.original_name AS file_name, s.name AS sheet_name "
        "FROM analyses a JOIN files f ON f.id=a.file_id JOIN sheets s ON s.id=a.sheet_id "
        "WHERE a.session_id=? ORDER BY a.created_at DESC LIMIT 50",
        (session,),
    )
    return {
        "session_id": session,
        "files": files,
        "analyses": [_analysis_summary(row) for row in rows],
        "favorites": _favorite_items(session),
        "settings": public_settings(),
        "limits": {"max_upload_mb": MAX_UPLOAD_MB, "max_rows": ingest.MAX_ROWS if hasattr(ingest, "MAX_ROWS") else None},
    }


@app.post("/api/files", status_code=201)
async def upload_file(session: Session, file: UploadFile = File(...)):
    filename = file.filename or "未命名文件"
    extension = Path(filename).suffix.lower()
    if extension not in {".xlsx", ".xls", ".csv"}:
        raise _http_error(415, "仅支持 .xlsx / .xls / .csv 文件。", "unsupported_type")

    temp_dir = DATA_DIR / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(delete=False, dir=temp_dir, suffix=extension)
    temp_path = Path(handle.name)
    size = 0
    try:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                handle.close()
                raise _http_error(413, f"文件超过 {MAX_UPLOAD_MB}MB 上限，请压缩或抽样后再上传。", "too_large")
            handle.write(chunk)
        handle.close()
        if size == 0:
            raise _http_error(400, "文件内容为空。", "empty_file")
        try:
            meta = ingest.ingest_file(temp_path, filename, session, size)
        except IngestError as exc:
            raise _http_error(422, str(exc), "ingest_failed") from exc
    finally:
        await file.close()
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
    return {"file": meta}


@app.get("/api/files")
def list_files(session: Session):
    return {"files": ingest.list_files(session)}


@app.get("/api/files/{file_id}")
def get_file(file_id: str, session: Session):
    file = ingest.get_file(session, file_id)
    if not file:
        raise _http_error(404, "文件不存在或已被删除。", "file_not_found")
    notes.attach_all(file.get("sheets") or [])
    active = file["sheets"][0] if file["sheets"] else None
    return {"file": file, "suggestions": _suggested_questions(active) if active else []}


@app.get("/api/files/{file_id}/sheets/{sheet_id}/preview")
def preview(file_id: str, sheet_id: str, session: Session, limit: int = 20):
    file = ingest.get_file(session, file_id)
    if not file:
        raise _http_error(404, "文件不存在或已被删除。", "file_not_found")
    sheet = ingest.get_sheet(file_id, sheet_id)
    if not sheet:
        raise _http_error(404, "工作表不存在。", "sheet_not_found")
    limit = max(1, min(limit, 100))
    preview = ingest.preview_sheet(sheet, limit=limit)
    notes.attach_notes(sheet)
    return {
        "sheet": {
            "id": sheet["id"],
            "name": sheet["name"],
            "row_count": sheet["row_count"],
            "col_count": sheet["col_count"],
            "columns": sheet["columns"],
            "quality": sheet["quality"],
        },
        "preview": preview,
        "suggestions": _suggested_questions(sheet),
    }


@app.delete("/api/files/{file_id}")
def delete_file(file_id: str, session: Session):
    if not ingest.delete_file(session, file_id):
        raise _http_error(404, "文件不存在或已被删除。", "file_not_found")
    return {"ok": True}


def _run_analysis(
    session: str,
    file_id: str,
    sheet_id: str | None,
    question: str,
    context: dict | None = None,
) -> dict:
    started = time.perf_counter()
    file = ingest.get_file(session, file_id)
    if not file:
        raise _http_error(404, "文件不存在，请先上传数据。", "file_not_found")
    sheets = notes.attach_all(file["sheets"])
    if not sheets:
        raise _http_error(422, "该文件没有可分析的工作表。", "empty_file")

    if sheet_id:
        sheet = next((item for item in sheets if item["id"] == sheet_id), None)
        if not sheet:
            raise _http_error(404, "工作表不存在。", "sheet_not_found")
    else:
        sheet = planner.select_sheet(question, sheets)

    try:
        plan, sheet, plan_warnings = planner.plan_question(question, sheets, sheet["id"], context=context)
        full_sheet = ingest.get_sheet(file["id"], sheet["id"])
        if not full_sheet:
            raise _http_error(404, "工作表数据缺失，请重新上传文件。", "sheet_not_found")
        notes.attach_notes(full_sheet)
        result = analyzer.compute(question, plan, full_sheet)
        method = analyzer.build_methodology(result, sheet, plan)
        conclusion, conclusion_warnings = narrative.build_conclusion(result)
    except analyzer.AnalysisError as exc:
        raise _http_error(422, str(exc), "analysis_failed") from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("Analysis crashed")
        raise _http_error(500, "分析过程出现异常，请重试或换一种问法。", "internal_error") from exc

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    warnings = [*plan_warnings, *result.get("warnings", []), *conclusion_warnings]
    model_used = (
        "本地规则引擎"
        if conclusion.get("source") != "model"
        else (public_settings().get("model") or "大模型")
    )
    if plan.get("mode") == "llm" and conclusion.get("source") != "model":
        model_used = "本地规则引擎（模型辅助规划）"

    analysis_id = f"an_{uuid.uuid4().hex[:20]}"
    now = db.utc_now()
    plan_snapshot = {
        key: plan.get(key)
        for key in (
            "intent",
            "time_field",
            "metric_field",
            "group_field",
            "aggregation",
            "granularity",
            "period_value",
            "period_unit",
            "top_n",
            "filters",
            "follow_up",
        )
    }
    response = {
        "id": analysis_id,
        "question": question,
        "intent": result["intent"],
        "intent_label": result["intent_label"],
        "one_liner": conclusion["one_liner"],
        "metrics": result["metrics"],
        "chart": result["chart"],
        "table": result["table"],
        "detail": {
            "facts": conclusion["facts"],
            "inferences": conclusion["inferences"],
            "suggestions": conclusion["suggestions"],
        },
        "method": method,
        "file": {"id": file["id"], "name": file["original_name"]},
        "sheet": {"id": sheet["id"], "name": sheet["name"], "row_count": sheet["row_count"]},
        "meta": {
            "model_used": model_used,
            "conclusion_source": conclusion.get("source"),
            "ai_enabled": llm_configured(),
            "elapsed_ms": elapsed_ms,
            "warnings": warnings,
            "created_at": now,
            "plan_rationale": plan.get("rationale"),
            "plan_summary": planner.plan_summary(plan, sheet),
            "sql": method.get("sql"),
            "plan": plan_snapshot,
            "follow_up": bool(plan.get("follow_up")),
            "app_version": APP_VERSION,
            "fields_with_notes": [
                {"name": column["name"], "note": column["note"]}
                for column in sheet["columns"]
                if column.get("note")
            ],
        },
        "status": "ok",
    }

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO analyses(id, session_id, file_id, sheet_id, question, intent, plan_json, "
            "sql_text, result_json, status, model_used, elapsed_ms, created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                analysis_id,
                session,
                file["id"],
                sheet["id"],
                question,
                result["intent"],
                db.dumps(plan),
                method.get("sql"),
                db.dumps(response),
                "ok",
                model_used,
                elapsed_ms,
                now,
            ),
        )
    return response


@app.post("/api/analyze")
def analyze(payload: AnalyzeRequest, session: Session):
    context = payload.context.model_dump() if payload.context else None
    return _run_analysis(session, payload.file_id, payload.sheet_id, payload.question, context)


@app.put("/api/files/{file_id}/sheets/{sheet_id}/columns/{column_name}")
def set_column_note(
    file_id: str,
    sheet_id: str,
    column_name: str,
    payload: ColumnNoteRequest,
    session: Session,
):
    file = ingest.get_file(session, file_id)
    if not file:
        raise _http_error(404, "文件不存在或已被删除。", "file_not_found")
    sheet = next((item for item in file["sheets"] if item["id"] == sheet_id), None)
    if not sheet:
        raise _http_error(404, "工作表不存在。", "sheet_not_found")
    if not any(column["name"] == column_name for column in sheet["columns"]):
        raise _http_error(404, "字段不存在。", "column_not_found")
    saved = notes.set_note(sheet_id, column_name, payload.note)
    return {"ok": True, "column": column_name, "note": saved}


@app.get("/api/analyses")
def list_analyses(session: Session, file_id: str | None = None):
    sql = (
        "SELECT a.id, a.question, a.intent, a.file_id, a.model_used, a.created_at, a.status, "
        "f.original_name AS file_name, s.name AS sheet_name "
        "FROM analyses a JOIN files f ON f.id=a.file_id JOIN sheets s ON s.id=a.sheet_id "
        "WHERE a.session_id=?"
    )
    params: list = [session]
    if file_id:
        sql += " AND a.file_id=?"
        params.append(file_id)
    sql += " ORDER BY a.created_at DESC LIMIT 100"
    return {"analyses": [_analysis_summary(row) for row in db.query_all(sql, tuple(params))]}


@app.get("/api/analyses/{analysis_id}")
def get_analysis(analysis_id: str, session: Session):
    row = db.query_one(
        "SELECT * FROM analyses WHERE id=? AND session_id=? AND status='ok'", (analysis_id, session)
    )
    if not row:
        raise _http_error(404, "分析记录不存在。", "analysis_not_found")
    result = db.loads(row["result_json"], None)
    if not result:
        raise _http_error(500, "分析记录损坏。", "analysis_corrupt")
    return result


@app.post("/api/analyses/{analysis_id}/regenerate")
def regenerate(analysis_id: str, session: Session):
    row = db.query_one("SELECT * FROM analyses WHERE id=? AND session_id=?", (analysis_id, session))
    if not row:
        raise _http_error(404, "分析记录不存在。", "analysis_not_found")
    payload = AnalyzeRequest(file_id=row["file_id"], sheet_id=row["sheet_id"], question=row["question"])
    return analyze(payload, session)


@app.delete("/api/analyses/{analysis_id}")
def delete_analysis(analysis_id: str, session: Session):
    row = db.query_one("SELECT id FROM analyses WHERE id=? AND session_id=?", (analysis_id, session))
    if not row:
        raise _http_error(404, "分析记录不存在。", "analysis_not_found")
    db.execute("DELETE FROM analyses WHERE id=?", (analysis_id,))
    return {"ok": True}


@app.get("/api/analyses/{analysis_id}/export.csv")
def export_csv(analysis_id: str, session: Session):
    row = db.query_one(
        "SELECT result_json, question, created_at FROM analyses WHERE id=? AND session_id=?",
        (analysis_id, session),
    )
    if not row:
        raise _http_error(404, "分析记录不存在。", "analysis_not_found")
    result = db.loads(row["result_json"], {})
    table = result.get("table") or {}
    columns = table.get("columns") or []
    rows = table.get("rows") or []
    if not columns:
        raise _http_error(422, "本次分析没有可导出的明细数据。", "no_table")

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([column["label"] for column in columns])
    for item in rows:
        values = []
        for column in columns:
            value = item.get(column["key"])
            if column["type"] == "percent" and value is not None:
                values.append(f"{float(value) * 100:.2f}%")
            elif value is None:
                values.append("")
            else:
                values.append(value)
        writer.writerow(values)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"分析结果_{stamp}.csv"
    headers = {
        "Content-Disposition": f"attachment; filename=\"analysis_{stamp}.csv\"; filename*=UTF-8''{quote(filename)}"
    }
    return Response(
        content=buffer.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


@app.get("/api/favorites")
def list_favorites(session: Session):
    return {"favorites": _favorite_items(session)}


@app.post("/api/favorites", status_code=201)
def add_favorite(payload: FavoriteRequest, session: Session):
    row = db.query_one(
        "SELECT * FROM analyses WHERE id=? AND session_id=? AND status='ok'", (payload.analysis_id, session)
    )
    if not row:
        raise _http_error(404, "分析记录不存在。", "analysis_not_found")
    result = db.loads(row["result_json"], {}) or {}
    favorite_id = f"fv_{uuid.uuid4().hex[:20]}"
    now = db.utc_now()
    title = (payload.title or row["question"]).strip()[:80] or "收藏分析"
    db.execute(
        "INSERT INTO favorites(id, session_id, analysis_id, file_id, sheet_id, question, title, one_liner, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            favorite_id,
            session,
            row["id"],
            row["file_id"],
            row["sheet_id"],
            row["question"],
            title,
            str(result.get("one_liner") or ""),
            now,
            now,
        ),
    )
    return {
        "favorite": {
            "id": favorite_id,
            "analysis_id": row["id"],
            "question": row["question"],
            "title": title,
            "one_liner": str(result.get("one_liner") or ""),
            "file_id": row["file_id"],
            "sheet_id": row["sheet_id"],
            "created_at": now,
            "updated_at": now,
        }
    }


@app.delete("/api/favorites/{favorite_id}")
def delete_favorite(favorite_id: str, session: Session):
    row = db.query_one("SELECT id FROM favorites WHERE id=? AND session_id=?", (favorite_id, session))
    if not row:
        raise _http_error(404, "收藏不存在。", "favorite_not_found")
    db.execute("DELETE FROM favorites WHERE id=?", (favorite_id,))
    return {"ok": True}


@app.patch("/api/favorites/{favorite_id}")
def rename_favorite(favorite_id: str, payload: FavoriteRenameRequest, session: Session):
    row = db.query_one("SELECT id FROM favorites WHERE id=? AND session_id=?", (favorite_id, session))
    if not row:
        raise _http_error(404, "收藏不存在。", "favorite_not_found")
    title = payload.title.strip()[:80]
    if not title:
        raise _http_error(422, "收藏名称不能为空。", "invalid_title")
    db.execute("UPDATE favorites SET title=?, updated_at=? WHERE id=?", (title, db.utc_now(), favorite_id))
    return {"ok": True, "title": title}


@app.post("/api/favorites/{favorite_id}/rerun")
def rerun_favorite(favorite_id: str, session: Session):
    favorite = db.query_one("SELECT * FROM favorites WHERE id=? AND session_id=?", (favorite_id, session))
    if not favorite:
        raise _http_error(404, "收藏不存在。", "favorite_not_found")
    context = None
    if favorite["analysis_id"]:
        origin = db.query_one(
            "SELECT result_json FROM analyses WHERE id=? AND session_id=?",
            (favorite["analysis_id"], session),
        )
        if origin:
            original = db.loads(origin["result_json"], {}) or {}
            context = (original.get("meta") or {}).get("plan")
    response = _run_analysis(session, favorite["file_id"], favorite["sheet_id"], favorite["question"], context)
    db.execute(
        "UPDATE favorites SET analysis_id=?, one_liner=?, updated_at=? WHERE id=?",
        (response["id"], response["one_liner"], db.utc_now(), favorite_id),
    )
    return response


def _analysis_result_or_404(analysis_id: str, session: str) -> dict:
    row = db.query_one(
        "SELECT result_json FROM analyses WHERE id=? AND session_id=? AND status='ok'",
        (analysis_id, session),
    )
    if not row:
        raise _http_error(404, "分析记录不存在。", "analysis_not_found")
    result = db.loads(row["result_json"], None)
    if not result:
        raise _http_error(500, "分析记录损坏。", "analysis_corrupt")
    return result


@app.get("/api/analyses/{analysis_id}/export.md")
def export_markdown(analysis_id: str, session: Session):
    result = _analysis_result_or_404(analysis_id, session)
    text = report.build_markdown(result)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"分析报告_{stamp}.md"
    headers = {
        "Content-Disposition": f"attachment; filename=\"report_{stamp}.md\"; filename*=UTF-8''{quote(filename)}"
    }
    return Response(
        content=text.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers=headers,
    )


@app.get("/api/analyses/{analysis_id}/export.html")
def export_html(analysis_id: str, session: Session):
    result = _analysis_result_or_404(analysis_id, session)
    return Response(
        content=report.build_html(result).encode("utf-8"),
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@app.delete("/api/data")
def clear_data(session: Session):
    ingest.clear_session(session)
    return {"ok": True}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and "message" in detail:
        body = {"error": detail, "status": exc.status_code}
    else:
        body = {"error": {"code": "http_error", "message": str(detail)}, "status": exc.status_code}
    return JSONResponse(status_code=exc.status_code, content=body)


@app.get("/")
def index():
    index_path = WEB_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=500, detail="前端页面缺失")
    return FileResponse(index_path)


if (WEB_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")
if (WEB_DIR.parent / "samples").exists():
    app.mount("/samples", StaticFiles(directory=WEB_DIR.parent / "samples"), name="samples")
