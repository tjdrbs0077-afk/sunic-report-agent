"""외부 뉴스 수집 — 담당자가 보고서를 읽다 막히는 배경지식을 채우는 용도.

수집 경로 (앞에서부터 시도)
---------------------------
1. 네이버 검색 오픈 API   https://openapi.naver.com/v1/search/news.json
   NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 필요. 무료·일 25,000 건.
2. 구글 뉴스 RSS          키가 없을 때의 폴백.
   HTML 스크래핑이 아니라 RSS 라 페이지 구조 변경에 덜 취약하다.

보안 원칙 (1주차 수행계획서 리스크 항목 대응)
---------------------------------------------
**보고서 본문은 절대 나가지 않는다.** 이 모듈이 외부로 보내는 것은
사용자가 직접 입력한 질문에서 뽑아낸 검색어뿐이다.
`extract_query()` 가 그 경계선이며, 전송값은 호출부가 그대로 화면에 노출한다.
"""
from __future__ import annotations

import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

TIMEOUT_SEC = 12
NAVER_API = "https://openapi.naver.com/v1/search/news.json"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"

TAG_RE = re.compile(r"<[^>]+>")

# 검색어에서 걷어낼 조사·의문 표현. 남는 것은 고유명사·기술용어 위주가 된다.
_TRIM_PATTERNS = [
    r"(에\s*(대해|대한|관해|관한)|관련(해서|한|된|하여)?)\s*(알려줘|설명해줘|말해줘|알려주세요|정리해줘)?\s*\??$",
    r"에\s*(대해|대한|관해|관한)\s*(알려줘|설명해줘|말해줘|알려주세요|정리해줘)?",
    r"(이|가|은|는|을|를|의|와|과|도|만)?\s*(뭐야|뭔가요|무엇인가요|무엇이야|뭐지|어때|어떤가요)\s*\??$",
    r"(최근|요즘|현재)?\s*(동향|트렌드|근황|이슈|소식)\s*(이|은|는|을|를)?\s*(알려줘|정리해줘|찾아줘)?\s*\??$",
    r"(알려줘|설명해줘|정리해줘|찾아줘|요약해줘|말해줘)\s*\??$",
]


def _strip_external_tags(value: str) -> str:
    return html.unescape(TAG_RE.sub("", value or "")).strip()


def extract_query(question: str, max_len: int = 60) -> str:
    """질문에서 외부로 내보낼 검색어를 뽑는다.

    이 함수의 반환값이 **외부로 나가는 유일한 문자열**이다.
    호출부는 이 값을 사용자에게 그대로 보여 주어 무엇이 전송되는지 알 수 있게 한다.
    """
    original = re.sub(r"\s+", " ", (question or "")).strip()
    query = original
    for pattern in _TRIM_PATTERNS:
        query = re.sub(pattern, " ", query).strip()
    query = re.sub(r"[?？!！.]+$", "", query).strip()
    query = re.sub(r"\s+", " ", query)
    return (query or original)[:max_len]


def _naver_credentials() -> tuple[str, str] | None:
    cid = os.environ.get("NAVER_CLIENT_ID", "").strip()
    secret = os.environ.get("NAVER_CLIENT_SECRET", "").strip()
    return (cid, secret) if cid and secret else None


def _parse_date(value: str) -> str:
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S GMT"):
        try:
            parsed = datetime.strptime((value or "").strip(), fmt)
        except (ValueError, TypeError):
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d")
    return ""


def _fetch(url: str, headers: dict[str, str] | None = None) -> bytes:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "sunic-report-agent/0.1"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
        return resp.read()


def _search_naver_api(query: str, limit: int) -> list[dict[str, Any]]:
    creds = _naver_credentials()
    if not creds:
        return []
    cid, secret = creds
    url = f"{NAVER_API}?query={urllib.parse.quote(query)}&display={max(1, min(limit, 20))}&sort=date"
    raw = _fetch(url, {"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": secret})
    items = json.loads(raw.decode("utf-8")).get("items", [])
    return [
        {
            "title": _strip_external_tags(item.get("title", "")),
            "summary": _strip_external_tags(item.get("description", ""))[:220],
            "url": item.get("originallink") or item.get("link", ""),
            "date": _parse_date(item.get("pubDate", "")),
            "source": "네이버 뉴스",
        }
        for item in items
        if _strip_external_tags(item.get("title", ""))
    ]


