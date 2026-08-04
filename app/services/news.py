"""키워드 기반 뉴스 검색 — 구글 뉴스 RSS를 서버에서 가져온다.

API 키가 필요 없고, 네트워크가 막힌 환경(사내망·오프라인 데모)에서는
빈 목록과 사유를 돌려주므로 화면이 깨지지 않는다.
"""
from __future__ import annotations

import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree

RSS_ENDPOINT = "https://news.google.com/rss/search"
USER_AGENT = "Mozilla/5.0 (compatible; sunic-report-agent/1.0)"
TIMEOUT = 8
CACHE_TTL = 600  # 초

_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


def _strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _relative_day(pub: str) -> str:
    try:
        dt = parsedate_to_datetime(pub)
    except (TypeError, ValueError):
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    days = delta.days
    if days <= 0:
        return "오늘"
    if days == 1:
        return "어제"
    if days < 7:
        return f"{days}일 전"
    return dt.strftime("%m/%d")


def _score(title: str, keyword: str, rank: int, total: int) -> float:
    """관련도 = 검색 순위 기반 기본점 + 키워드 문자열 포함 가산."""
    base = 0.95 - (rank / max(total, 1)) * 0.30
    tokens = [t for t in re.split(r"\s+", keyword) if len(t) >= 2]
    hits = sum(1 for t in tokens if t in title)
    bonus = min(0.05, hits * 0.025)
    return round(min(0.99, base + bonus), 2)


