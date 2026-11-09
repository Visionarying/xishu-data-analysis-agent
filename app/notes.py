"""字段备注（轻量语义层）：把用户写的业务含义/口径存进 SQLite，并在规划时参考。"""

from __future__ import annotations

from typing import Any

from . import db

NOTE_MAX_LENGTH = 200


def get_notes(sheet_id: str) -> dict[str, str]:
    rows = db.query_all(
        "SELECT column_name, note FROM column_notes WHERE sheet_id=? ORDER BY column_name",
        (sheet_id,),
    )
    return {row["column_name"]: row["note"] for row in rows}


def set_note(sheet_id: str, column_name: str, note: str) -> str:
    cleaned = (note or "").strip()[:NOTE_MAX_LENGTH]
    if cleaned:
        db.execute(
            "INSERT INTO column_notes(sheet_id, column_name, note, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(sheet_id, column_name) DO UPDATE SET note=excluded.note, updated_at=excluded.updated_at",
            (sheet_id, column_name, cleaned, db.utc_now()),
        )
    else:
        db.execute(
            "DELETE FROM column_notes WHERE sheet_id=? AND column_name=?",
            (sheet_id, column_name),
        )
    return cleaned


def attach_notes(sheet: dict) -> dict:
    """把备注写回字段 dict（不改变表结构），供预览与规划复用。"""
    notes = get_notes(sheet["id"])
    if notes:
        for column in sheet.get("columns") or []:
            note = notes.get(column.get("name", ""))
            if note:
                column["note"] = note
    return sheet


def attach_all(sheets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for sheet in sheets:
        attach_notes(sheet)
    return sheets