def _search_rss(query: str, limit: int) -> list[dict[str, Any]]:
    url = f"{GOOGLE_NEWS_RSS}?q={urllib.parse.quote(query)}&hl=ko&gl=KR&ceid=KR:ko"
    root = ET.fromstring(_fetch(url).decode("utf-8", "replace"))
    results: list[dict[str, Any]] = []
    for item in root.iterfind(".//item"):
        title = _strip_external_tags(item.findtext("title") or "")
        if not title:
            continue
        results.append({
            "title": title,
            "summary": _strip_external_tags(item.findtext("description") or "")[:220],
            "url": (item.findtext("link") or "").strip(),
            "date": _parse_date(item.findtext("pubDate") or ""),
            "source": "구글 뉴스 RSS",
        })
        if len(results) >= limit:
            break
    return results


def search_news(query: str, limit: int = 5) -> dict[str, Any]:
    """뉴스를 검색해 기사 목록과 수집 경로를 함께 반환한다.

    반환: {articles, channel, sent_query, error}
    실패해도 예외를 올리지 않는다 — 챗봇은 뉴스 없이도 답해야 한다.
    """
    query = (query or "").strip()
    if not query:
        return {"articles": [], "channel": "none", "sent_query": "", "error": "검색어가 비어 있습니다"}

    last_error = "수집 경로를 사용할 수 없습니다"
    for channel, fn in (("naver_api", _search_naver_api), ("google_rss", _search_rss)):
        try:
            articles = fn(query, limit)
        except (urllib.error.URLError, urllib.error.HTTPError, ET.ParseError,
                ValueError, TimeoutError, OSError) as exc:
            last_error = f"{channel}: {exc}"
            continue
        if articles:
            return {"articles": articles, "channel": channel, "sent_query": query, "error": None}
        last_error = f"{channel}: 결과 없음"

    return {"articles": [], "channel": "none", "sent_query": query, "error": last_error}
"""키워드 기반 뉴스 검색 — 구글 뉴스 RSS를 서버에서 가져온다.

API 키가 필요 없고, 네트워크가 막힌 환경(사내망·오프라인 데모)에서는
빈 목록과 사유를 돌려주므로 화면이 깨지지 않는다.
"""
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
CACHE_TTL = 600  # 검색어 단위 메모리 캐시(초)
REFRESH_INTERVAL = 6 * 3600  # 보고서 단위 재수집 주기 — 6시간

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


# ── 기업–기술 관계 그래프 ──────────────────────────────────

# 기사 제목에서 찾아낼 기업. 계열 표기가 다양해 대표 이름으로 묶는다.
COMPANY_PATTERNS: list[tuple[str, str]] = [
    ("삼성전자", r"삼성전자"), ("삼성SDI", r"삼성\s?SDI"), ("삼성디스플레이", r"삼성디스플레이"),
    ("SK하이닉스", r"SK\s?하이닉스"), ("SK온", r"SK\s?온"), ("SK이노베이션", r"SK\s?이노베이션"),
    ("SK텔레콤", r"SK\s?텔레콤|SKT"), ("SK에코플랜트", r"SK\s?에코플랜트"), ("SK E&S", r"SK\s?E&S"),
    ("LG에너지솔루션", r"LG\s?에너지솔루션|LG엔솔"), ("LG전자", r"LG전자"), ("LG화학", r"LG화학"),
    ("현대자동차", r"현대차|현대자동차"), ("기아", r"기아(?!자)"), ("포스코", r"포스코|POSCO"),
    ("한화", r"한화"), ("두산", r"두산"), ("네이버", r"네이버|NAVER"), ("카카오", r"카카오"),
    ("엔비디아", r"엔비디아|NVIDIA"), ("인텔", r"인텔|Intel"), ("TSMC", r"TSMC"),
    ("애플", r"애플|Apple"), ("구글", r"구글|Google"), ("마이크로소프트", r"마이크로소프트|MS|Microsoft"),
    ("테슬라", r"테슬라|Tesla"), ("도요타", r"도요타|토요타"), ("파나소닉", r"파나소닉"),
    ("CATL", r"CATL"), ("BYD", r"BYD"), ("퀀텀스케이프", r"퀀텀스케이프|QuantumScape"),
    ("아마존", r"아마존|AWS"), ("오픈AI", r"오픈\s?AI|OpenAI"),
]
# 사전에 없는 기업·기관을 잡아내는 접미사 패턴
ORG_SUFFIX = re.compile(
    r"([가-힣A-Za-z]{2,10}(?:전자|화학|에너지|중공업|건설|제철|바이오|반도체|모빌리티|솔루션|시스템즈"
    r"|공사|공단|협회|연구원|연구소|과학기술원|대학교|산업부|중기부|과기부))"
)
# 기사 제목은 "주체, 내용" 형태가 많다 — 쉼표 앞을 주체 후보로 본다
SUBJECT_HEAD = re.compile(r"^([^,]{2,24}?)\s*,")
# 지자체·부처 등 기관 접미사
ORG_TAIL = re.compile(r"(시|군|구|도|부|청|원|회|단|사)$")
# 주체로 보기 어려운 낱말과 직함
SUBJECT_STOP = {
    "AI", "데이터", "제조", "산업", "기술", "세계", "국내", "글로벌", "속보", "단독", "인터뷰",
    "오늘", "내년", "올해", "정부", "업계", "시장", "미래", "현장", "특집", "기획",
}
TITLE_TAIL = re.compile(r"(의원|위원장|장관|차관|사장|대표|회장|교수|본부장|실장|국장|과장)$")


