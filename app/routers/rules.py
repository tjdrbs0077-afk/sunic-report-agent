"""양식 규칙 조회 — 업로드 화면의 '적용 중인 양식 기준' 카드가 사용한다."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.services import validator

router = APIRouter(prefix="/api", tags=["rules"])


@router.get("/rules")
def rules() -> dict[str, Any]:
    return validator.load_rules()
