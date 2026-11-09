"""应用配置：全部通过环境变量注入，API Key 不会出现在前端。"""

from __future__ import annotations

import os
from pathlib import Path

try:  # 本地开发可选加载 .env；容器中直接使用环境变量
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # pragma: no cover
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data"))).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = Path(os.getenv("SQLITE_PATH", str(DATA_DIR / "analyst.db"))).resolve()

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
MAX_ROWS = int(os.getenv("MAX_ROWS", "200000"))
MAX_SHEETS = int(os.getenv("MAX_SHEETS", "20"))

ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}

# OpenAI 兼容接口
LLM_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
LLM_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
LLM_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "40"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1200"))
APP_VERSION = "0.10.2"


def llm_configured() -> bool:
    return bool(LLM_API_KEY and LLM_BASE_URL and LLM_MODEL)


def public_settings() -> dict:
    host = ""
    try:
        from urllib.parse import urlparse

        host = urlparse(LLM_BASE_URL).netloc or "自定义端点"
    except Exception:  # pragma: no cover
        host = "自定义端点"
    return {
        "app_version": APP_VERSION,
        "ai_configured": llm_configured(),
        "model": LLM_MODEL if llm_configured() else None,
        "endpoint_host": host if llm_configured() else None,
        "max_upload_mb": MAX_UPLOAD_MB,
        "max_rows": MAX_ROWS,
        "storage_dir": str(DATA_DIR),
        "privacy": "文件、解析结果与分析历史仅保存在本机 data 目录；除结论生成外，不会向外部发送原始数据。",
    }