def extract_companies(title: str) -> list[str]:
    """기사 제목에서 기업·기관 이름을 뽑는다 (사전 → 접미사 → 문장 주체 순)."""
    found: list[str] = []
    for name, pattern in COMPANY_PATTERNS:
        if re.search(pattern, title) and name not in found:
            found.append(name)
    if found:
        return found[:3]

    for match in ORG_SUFFIX.findall(title):
        if match not in found and len(match) >= 3:
            found.append(match)
    if found:
        return found[:3]

    head = SUBJECT_HEAD.match(title)
    if head:
        # "제조업 체질개선 확실히…경산시" 처럼 앞말이 붙은 경우 마지막 조각만 쓴다
        candidate = re.split(r"[…·\]\)》」]", head.group(1))[-1].strip()
        tokens = candidate.split()
        if len(tokens) > 1:
            candidate = tokens[-1]  # "김승기 경기도의원" → "경기도의원"
        candidate = candidate.strip("‘’“”'\"[]()")
        if (
            2 <= len(candidate) <= 12
            and candidate not in SUBJECT_STOP
            and not TITLE_TAIL.search(candidate)
            and (ORG_TAIL.search(candidate) or re.search(r"[A-Za-z]{2,}", candidate))
        ):
            found.append(candidate)
    return found[:3]


def build_graph(items: list[dict[str, Any]], unit_name: str, max_nodes: int = 9) -> dict[str, Any]:
    """수집된 기사에서 기업–기술 관계 그래프를 만든다.

    기사 제목에 기업과 기술 키워드가 함께 나오면 연결한다. 등장 횟수를
    노드 크기·선 굵기로 표현하고, 근거 기사 제목을 함께 담는다.
    """
    from collections import defaultdict

    company_hits: dict[str, list[str]] = defaultdict(list)
    tech_hits: dict[str, list[str]] = defaultdict(list)
    edges: dict[tuple[str, str], list[str]] = defaultdict(list)

    for item in items:
        title = item.get("title", "")
        tech = item.get("keyword", "")
        companies = extract_companies(title)
        if tech:
            tech_hits[tech].append(title)
        for company in companies:
            company_hits[company].append(title)
            if tech:
                edges[(company, tech)].append(title)

    top_companies = sorted(company_hits.items(), key=lambda kv: -len(kv[1]))[:max_nodes - 1]
    kept = {name for name, _ in top_companies}
    techs = sorted(tech_hits.items(), key=lambda kv: -len(kv[1]))

    nodes: list[dict[str, Any]] = [{
        "id": "us", "type": "us", "label": _short(unit_name, 14),
        "weight": len(items), "articles": [],
    }]
    for name, titles in top_companies:
        nodes.append({"id": f"c:{name}", "type": "company", "label": name,
                      "weight": len(titles), "articles": titles[:3]})
    for name, titles in techs:
        nodes.append({"id": f"t:{name}", "type": "tech", "label": name,
                      "weight": len(titles), "articles": titles[:3]})

    links: list[dict[str, Any]] = []
    for name, titles in techs:
        links.append({"source": "us", "target": f"t:{name}", "label": "보고서 키워드",
                      "weight": len(titles), "articles": []})
    for (company, tech), titles in edges.items():
        if company in kept:
            links.append({"source": f"c:{company}", "target": f"t:{tech}",
                          "label": f"기사 {len(titles)}건", "weight": len(titles),
                          "articles": titles[:3]})
    return {"nodes": nodes, "links": links}


def _short(text: str, limit: int) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


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
