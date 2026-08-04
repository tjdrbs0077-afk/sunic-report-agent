"""동향 인사이트 — 보고서 키워드로 실제 뉴스 기사를 검색한다."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.services import news, store

router = APIRouter(prefix="/api", tags=["news"])


@router.get("/news")
def search_news(q: str = Query(..., description="검색 키워드"), limit: int = 8) -> dict[str, Any]:
    if not q.strip():
        raise HTTPException(400, "검색어를 입력해 주세요.")
    return news.search(q, min(max(limit, 1), 20))


@router.get("/reports/{report_id}/news")
def report_news(report_id: str, limit: int = 12) -> dict[str, Any]:
    """보고서에서 추출한 키워드로 관련 기사를 모아 온다."""
    payload = store.report_payload(report_id)
    unit = payload["unit"]
    terms = news.build_search_terms(payload)
    if not terms:
        return {"items": [], "keywords": [], "ok": False, "reason": "보고서에서 검색할 키워드를 찾지 못했습니다."}
    result = news.search_many(terms, per_keyword=4, limit=limit)
    result["unit"] = payload["unit"]["name"]
    return result
