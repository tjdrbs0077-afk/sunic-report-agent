"""레이아웃 편집 저장·불러오기·초기화 + 표준 양식 프로파일 조회."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import config
from app.services import store
from app.services.builder import exact_template_profile

router = APIRouter(prefix="/api", tags=["layout"])


class LayoutSaveRequest(BaseModel):
    report_id: str
    layout_overrides: dict[str, Any] = Field(default_factory=dict)


@router.get("/profile")
def profile() -> dict[str, Any]:
    if config.PROFILE_CACHE.exists():
        return json.loads(config.PROFILE_CACHE.read_text(encoding="utf-8"))
    result = exact_template_profile(config.TEMPLATE)
    config.PROFILE_CACHE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


@router.get("/layouts/{report_id}")
def get_layout(report_id: str):
    return {"report_id": report_id, "layout_overrides": store.load_layouts().get(report_id, {"global": {}, "slides": {}})}


@router.post("/layouts")
def save_layout(req: LayoutSaveRequest):
    layouts = store.load_layouts()
    layouts[req.report_id] = req.layout_overrides
    store.save_layouts(layouts)
    return {"ok": True, "report_id": req.report_id, "layout_overrides": req.layout_overrides}


@router.delete("/layouts/{report_id}")
def reset_layout(report_id: str):
    layouts = store.load_layouts()
    layouts.pop(report_id, None)
    store.save_layouts(layouts)
    return {"ok": True}