def search(keyword: str, limit: int = 8) -> dict[str, Any]:
    keyword = (keyword or "").strip()
    if not keyword:
        return {"keyword": "", "items": [], "ok": False, "reason": "검색어가 비어 있습니다."}

    cached = _cache.get(keyword)
    if cached and _now() - cached[0] < CACHE_TTL:
        return cached[1]

    query = urllib.parse.urlencode({"q": keyword, "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
    request = urllib.request.Request(f"{RSS_ENDPOINT}?{query}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read()
    except (urllib.error.URLError, socket.timeout, OSError) as exc:
        return {
            "keyword": keyword,
            "items": [],
            "ok": False,
            "reason": f"뉴스 서버에 연결하지 못했습니다 ({type(exc).__name__}). 사내망에서는 외부 접속이 차단될 수 있습니다.",
        }

    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return {"keyword": keyword, "items": [], "ok": False, "reason": "뉴스 응답을 해석하지 못했습니다."}

    entries = root.findall("./channel/item")[:limit]
    items: list[dict[str, Any]] = []
    for rank, entry in enumerate(entries):
        title = _strip_tags(entry.findtext("title") or "")
        if not title:
            continue
        source_el = entry.find("source")
        source = _strip_tags(source_el.text if source_el is not None else "") or "뉴스"
        pub = entry.findtext("pubDate") or ""
        items.append({
            "type": "news",
            "title": title,
            "source": source,
            "date": _relative_day(pub),
            "link": entry.findtext("link") or "",
            "score": _score(title, keyword, rank, len(entries)),
        })

    result = {"keyword": keyword, "items": items, "ok": True, "reason": ""}
    _cache[keyword] = (_now(), result)
    return result


# 뉴스 검색어로 쓰기엔 너무 일반적인 낱말 (검색해도 사업과 무관한 기사가 나온다)
GENERIC_TERMS = {
    "일정", "실행", "협의", "기준", "방안", "구성", "체계", "전략", "목표", "관리", "운영", "적용",
    "확대", "개선", "분석", "방향", "역할", "단계", "과제", "성과", "지표", "조직", "의사결정",
    "보고", "회의", "담당", "범위", "요건", "확인", "검증", "수립", "제시", "포함", "가능",
    "개요", "전체", "사업", "기반", "구축", "확보", "중심", "추진", "내용", "현황", "계획",
    "주요", "대상", "결과", "예정", "필요", "경영진", "입장", "영문", "국문",
}


# 양식·서식에서 흘러들어온 노이즈 (폰트명 등)와 검색에 무의미한 조각
NOISE_TERMS = {
    "corbel", "extrabold", "나눔스퀘어", "tahoma", "wingdings", "arial", "phase", "sample",
    "solution", "smart", "factory", "energy", "mobility", "next", "green", "pptx", "시연본",
    "보고양식", "사업단", "보고서",
}
# 영문 단독 토큰 중 검색어로 의미 있는 약어
TECH_ACRONYMS = {"AI", "DX", "ESG", "SMR", "SFR", "EV", "IoT", "GPU", "CPU", "LNG", "ICT", "R&D", "5G", "6G"}


def _clean_token(token: str) -> str:
    token = token.strip(" ·_-()[]{}<>「」“”\"'")
    # 한글 조사 꼬리 제거 (…의 / …을 / …를 …)
    if len(token) > 2 and token[-1] in "의은는이가을를에서로과와도만":
        token = token[:-1]
    return token


def _useful(token: str) -> bool:
    token = token.strip()
    if len(token) < 2 or token.lower() in NOISE_TERMS or token in GENERIC_TERMS:
        return False
    if re.fullmatch(r"[\d.]+p?", token) or re.search(r"\d", token):
        return False
    # 한글이 없는 영문 토큰은 널리 쓰이는 약어만 허용
    if not re.search(r"[가-힣]", token) and token.upper() not in TECH_ACRONYMS:
        return False
    return True


def _phrases(text: str, max_phrases: int = 2) -> list[str]:
    """문장에서 뉴스 검색에 쓸 두 어절 구를 만든다."""
    tokens = [_clean_token(t) for t in re.split(r"[\s,·/_\-()]+", str(text or ""))]
    tokens = [t for t in tokens if _useful(t)]
    out: list[str] = []
    for i in range(len(tokens) - 1):
        out.append(f"{tokens[i]} {tokens[i + 1]}")
        if len(out) >= max_phrases:
            break
    if not out:
        out = [t for t in tokens if len(t) >= 3][:max_phrases]
    return out


def dominant_topic(slides: list[dict[str, Any]]) -> str:
    """모든 페이지에 반복되는 최상위(Lv1) 문단 = 보고서의 대주제.

    표준 양식은 같은 대주제가 이어지는 장에서도 Lv1 제목을 유지하므로,
    가장 자주 등장하는 Lv1 문단이 보고서 주제에 가장 가깝다.
    """
    from collections import Counter

    counter: Counter[str] = Counter()
    for slide in slides:
        for item in slide.get("body", []):
            if int(item.get("level", 0)) == 0:
                text = str(item.get("text", "")).strip()
                if len(text) >= 4:
                    counter[text] += 1
                break
    if not counter:
        return ""
    text, count = counter.most_common(1)[0]
    return text if count >= 2 else ""


def build_search_terms(payload: dict[str, Any], limit: int = 4) -> list[str]:
    """보고서에서 뉴스 검색어를 만든다.

    낱말 하나(예: '일정')보다 '자율제조 운영체계' 같은 두 어절 구가 검색 품질이 훨씬 좋다.
    사업단명 → 반복 대주제 → 첫 페이지 주제 → 키워드 순으로 구체적인 것을 앞세운다.
    """
    unit = payload.get("unit", payload)
    terms: list[str] = []

    def push(term: str) -> None:
        term = term.strip()
        if term and term not in terms:
            terms.append(term)

    for source in (unit.get("name"), dominant_topic(payload.get("slides") or []), unit.get("topic")):
        for phrase in _phrases(source or ""):
            push(phrase)

    for keyword in unit.get("keywords") or []:
        token = _clean_token(keyword)
        if _useful(token) and len(token) >= 3:
            push(token)
    if len(terms) < 2:
        for keyword in unit.get("keywords") or []:
            token = _clean_token(keyword)
            if _useful(token):
                push(token)
    return terms[:limit]


def refine_keywords(keywords: list[str], fallback: str = "", limit: int = 4) -> list[str]:
    """키워드 목록만으로 검색어를 고른다 (주제 문장이 없을 때의 보조 경로)."""
    picked = [k for k in (_clean_token(x) for x in keywords) if _useful(k)]
    picked.sort(key=lambda k: -len(k))
    out: list[str] = []
    for token in picked:
        if token not in out:
            out.append(token)
    if len(out) < 2 and fallback:
        for token in (_clean_token(t) for t in re.split(r"[\s_\-·]+", fallback)):
            if _useful(token) and token not in out:
                out.append(token)
    return out[:limit]


def search_many(keywords: list[str], per_keyword: int = 4, limit: int = 12) -> dict[str, Any]:
    """여러 키워드를 병렬로 검색해 관련도순으로 합친다."""
    from concurrent.futures import ThreadPoolExecutor

    terms = keywords[:5]
    if not terms:
        return {"items": [], "keywords": [], "ok": False, "reason": "검색할 키워드가 없습니다."}
    with ThreadPoolExecutor(max_workers=min(5, len(terms))) as pool:
        results = list(pool.map(lambda k: search(k, per_keyword), terms))

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    failures: list[str] = []
    counts: list[dict[str, Any]] = []
    for keyword, result in zip(terms, results):
        if not result["ok"]:
            failures.append(result["reason"])
            counts.append({"keyword": keyword, "count": 0})
            continue
        counts.append({"keyword": keyword, "count": len(result["items"])})
        for item in result["items"]:
            key = item["title"][:40]
            if key in seen:
                continue
            seen.add(key)
            merged.append({**item, "keyword": keyword})
    merged.sort(key=lambda x: -x["score"])
    return {
        "items": merged[:limit],
        "keywords": counts,
        "ok": bool(merged) or not failures,
        "reason": failures[0] if failures and not merged else "",
    }
