"""동향 인사이트 — 보고서 키워드로 실제 뉴스 기사를 검색한다.

수집 결과는 data/news_cache.json 에 저장하고 6시간마다 갱신한다.
정해진 시각에 도는 스케줄러 대신 '열었을 때 오래됐으면 갱신'하는 방식인데,
무료 호스팅에서는 접속이 없으면 서버가 잠들어 타이머가 돌지 않기 때문이다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app import config
from app.services import news, store

router = APIRouter(prefix="/api", tags=["news"])

CACHE_FILE = config.DATA / "news_cache.json"


def _load_cache() -> dict[str, Any]:
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_cache(cache: dict[str, Any]) -> None:
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _age_seconds(fetched_at: str) -> float:
    try:
        dt = datetime.fromisoformat(fetched_at)
    except (TypeError, ValueError):
        return float("inf")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds()


def _with_age(entry: dict[str, Any], from_cache: bool) -> dict[str, Any]:
    out = dict(entry)
    out["from_cache"] = from_cache
    out["age_minutes"] = int(_age_seconds(out.get("fetched_at", "")) // 60) if out.get("fetched_at") else None
    out["refresh_hours"] = news.REFRESH_INTERVAL // 3600
    return out


@router.get("/news")
def search_news(q: str = Query(..., description="검색 키워드"), limit: int = 8) -> dict[str, Any]:
    if not q.strip():
        raise HTTPException(400, "검색어를 입력해 주세요.")
    return news.search(q, min(max(limit, 1), 20))


@router.get("/reports/{report_id}/news")
def report_news(report_id: str, limit: int = 12, force: bool = False) -> dict[str, Any]:
    """보고서 키워드로 모은 기사와 기업–기술 관계 그래프.

    마지막 수집이 6시간을 넘었거나 force=true 이면 새로 수집한다.
    """
    payload = store.report_payload(report_id)
    unit = payload["unit"]
    cache = _load_cache()
    entry = cache.get(report_id)

    if entry and not force and _age_seconds(entry.get("fetched_at", "")) < news.REFRESH_INTERVAL:
        return _with_age(entry, True)

    terms = news.build_search_terms(payload)
    if not terms:
        return _with_age({
            "items": [], "keywords": [], "graph": {"nodes": [], "links": []},
            "ok": False, "reason": "보고서에서 검색할 키워드를 찾지 못했습니다.", "fetched_at": "",
        }, False)

    result = news.search_many(terms, per_keyword=4, limit=limit)
    result["unit"] = unit["name"]
    result["graph"] = news.build_graph(result["items"], unit["name"])
    result["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if result["items"] or not entry:
        cache[report_id] = result
        _save_cache(cache)
        return _with_age(result, False)
    # 수집에 실패했으면 직전 결과를 계속 보여준다.
    stale = _with_age(entry, True)
    stale["reason"] = result.get("reason", "")
    return stale
