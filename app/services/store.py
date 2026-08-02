"""JSON 파일 저장소 — 보고서 인덱스·본문·레이아웃 오버라이드를 data/ 아래 JSON으로 관리한다."""
from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException

from app import config


def _read_json(path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fallback


def _write_json(path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 보고서 본문 (data/{report_id}.json) ──────────────────────

def report_payload(report_id: str) -> dict[str, Any]:
    path = config.DATA / f"{report_id}.json"
    if not path.exists():
        raise HTTPException(404, "보고서를 찾을 수 없습니다.")
    return json.loads(path.read_text(encoding="utf-8"))


def save_report_payload(report_id: str, payload: dict[str, Any]) -> None:
    _write_json(config.DATA / f"{report_id}.json", payload)


def delete_report_payload(report_id: str) -> None:
    (config.DATA / f"{report_id}.json").unlink(missing_ok=True)


# ── 보고서 인덱스 (data/reports.json) ────────────────────────

def load_report_index() -> list[dict[str, Any]]:
    return _read_json(config.REPORT_INDEX, [])


def save_report_index(items: list[dict[str, Any]]) -> None:
    _write_json(config.REPORT_INDEX, items)


def upsert_report_index(payload: dict[str, Any]) -> dict[str, Any]:
    unit, slides = payload["unit"], payload["slides"]
    item = {
        "id": unit["id"],
        "name": unit["name"],
        "short": unit.get("short", unit["name"]),
        "topic": unit.get("topic", ""),
        "slide_count": len(slides),
        "download": "",
        "keywords": unit.get("keywords", []),
        "source": unit.get("source", "demo"),
        "source_file": unit.get("source_file", ""),
        "issue_count": payload.get("validation", {}).get("total", 0),
        "status": "done",
        "uploaded_at": payload.get("uploaded_at", ""),
        "processing_seconds": payload.get("processing_seconds", 0),
    }
    index = [x for x in load_report_index() if x.get("id") != unit["id"]]
    index.append(item)
    save_report_index(index)
    return item


def remove_from_report_index(report_id: str) -> None:
    save_report_index([x for x in load_report_index() if x.get("id") != report_id])


# ── 레이아웃 오버라이드 (data/layout_overrides.json) ─────────

def load_layouts() -> dict[str, Any]:
    return _read_json(config.LAYOUT_STORE, {})


def save_layouts(payload: dict[str, Any]) -> None:
    _write_json(config.LAYOUT_STORE, payload)
