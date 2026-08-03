"""⑥ 동향 인사이트 — 조사 이력 지식맵 API.

그래프는 ⑤ 챗봇 지식·동향 모드의 조사 활동이 누적된 결과다.
articles / reset 엔드포인트는 2차에서 추가한다 (DESIGN 문서 §3-4).
"""
from __future__ import annotations

from fastapi import APIRouter

from app.services import graph_store

router = APIRouter(prefix="/api/insight", tags=["insight"])


@router.get("/graph")
def graph():
    """전체 그래프. 시드(예시 데이터)는 seed: true 로 구분된다."""
    return graph_store.load_graph()
