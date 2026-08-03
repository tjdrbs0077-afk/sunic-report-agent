"""동향 그래프 저장소 — data/insight_graph.json

⑥ 동향 인사이트의 지식맵을 관리한다. 그래프는 "사실 관계도"가 아니라
**팀 조사 이력의 누적**이다. 노드·엣지는 ⑤ 챗봇 지식·동향 모드의 질문에서
추출된 결과가 병합되며, 재료는 정제된 검색어와 공개 뉴스뿐이다.
질문 원문·보고서 본문은 어떤 형태로도 저장하지 않는다.

식별 규칙 (이 모듈이 단일 진실 공급원)
--------------------------------------
- 노드 ID는 **결정적**: ``f"{type}:{slug(canonical_label)}"``.
  같은 엔티티가 동시에 들어와도 중복 노드가 생기지 않는다.
- 표기 흔들림은 ``ALIASES`` 별칭 사전으로 흡수한다. (삼성 SDI → 삼성SDI)
- 기사는 URL(없으면 정규화 제목+날짜) 해시로 최상위 ``articles`` 에 1회만 저장,
  엣지·노드는 해시로 참조한다. → article_count 중복 집계 방지.

카운트 3종 (의미가 다르다)
--------------------------
article_count  중복 제거된 관련 기사 수
query_count    이 노드를 발견한 고유 검색어 수
touch_count    조사 과정에서 등장한 총횟수 (노드 크기에 반영)
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any

from app import config

# ── 별칭 사전 — 표기가 달라도 같은 노드로 병합한다 ──────────
# 키는 소문자·단일 공백으로 정규화해 조회한다. 데모 도메인(배터리) 중심.
ALIASES = {
    "삼성 sdi": "삼성SDI",
    "samsung sdi": "삼성SDI",
    "삼성에스디아이": "삼성SDI",
    "퀀텀스케이프": "QuantumScape",
    "퀀텀 스케이프": "QuantumScape",
    "quantumscape": "QuantumScape",
    "lg 에너지솔루션": "LG에너지솔루션",
    "lg에너지솔루션": "LG에너지솔루션",
    "lg엔솔": "LG에너지솔루션",
    "lg energy solution": "LG에너지솔루션",
    "toyota": "도요타",
    "토요타": "도요타",
    "sk온": "SK온",
    "sk on": "SK온",
    "전고체전지": "전고체 배터리",
    "전고체 전지": "전고체 배터리",
    "all-solid-state battery": "전고체 배터리",
    "solid-state battery": "전고체 배터리",
    "황화물계 전해질": "황화물 전해질",
    "리튬메탈": "리튬메탈 음극",
    "리튬 메탈 음극": "리튬메탈 음극",
    "건식전극": "건식 전극",
    "건식 전극 공정": "건식 전극",
}


def canonical_label(label: str) -> str:
    """별칭 사전을 통과시킨 대표 표기를 돌려준다."""
    key = re.sub(r"\s+", " ", (label or "").strip()).lower()
    return ALIASES.get(key, re.sub(r"\s+", " ", (label or "").strip()))


def node_id(node_type: str, label: str) -> str:
    """결정적 노드 ID. 예) company:삼성sdi / tech:전고체배터리"""
    slug = re.sub(r"[^0-9a-z가-힣]+", "", canonical_label(label).lower())
    return f"{node_type}:{slug or 'unknown'}"


def article_hash(article: dict[str, Any]) -> str:
    """기사 중복 제거 키. URL 우선, 없으면 정규화 제목+날짜."""
    url = (article.get("url") or "").strip()
    if url:
        basis = url
    else:
        title = re.sub(r"\s+", " ", (article.get("title") or "").strip()).lower()
        basis = f"{title}|{article.get('date') or ''}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def _edge_id(a: str, b: str) -> str:
    return "|".join(sorted((a, b)))


# ── 시드 (예시 데이터) ───────────────────────────────────────
# 기존 ⑥ 화면의 더미를 계승한 **예시 데이터**다. 화면에는 반드시
# "예시 데이터"로 표시한다 — 실제 수집 결과로 오해하게 만들지 않는다.

def _seed_node(node_type: str, label: str, desc: str) -> dict[str, Any]:
    return {
        "id": node_id(node_type, label),
        "label": canonical_label(label),
        "type": node_type,
        "desc": desc,
        "article_count": 0,
        "query_count": 0,
        "touch_count": 0,   # 시드는 조사 이력이 없다 — 예시 데이터임을 수치로도 드러낸다
        "first_seen": "",
        "last_seen": "",
        "search_queries": [],
        "article_ids": [],
        "seed": True,
    }


def _seed_edge(a_id: str, b_id: str, label: str) -> dict[str, Any]:
    return {
        "id": _edge_id(a_id, b_id),
        "a": a_id,
        "b": b_id,
        "label": label,
        "relation_type": "seed",
        "extraction_method": "seed",
        "confidence": None,
        "weight": 1,
        "article_ids": [],
        "evidence": None,
    }


def _seed_graph() -> dict[str, Any]:
    n = {
        "us": _seed_node("biz", "우리 사업", "배터리소재사업단 기획안"),
        "ssdi": _seed_node("company", "삼성SDI", "전고체 파일럿 S라인 운영"),
        "toy": _seed_node("company", "도요타", "2027 양산 목표"),
        "qs": _seed_node("company", "QuantumScape", "리튬메탈 분리막"),
        "lg": _seed_node("company", "LG에너지솔루션", "건식 전극 2028 상용화"),
        "sulf": _seed_node("tech", "황화물 전해질", "예시 · 특허 5건 · 기사 8건"),
        "limt": _seed_node("tech", "리튬메탈 음극", "예시 · 기사 6건"),
        "dry": _seed_node("tech", "건식 전극", "예시 · 특허 3건 · 기사 4건"),
    }
    pairs = [
        ("us", "sulf", "핵심 기술"), ("us", "limt", "검토 중"), ("us", "dry", "공정 검토"),
        ("ssdi", "sulf", "파일럿 적용"), ("toy", "sulf", "양산 개발"),
        ("qs", "limt", "상용화 선도"), ("lg", "dry", "공정 개발"), ("toy", "limt", "공동 연구"),
    ]
    return {
        "articles": {},
        "nodes": list(n.values()),
        "edges": [_seed_edge(n[a]["id"], n[b]["id"], lb) for a, b, lb in pairs],
    }


# ── 로드 / 저장 ──────────────────────────────────────────────

def load_graph() -> dict[str, Any]:
    """그래프를 읽는다. 파일이 없거나 깨졌으면 시드로 초기화한다."""
    if config.INSIGHT_GRAPH.exists():
        try:
            graph = json.loads(config.INSIGHT_GRAPH.read_text(encoding="utf-8"))
            if isinstance(graph, dict) and {"articles", "nodes", "edges"} <= set(graph):
                return graph
        except json.JSONDecodeError:
            pass
    graph = _seed_graph()
    save_graph(graph)
    return graph


def save_graph(graph: dict[str, Any]) -> None:
    config.INSIGHT_GRAPH.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 병합 ─────────────────────────────────────────────────────

def merge(extraction: dict[str, Any], query: str) -> dict[str, Any]:
    """entity.extract() 결과를 그래프에 병합하고 delta를 돌려준다.

    extraction 형식:
        nodes    [{id, label, type, desc?, article_ids?}]
        edges    [{a, b, label, relation_type, extraction_method,
                   confidence, article_ids?, evidence?}]
        articles {hash: {title, url, date, source}}
    """
    graph = load_graph()
    today = date.today().isoformat()
    query = (query or "").strip()

    delta: dict[str, Any] = {
        "added_node_ids": [], "updated_node_ids": [], "added_edge_ids": [],
        "article_count": 0, "warnings": list(extraction.get("warnings", [])),
    }

    # 1) 기사 등록 — 해시 기준 1회만
    for h, art in (extraction.get("articles") or {}).items():
        if h not in graph["articles"]:
            graph["articles"][h] = art
            delta["article_count"] += 1

    # 2) 노드 병합
    by_id = {node["id"]: node for node in graph["nodes"]}
    for incoming in extraction.get("nodes", []):
        art_ids = list(incoming.get("article_ids") or [])
        node = by_id.get(incoming["id"])
        if node is None:
            node = {
                "id": incoming["id"],
                "label": incoming["label"],
                "type": incoming["type"],
                "desc": incoming.get("desc", ""),
                "article_count": len(set(art_ids)),
                "query_count": 1 if query else 0,
                "touch_count": 1,
                "first_seen": today,
                "last_seen": today,
                "search_queries": [query] if query else [],
                "article_ids": sorted(set(art_ids)),
                "seed": False,
            }
            graph["nodes"].append(node)
            by_id[node["id"]] = node
            delta["added_node_ids"].append(node["id"])
            continue

        node["touch_count"] = node.get("touch_count", 0) + 1
        node["article_ids"] = sorted(set(node.get("article_ids", [])) | set(art_ids))
        node["article_count"] = len(node["article_ids"])
        if query and query not in node.get("search_queries", []):
            node.setdefault("search_queries", []).append(query)
        node["query_count"] = len(node.get("search_queries", []))
        node["last_seen"] = today
        if not node.get("first_seen"):
            node["first_seen"] = today
        if incoming.get("desc") and not node.get("desc"):
            node["desc"] = incoming["desc"]
        if node["id"] not in delta["updated_node_ids"]:
            delta["updated_node_ids"].append(node["id"])

    # 3) 엣지 병합 — 방향 없는 쌍으로 식별
    edge_by_id = {edge["id"]: edge for edge in graph["edges"]}
    for incoming in extraction.get("edges", []):
        a, b = incoming["a"], incoming["b"]
        if a == b or a not in by_id or b not in by_id:
            continue
        eid = _edge_id(a, b)
        art_ids = list(incoming.get("article_ids") or [])
        edge = edge_by_id.get(eid)
        if edge is None:
            edge = {
                "id": eid, "a": a, "b": b,
                "label": incoming.get("label", "함께 언급"),
                "relation_type": incoming.get("relation_type", "co_occurrence"),
                "extraction_method": incoming.get("extraction_method", "offline"),
                "confidence": incoming.get("confidence"),
                "weight": 1,
                "article_ids": sorted(set(art_ids)),
                "evidence": incoming.get("evidence"),
            }
            graph["edges"].append(edge)
            edge_by_id[eid] = edge
            delta["added_edge_ids"].append(eid)
            continue

        edge["weight"] = edge.get("weight", 1) + 1
        edge["article_ids"] = sorted(set(edge.get("article_ids", [])) | set(art_ids))
        # 시드(예시) 관계가 실제 조사로 재발견되면 실데이터 승격
        if edge.get("relation_type") == "seed" and incoming.get("relation_type"):
            edge["relation_type"] = incoming["relation_type"]
            edge["extraction_method"] = incoming.get("extraction_method", "offline")
            edge["label"] = incoming.get("label", edge["label"])
            edge["confidence"] = incoming.get("confidence")
        # 근거가 더 강한 추출(LLM)이 들어오면 라벨·근거 갱신
        elif incoming.get("relation_type") == "extracted":
            edge["relation_type"] = "extracted"
            edge["extraction_method"] = incoming.get("extraction_method", "llm")
            edge["label"] = incoming.get("label", edge["label"])
            edge["confidence"] = incoming.get("confidence")
            if incoming.get("evidence"):
                edge["evidence"] = incoming["evidence"]

    save_graph(graph)
    return delta
