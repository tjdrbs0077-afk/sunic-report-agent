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


def _with_sort(result: dict[str, Any], order: str, limit: int,
               graph_keyword: str = "") -> dict[str, Any]:
    if order not in {"accuracy", "latest"}:
        raise HTTPException(400, "정렬 기준은 accuracy 또는 latest여야 합니다.")
    out = dict(result)
    sorted_items = news.sort_articles(out.get("items", []), order)
    out["items_total"] = len(sorted_items)
    if order == "accuracy":
        # 동점 기사가 몰려 상위가 전부 같은 날짜가 되는 것을 막는다 (점수 순서는 유지).
        visible = news.spread_by_day(sorted_items, limit)
    else:
        visible = sorted_items[:limit]
    # 캐시에 담긴 원본 dict 를 그대로 쓰면 build_graph 가 붙이는 색인이
    # 캐시 파일까지 흘러 들어간다. 화면용 사본을 따로 만든다.
    out["items"] = [dict(item) for item in visible]
    out["sort"] = order
    graph_keyword = (graph_keyword or "").strip()
    if graph_keyword:
        # 지식맵은 현재 정렬의 **상위 GRAPH_ARTICLES 건**으로 만든다.
        # build_graph 가 각 기사에 node_ids 를 채워 준다 (양방향 하이라이트용).
        seed = out["items"][:news.GRAPH_ARTICLES]
        out["graph"] = news.build_graph(seed, graph_keyword)
        # 화면 중앙의 빨간 노드는 보고서명이 아니라 실제 검색 키워드를 표시한다.
        out["graph_keyword"] = graph_keyword
        for item in out["items"][news.GRAPH_ARTICLES:]:
            item["node_ids"] = []   # 지식맵 밖 기사도 키는 갖고 있게 한다
        out["graph_basis"] = order
        out["graph_articles"] = len(seed)
    return out


@router.get("/news")
def search_news(q: str = Query(..., description="검색 키워드"), limit: int = 8,
                sort: str = "accuracy", days: int = news.LOOKBACK_DAYS) -> dict[str, Any]:
    if not q.strip():
        raise HTTPException(400, "검색어를 입력해 주세요.")
    visible_limit = min(max(limit, 1), 20)
    lookback = min(max(days, 1), 90)
    result = news.search(q, max(40, visible_limit * 4), lookback)
    out = _with_sort(result, sort, visible_limit, q.strip())
    out["lookback_days"] = lookback
    return out


@router.get("/reports/{report_id}/news")
def report_news(report_id: str, limit: int = 12, force: bool = False,
                sort: str = "accuracy", days: int = news.LOOKBACK_DAYS) -> dict[str, Any]:
    """보고서 키워드로 모은 기사와 기업–기술 관계 그래프.

    마지막 수집이 6시간을 넘었거나 force=true 이면 새로 수집한다.
    """
    payload = store.report_payload(report_id)
    unit = payload["unit"]
    terms = news.build_search_terms(payload)
    primary_keyword = terms[0] if terms else ""
    limit = min(max(limit, 1), 30)
    lookback = min(max(days, 1), 90)
    cache = _load_cache()
    entry = cache.get(report_id)

    # 수집 범위가 달라지면 저장된 결과로는 답할 수 없다 — 다시 모은다.
    cache_is_current = (entry and entry.get("version") == news.CACHE_VERSION
                        and int(entry.get("lookback_days") or 0) >= lookback)
    if cache_is_current and not force and _age_seconds(entry.get("fetched_at", "")) < news.REFRESH_INTERVAL:
        return _with_sort(_with_age(entry, True), sort, limit, primary_keyword)

    if not terms:
        return _with_sort(_with_age({
            "items": [], "keywords": [], "graph": {"nodes": [], "links": []},
            "ok": False, "reason": "보고서에서 검색할 키워드를 찾지 못했습니다.", "fetched_at": "",
        }, False), sort, limit, unit["name"])

    # 후보군을 넉넉히 모아 캐시에 담는다. 정확순·최신순이 같은 후보군을 나눠 쓰므로
    # 여기가 좁으면 어느 한쪽 정렬이 다른 쪽의 복사본이 된다.
    result = news.search_many(
        terms,
        per_keyword=max(30, limit * 2),
        limit=max(60, limit * 5),
        lookback_days=lookback,
    )
    result["unit"] = unit["name"]
    result["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if result["items"] or not entry:
        cache[report_id] = result
        _save_cache(cache)
        return _with_sort(_with_age(result, False), sort, limit, primary_keyword)
    # 수집에 실패했으면 직전 결과를 계속 보여준다.
    stale = _with_age(entry, True)
    stale["reason"] = result.get("reason", "")
    return _with_sort(stale, sort, limit, primary_keyword)
