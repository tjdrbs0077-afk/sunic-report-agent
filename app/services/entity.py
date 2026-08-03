"""오프라인 엔티티 추출 — 검색어와 공개 뉴스에서 그래프 재료를 만든다.

1차 MVP는 규칙 기반만 사용한다 (CLAUDE.md: 외부 LLM 기본 비활성).
오프라인 규칙으로는 **의미 관계를 추정하지 않는다** — 같은 기사에 함께
등장했다는 사실만 `co_occurrence` 엣지로 기록하고, 라벨은 "함께 언급"으로
고정한다. 화면은 이를 점선으로 그려 실제 관계와 구분한다.

엣지는 검색어 노드 ↔ 발견된 기업 노드 사이에만 만든다.
기업-기업 동시 등장까지 연결하면 관계를 과장하게 되므로 하지 않는다.

2차에서 답변 생성과 통합된 LLM 호출이 `extracted` 관계(실선)를 추가한다.
그때도 기사 근거(article_index + 근거 문장)가 없는 관계는 채택하지 않는다.

보안: 이 모듈은 보고서 본문을 받지 않는다. 입력은 정제된 검색어와
외부에서 수집한 공개 기사뿐이며, 명확한 개인정보 패턴은 걷어낸다.
"""
from __future__ import annotations

import re
from typing import Any

from app.services.graph_store import article_hash, canonical_label, node_id

# 동시 등장(점선) 관계의 고정 신뢰도 — "관계가 있다"가 아니라 "함께 언급됐다"의 확신도
CO_OCCURRENCE_CONFIDENCE = 0.6

# 기사 본문 매칭용 기업명 패턴. 키는 대표 표기(canonical), 값은 표기 변형들.
# 별칭 사전(graph_store.ALIASES)과 함께 유지한다.
COMPANY_PATTERNS: dict[str, list[str]] = {
    "삼성SDI": ["삼성SDI", "삼성 SDI", "Samsung SDI", "삼성에스디아이"],
    "LG에너지솔루션": ["LG에너지솔루션", "LG 에너지솔루션", "LG엔솔", "LG Energy Solution"],
    "SK온": ["SK온", "SK 온", "SK On"],
    "도요타": ["도요타", "토요타", "Toyota"],
    "QuantumScape": ["QuantumScape", "퀀텀스케이프", "퀀텀 스케이프"],
    "파나소닉": ["파나소닉", "Panasonic"],
    "CATL": ["CATL", "닝더스다이"],
    "BYD": ["BYD", "비야디"],
    "테슬라": ["테슬라", "Tesla"],
    "현대자동차": ["현대자동차", "현대차", "Hyundai Motor"],
    "포스코퓨처엠": ["포스코퓨처엠", "POSCO Future M"],
    "에코프로": ["에코프로", "EcoPro"],
    "Solid Power": ["Solid Power", "솔리드파워"],
}

_COMPANY_RE = {
    canon: re.compile("|".join(re.escape(v) for v in variants), re.IGNORECASE)
    for canon, variants in COMPANY_PATTERNS.items()
}

# 명확한 개인정보 패턴 — 검색어에서 제거하고 경고를 남긴다
_PII_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "이메일"),
    (re.compile(r"01[016789][-\s]?\d{3,4}[-\s]?\d{4}"), "전화번호"),
    (re.compile(r"\d{6}[-\s]?[1-4]\d{6}"), "주민등록번호 추정"),
]


def strip_personal(query: str) -> tuple[str, list[str]]:
    """검색어에서 명확한 개인정보 패턴을 제거한다."""
    warnings: list[str] = []
    clean = query or ""
    for pattern, kind in _PII_PATTERNS:
        if pattern.search(clean):
            clean = pattern.sub(" ", clean)
            warnings.append(f"검색어에서 {kind} 패턴을 제거했습니다")
    return re.sub(r"\s+", " ", clean).strip(), warnings


def extract(query: str, articles: list[dict[str, Any]]) -> dict[str, Any]:
    """검색어 + 수집 기사 → graph_store.merge() 입력 형식.

    반환: {nodes, edges, articles, warnings}
    """
    clean_query, warnings = strip_personal(query)
    if not clean_query:
        return {"nodes": [], "edges": [], "articles": {}, "warnings": warnings or ["검색어가 비어 있습니다"]}

    # 검색어 자체가 하나의 노드 — 사전에 있는 기업명이면 company, 아니면 tech(주제)
    canon = canonical_label(clean_query)
    query_type = "company" if canon in COMPANY_PATTERNS else "tech"
    query_node_id = node_id(query_type, canon)

    dedup_articles: dict[str, dict[str, Any]] = {}
    node_articles: dict[str, set[str]] = {query_node_id: set()}
    found_companies: dict[str, dict[str, set[str]]] = {}  # canon → {"hashes": set}

    for art in articles or []:
        h = article_hash(art)
        if h not in dedup_articles:
            dedup_articles[h] = {
                "title": art.get("title", ""),
                "url": art.get("url", ""),
                "date": art.get("date", ""),
                "source": art.get("source", ""),
            }
        node_articles[query_node_id].add(h)  # 이 검색어로 수집된 기사

        text = f"{art.get('title', '')} {art.get('summary', '')}"
        for company_canon, pattern in _COMPANY_RE.items():
            if pattern.search(text):
                found_companies.setdefault(company_canon, {"hashes": set()})["hashes"].add(h)

    nodes: list[dict[str, Any]] = [{
        "id": query_node_id,
        "label": canon,
        "type": query_type,
        "article_ids": sorted(node_articles[query_node_id]),
    }]
    edges: list[dict[str, Any]] = []

    for company_canon, info in found_companies.items():
        cid = node_id("company", company_canon)
        if cid == query_node_id:
            continue
        nodes.append({
            "id": cid,
            "label": company_canon,
            "type": "company",
            "article_ids": sorted(info["hashes"]),
        })
        edges.append({
            "a": query_node_id,
            "b": cid,
            "label": "함께 언급",
            "relation_type": "co_occurrence",
            "extraction_method": "offline",
            "confidence": CO_OCCURRENCE_CONFIDENCE,
            "article_ids": sorted(info["hashes"]),
            "evidence": None,
        })

    return {"nodes": nodes, "edges": edges, "articles": dedup_articles, "warnings": warnings}
