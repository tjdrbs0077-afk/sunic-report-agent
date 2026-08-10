"""⑥ 동향 인사이트용 키워드 뉴스 검색 — 구글 뉴스 RSS를 서버에서 가져온다.

API 키가 필요 없고, 네트워크가 막힌 환경(사내망·오프라인 데모)에서는
빈 목록과 사유를 돌려주므로 화면이 깨지지 않는다.

정렬 설계
---------
구글 뉴스 RSS 는 검색어만 던지면 **최근 며칠치만** 내려준다. 응답을 전부
채점해도 후보 자체가 오늘 기사뿐이라 '정확순'이 '최신순'과 같아진다.
그래서 한 검색어를 **기간 창(window)으로 나눠 여러 번** 요청한다
(`SEARCH_WINDOWS`). 최근 1주 / 1~2주 전 / 2~4주 전을 따로 받아 합치면
정확순이 한 달 범위에서 진짜 일치율 순으로 정렬된다.

정확도 점수는 RSS 순위가 아니라 제목·요약의 검색어 일치에서만 나온다.
"""
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree

RSS_ENDPOINT = "https://news.google.com/rss/search"
USER_AGENT = "Mozilla/5.0 (compatible; sunic-report-agent/1.0)"
TIMEOUT = 8
CACHE_TTL = 600  # 검색어 단위 메모리 캐시(초)
REFRESH_INTERVAL = 6 * 3600  # 보고서 단위 재수집 주기 — 6시간
MAX_FEED_ITEMS = 100  # RSS 한 응답에서 채점할 최대 기사 수
LOOKBACK_DAYS = 30  # 정확순이 훑는 기간 — 최근 한 달
CACHE_VERSION = 4  # 점수 체계·수집 범위가 바뀌면 올린다 (구버전 캐시는 자동 재수집)

# 기간 창 (시작일 전, 종료일 전) — 구글 뉴스의 after:/before: 연산자로 나눠 받는다.
# 하나의 질의로는 최근 며칠치만 오므로, 창을 나눠야 한 달치가 고르게 모인다.
SEARCH_WINDOWS: list[tuple[int, int]] = [(7, 0), (14, 7), (LOOKBACK_DAYS, 14)]

_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


def _strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _published_datetime(pub: str) -> datetime | None:
    try:
        dt = parsedate_to_datetime(pub)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _published_at(pub: str) -> str:
    """기사 발행 시각을 최신순 정렬에 사용할 UTC ISO 문자열로 바꾼다."""
    dt = _published_datetime(pub)
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z") if dt else ""


def _relative_day(pub: str) -> str:
    dt = _published_datetime(pub)
    if dt is None:
        return ""
    kst = timezone(timedelta(hours=9))
    local_dt = dt.astimezone(kst)
    local_now = datetime.now(kst)
    days = (local_now.date() - local_dt.date()).days
    clock = local_dt.strftime("%H:%M")
    if days <= 0:
        return f"오늘 {clock}"
    if days == 1:
        return f"어제 {clock}"
    if days < 7:
        return f"{days}일 전 {clock}"
    return local_dt.strftime("%Y.%m.%d")


def _match_tokens(value: str) -> list[str]:
    return [token.casefold() for token in re.findall(r"[0-9A-Za-z가-힣&]+", value or "") if len(token) >= 2]


def relevance_score(title: str, summary: str, keyword: str,
                    rank: int = 0, total: int = 1) -> float:
    """제목·요약의 검색어 일치만으로 관련도를 계산한다.

    **RSS 순위(rank)는 점수에 넣지 않는다.** RSS 는 사실상 최신순이라
    순위를 섞으면 '정확순'이 '최신순'의 복사본이 돼 버린다. rank·total 은
    기존 호출부 호환을 위해 남겨 두었을 뿐 계산에 쓰이지 않는다.

    구성 요소 (합계 최대 1.0)
      - 제목 어절 커버리지 0.34 : 검색어 토큰이 제목에 몇 개나 있는가
      - 제목 완전 일치     0.22 : 검색어 구가 통째로 제목에 있는가
      - 제목 앞부분 등장   0.10 : 제목 앞쪽에 나올수록 그 기사의 주제일 확률이 높다
      - 제목 내 밀도       0.14 : 짧은 제목이 검색어로 채워질수록 정확한 기사
      - 요약 커버리지      0.12
      - 기본점             0.08
    밀도 항목이 있어 커버리지가 같은 기사끼리도 점수가 갈린다. 이것이
    동점 붕괴 → 시간 tie-break → '오늘 기사만' 현상을 막는 핵심이다.
    """
    clean_title = re.sub(r"\s+", " ", title or "").strip()
    folded_title = clean_title.casefold()
    folded_summary = re.sub(r"\s+", " ", summary or "").casefold()
    phrase = re.sub(r"\s+", " ", keyword or "").strip().casefold()
    tokens = _match_tokens(keyword)
    if not tokens:
        return 0.01

    hit_tokens = [token for token in tokens if token in folded_title]
    title_coverage = len(hit_tokens) / len(tokens)
    summary_coverage = sum(1 for token in tokens if token in folded_summary) / len(tokens)
    exact = 1.0 if phrase and phrase in folded_title else 0.0

    # 검색어가 제목 어디쯤에서 처음 나오는가 (0 = 맨 앞)
    positions = [folded_title.find(token) for token in hit_tokens]
    if exact:
        positions.append(folded_title.find(phrase))
    first = min(p for p in positions if p >= 0) if any(p >= 0 for p in positions) else -1
    head = 0.0 if first < 0 else max(0.0, 1.0 - first / max(len(folded_title), 1) * 2.2)

    # 제목이 검색어로 얼마나 채워져 있는가 — 날짜와 무관한 정밀도 신호
    matched_chars = sum(len(token) for token in hit_tokens)
    density = min(1.0, matched_chars / max(len(clean_title), 1) * 2.2)

    score = (0.08
             + title_coverage * 0.34
             + exact * 0.22
             + head * 0.10
             + density * 0.14
             + summary_coverage * 0.12)
    return round(min(0.99, max(0.01, score)), 3)


def rescore(item: dict[str, Any], keywords: list[str] | None = None) -> float:
    """여러 검색어에 걸린 기사를 그 검색어 전부에 대해 다시 채점한다.

    두 개 이상의 보고서 키워드에 동시에 걸린 기사는 보고서 주제에 더
    가깝다고 보고 가산한다 (검색어 하나만 걸린 기사와 확실히 갈리도록).
    """
    terms = [k for k in (keywords or item.get("matched_keywords") or []) if k]
    if not terms:
        return float(item.get("score") or 0)
    title, summary = item.get("title", ""), item.get("summary", "")
    best = max(relevance_score(title, summary, term) for term in terms)
    bonus = min(0.10, 0.05 * (len(terms) - 1))
    return round(min(0.99, best + bonus), 3)


def _article_time(item: dict[str, Any]) -> float:
    published = str(item.get("published_at") or "").strip()
    if published:
        try:
            return datetime.fromisoformat(published.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass

    # published_at 도입 전 저장된 캐시는 화면용 상대 날짜로 최신순을 복원한다.
    label = str(item.get("date") or "").strip()
    now = datetime.now(timezone.utc)
    if label == "오늘":
        return now.timestamp()
    if label == "어제":
        return now.timestamp() - 86400
    days = re.fullmatch(r"(\d+)일 전(?:\s+\d{2}:\d{2})?", label)
    if days:
        return now.timestamp() - int(days.group(1)) * 86400
    month_day = re.fullmatch(r"(\d{1,2})/(\d{1,2})", label)
    if month_day:
        try:
            candidate = datetime(now.year, int(month_day.group(1)), int(month_day.group(2)), tzinfo=timezone.utc)
            if candidate > now:
                candidate = candidate.replace(year=now.year - 1)
            return candidate.timestamp()
        except ValueError:
            pass
    return 0


def sort_articles(items: list[dict[str, Any]], order: str = "accuracy") -> list[dict[str, Any]]:
    """기사 목록을 정확순 또는 최신순으로 정렬한다.

    - 최신순: 발행 시각 → 관련도. 시각이 없는 과거 캐시는 맨 뒤로.
    - 정확순: 관련도 → **걸린 검색어 수** → 제목이 짧은 순 → 발행 시각.
      동점일 때 곧장 시각으로 넘어가면 정확순이 최신순과 같아지므로,
      날짜와 무관한 근거를 먼저 쓴다.
    """
    copied = list(items or [])
    if order == "latest":
        return sorted(
            copied,
            key=lambda item: (_article_time(item), float(item.get("score") or 0)),
            reverse=True,
        )
    return sorted(
        copied,
        key=lambda item: (
            float(item.get("score") or 0),
            len(item.get("matched_keywords") or []),
            -len(str(item.get("title") or "")),
            _article_time(item),
        ),
        reverse=True,
    )


# 후보군을 남길 때 쓰는 경과일 구간 — 최근 / 지난주 / 2~4주 전
AGE_BUCKETS: list[tuple[float, float]] = [(0, 7), (7, 14), (14, 1e9)]


def _day_key(item: dict[str, Any]) -> str:
    """기사를 '며칠자'로 묶는 열쇠. 화면용 날짜에 붙은 시각은 떼어 낸다."""
    published = str(item.get("published_at") or "")
    if len(published) >= 10:
        return published[:10]
    # '오늘 14:30' · '3일 전 09:00' → '오늘' · '3일 전'
    return re.sub(r"\s*\d{1,2}:\d{2}$", "", str(item.get("date") or "")).strip()


def balanced_pool(items: list[dict[str, Any]], size: int) -> list[dict[str, Any]]:
    """구간별 정확순 상위 + 최신순 상위를 함께 남긴다.

    한쪽 기준으로만 잘라 캐시에 담으면 다른 정렬을 눌렀을 때 고를 후보가 없어진다.
    게다가 점수가 동점이면 정확순도 결국 시각으로 갈리기 때문에, 그냥 정확순
    상위를 남기면 **후보군 전체가 최근 며칠치로 쪼그라든다**. 그래서 경과일
    구간(`AGE_BUCKETS`)마다 몫을 떼어 각 구간의 정확순 상위를 남긴다.
    한 달 전 기사가 캐시까지 살아남아야 정확순이 한 달을 훑을 수 있다.
    """
    pool = list(items or [])
    if size <= 0 or len(pool) <= size:
        return sort_articles(pool, "accuracy")

    picked: list[dict[str, Any]] = []
    seen: set[int] = set()

    def take(candidates: list[dict[str, Any]], quota: int) -> None:
        for item in candidates:
            if quota <= 0 or len(picked) >= size:
                return
            if id(item) in seen:
                continue
            seen.add(id(item))
            picked.append(item)
            quota -= 1

    # 1) 최신순 몫 — '최신순' 탭이 볼 기사를 확보한다
    take(sort_articles(pool, "latest"), max(1, size // 4))

    # 2) 구간별 정확순 몫 — 오래됐지만 정확한 기사가 살아남는다
    remaining = size - len(picked)
    per_bucket = max(1, remaining // len(AGE_BUCKETS))
    for low, high in AGE_BUCKETS:
        bucket = [item for item in pool if low <= _age_days(item) < high]
        take(sort_articles(bucket, "accuracy"), per_bucket)

    # 3) 남는 자리는 전체 정확순으로 채운다
    take(sort_articles(pool, "accuracy"), size - len(picked))
    return sort_articles(picked, "accuracy")


def spread_by_day(items: list[dict[str, Any]], limit: int,
                  per_day: int = 0) -> list[dict[str, Any]]:
    """정확순 목록에서 같은 날짜가 몰리는 것을 막는다.

    점수가 동점이면 정확순도 마지막엔 시각으로 갈려 상위가 전부 오늘 기사가 된다.
    하루에서 가져올 기사 수에 상한을 두고, 넘치는 기사는 뒤로 미룬다.
    점수 순서 자체는 그대로라 '정확순'의 의미는 유지된다.
    """
    if limit <= 0 or not items:
        return []
    cap = per_day or max(2, limit // 6)
    front: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    used: dict[str, int] = {}
    for item in items:
        day = _day_key(item)
        count = used.get(day, 0)
        if day and count >= cap:
            deferred.append(item)
            continue
        used[day] = count + 1
        front.append(item)
        if len(front) >= limit:
            break
    return (front + deferred)[:limit]


def _window_query(keyword: str, since_days: int, until_days: int) -> str:
    """구글 뉴스 검색어에 기간 연산자를 붙인다.

    `after:` / `before:` 는 날짜 경계를 직접 지정한다. 가장 최근 창(until=0)은
    오늘 기사가 빠지지 않도록 `when:` 을 쓴다 (before:오늘 은 오늘을 제외한다).
    """
    today = datetime.now(timezone.utc).date()
    if until_days <= 0:
        return f"{keyword} when:{since_days}d"
    since = today - timedelta(days=since_days)
    until = today - timedelta(days=until_days)
    return f"{keyword} after:{since.isoformat()} before:{until.isoformat()}"


def _fetch_feed(query: str) -> tuple[list[ElementTree.Element], str]:
    """RSS 한 번 요청. (기사 엘리먼트, 실패 사유) 를 돌려주고 예외는 삼킨다."""
    encoded = urllib.parse.urlencode({"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
    request = urllib.request.Request(f"{RSS_ENDPOINT}?{encoded}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read()
    except (urllib.error.URLError, socket.timeout, OSError) as exc:
        return [], (f"뉴스 서버에 연결하지 못했습니다 ({type(exc).__name__}). "
                    "사내망에서는 외부 접속이 차단될 수 있습니다.")
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return [], "뉴스 응답을 해석하지 못했습니다."
    return root.findall("./channel/item")[:MAX_FEED_ITEMS], ""


def _to_article(entry: ElementTree.Element, keyword: str) -> dict[str, Any] | None:
    title = _strip_tags(entry.findtext("title") or "")
    if not title:
        return None
    source_el = entry.find("source")
    pub = entry.findtext("pubDate") or ""
    summary = _strip_tags(entry.findtext("description") or "")[:300]
    return {
        "type": "news",
        "title": title,
        "source": _strip_tags(source_el.text if source_el is not None else "") or "뉴스",
        "summary": summary,
        "date": _relative_day(pub),
        "published_at": _published_at(pub),
        "link": entry.findtext("link") or "",
        "score": relevance_score(title, summary, keyword),
        "keyword": keyword,
        "matched_keywords": [keyword],
    }


def _age_days(item: dict[str, Any]) -> float:
    """기사가 며칠 전 것인지. 발행 시각을 못 읽으면 0(최근)으로 본다."""
    stamp = _article_time(item)
    if not stamp:
        return 0.0
    return max(0.0, (_now() - stamp) / 86400)


def search(keyword: str, limit: int = 8, lookback_days: int = LOOKBACK_DAYS) -> dict[str, Any]:
    """한 검색어를 기간 창으로 나눠 받아 최근 `lookback_days` 일치를 모은다.

    창을 나누지 않으면 구글 뉴스가 최근 며칠치만 돌려주기 때문에,
    정확순을 눌러도 오늘 기사만 남는다.
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return {"keyword": "", "items": [], "ok": False, "reason": "검색어가 비어 있습니다."}

    requested = min(max(int(limit), 1), 60)
    pool_size = max(40, requested)
    cached = _cache.get(keyword)
    if cached and _now() - cached[0] < CACHE_TTL and int(cached[1].get("pool_size", 0)) >= pool_size:
        out = dict(cached[1])
        out["items"] = list(cached[1].get("items", []))[:requested]
        return out

    from concurrent.futures import ThreadPoolExecutor

    windows = [(since, until) for since, until in SEARCH_WINDOWS if until < lookback_days]
    queries = [_window_query(keyword, min(since, lookback_days), until) for since, until in windows]
    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        fetched = list(pool.map(_fetch_feed, queries))

    by_title: dict[str, dict[str, Any]] = {}
    spread: list[int] = []
    failures = [reason for _, reason in fetched if reason]
    for entries, _ in fetched:
        spread.append(len(entries))
        for entry in entries:
            article = _to_article(entry, keyword)
            if article is None:
                continue
            key = re.sub(r"\W+", "", article["title"].casefold())[:80]
            by_title.setdefault(key, article)

    # 기간 창을 나눠도 창 밖 기사가 섞여 오는 경우가 있어 한 번 더 거른다.
    items = [item for item in by_title.values() if _age_days(item) <= lookback_days + 1]

    if not items:
        reason = failures[0] if failures else "검색 결과가 없습니다."
        return {"keyword": keyword, "items": [], "ok": False, "reason": reason}

    items = balanced_pool(items, pool_size)
    result = {"keyword": keyword, "items": items, "ok": True, "reason": "",
              "pool_size": pool_size, "feed_size": sum(spread),
              "windows": len(queries), "lookback_days": lookback_days}
    _cache[keyword] = (_now(), result)
    out = dict(result)
    out["items"] = balanced_pool(items, requested)
    return out


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


# ── 기관–기술 관계 그래프 ──────────────────────────────────
#
# 예전 그래프는 기술 노드가 '보고서 검색어' 그대로였다. 검색어가 3~4개뿐이라
# 지식맵도 늘 3~4개 가지의 앙상한 별 모양이 됐다. 지금은 기사 제목과 요약에서
# 기술어·기관명을 직접 뽑고, 같은 기사에 함께 나온 것끼리 이어 붙인다.

GRAPH_ARTICLES = 10   # 지식맵을 만들 때 쓰는 상위 기사 수

# 기사에서 찾아낼 기업·기관. 표기가 여러 가지라 대표 이름으로 묶는다.
ORG_PATTERNS: list[tuple[str, str]] = [
    # 국내 대기업
    ("삼성전자", r"삼성전자"), ("삼성SDI", r"삼성\s?SDI"), ("삼성디스플레이", r"삼성디스플레이"),
    ("삼성물산", r"삼성물산"), ("삼성重", r"삼성중공업"),
    ("SK하이닉스", r"SK\s?하이닉스"), ("SK온", r"SK\s?온"), ("SK이노베이션", r"SK\s?이노베이션"),
    ("SK텔레콤", r"SK\s?텔레콤|SKT"), ("SK에코플랜트", r"SK\s?에코플랜트"),
    ("SK E&S", r"SK\s?E&S"), ("SK가스", r"SK\s?가스"), ("SK그룹", r"SK\s?그룹"),
    ("LG에너지솔루션", r"LG\s?에너지솔루션|LG엔솔"), ("LG전자", r"LG전자"),
    ("LG화학", r"LG화학"), ("LG디스플레이", r"LG디스플레이"), ("LG유플러스", r"LG유플러스"),
    ("현대자동차", r"현대차|현대자동차"), ("현대모비스", r"현대모비스"),
    ("현대중공업", r"현대중공업|HD현대"), ("현대건설", r"현대건설"), ("기아", r"기아(?!자)"),
    ("포스코", r"포스코|POSCO"), ("한화", r"한화"), ("두산", r"두산"), ("두산에너빌리티", r"두산에너빌리티"),
    ("효성", r"효성"), ("GS", r"GS칼텍스|GS에너지|GS그룹"), ("롯데", r"롯데케미칼|롯데에너지"),
    ("HMM", r"HMM"), ("대우조선", r"대우조선|한화오션"), ("삼성바이오로직스", r"삼성바이오로직스"),
    ("셀트리온", r"셀트리온"), ("KT", r"\bKT\b"), ("네이버", r"네이버|NAVER"), ("카카오", r"카카오"),
    ("한국전력", r"한국전력|한전(?!건)"), ("한국가스공사", r"한국가스공사|가스공사"),
    ("한국수력원자력", r"한국수력원자력|한수원"), ("한국석유공사", r"석유공사"),
    # 해외 기업
    ("엔비디아", r"엔비디아|NVIDIA"), ("인텔", r"인텔|Intel"), ("TSMC", r"TSMC"),
    ("애플", r"애플|Apple"), ("구글", r"구글|Google"), ("마이크로소프트", r"마이크로소프트|Microsoft"),
    ("메타", r"메타플랫폼|Meta\b"), ("테슬라", r"테슬라|Tesla"), ("도요타", r"도요타|토요타"),
    ("파나소닉", r"파나소닉"), ("CATL", r"CATL"), ("BYD", r"BYD"),
    ("아마존", r"아마존|AWS"), ("오픈AI", r"오픈\s?AI|OpenAI"), ("앤스로픽", r"앤스로픽|Anthropic"),
    ("ASML", r"ASML"), ("AMD", r"\bAMD\b"), ("퀄컴", r"퀄컴|Qualcomm"),
    ("지멘스", r"지멘스|Siemens"), ("GE", r"\bGE\b"), ("보쉬", r"보쉬|Bosch"),
    ("엑슨모빌", r"엑슨모빌|ExxonMobil"), ("셰브론", r"셰브론|Chevron"), ("쉘", r"\b쉘\b|Shell"),
    # 정부·공공·연구기관
    ("산업통상자원부", r"산업통상자원부|산업부"), ("과학기술정보통신부", r"과학기술정보통신부|과기정통부|과기부"),
    ("중소벤처기업부", r"중소벤처기업부|중기부"), ("환경부", r"환경부"), ("국토교통부", r"국토교통부|국토부"),
    ("기획재정부", r"기획재정부|기재부"), ("특허청", r"특허청"), ("조달청", r"조달청"),
    ("KOTRA", r"KOTRA|코트라"), ("KIST", r"\bKIST\b|한국과학기술연구원"),
    ("ETRI", r"\bETRI\b|한국전자통신연구원"), ("KAIST", r"KAIST|카이스트"),
    ("한국생산기술연구원", r"한국생산기술연구원|생기원"), ("한국에너지기술연구원", r"에너지기술연구원"),
    ("한국원자력연구원", r"원자력연구원"), ("국제에너지기구", r"국제에너지기구|\bIEA\b"),
]

# 사전에 없는 기업·기관을 잡아내는 접미사 패턴
ORG_SUFFIX = re.compile(
    r"([가-힣A-Za-z]{2,10}(?:전자|화학|에너지|중공업|건설|제철|바이오|반도체|모빌리티|솔루션|시스템즈"
    r"|테크|텍|일렉트로닉스|머티리얼즈|그룹|지주|은행|증권|보험|물산|해운|항공|조선|제약|정밀"
    r"|공사|공단|협회|재단|연구원|연구소|진흥원|과학기술원|대학교|산업부|중기부|과기부))"
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

# 기사에서 찾아낼 기술·산업 주제어. 표기 흔들림을 대표어로 묶는다.
TECH_PATTERNS: list[tuple[str, str]] = [
    ("AI", r"\bAI\b|인공지능|에이아이"), ("생성형 AI", r"생성형\s?AI|제너레이티브"),
    ("거대언어모델", r"\bLLM\d*|거대언어모델|초거대\s?AI"), ("AI반도체", r"AI\s?반도체|신경망처리|\bNPU\b"),
    ("반도체", r"반도체"), ("HBM", r"\bHBM\d*|고대역폭"), ("파운드리", r"파운드리"),
    ("메모리", r"D램|디램|낸드|메모리반도체"), ("디스플레이", r"디스플레이|OLED"),
    ("배터리", r"배터리|이차전지|2차전지"), ("전고체", r"전고체"), ("전기차", r"전기차|\bEV\b"),
    ("충전인프라", r"충전\s?인프라|충전소"), ("자율주행", r"자율주행"), ("모빌리티", r"모빌리티|\bUAM\b"),
    ("로봇", r"로봇|로보틱스"), ("스마트팩토리", r"스마트\s?팩토리|스마트공장"),
    ("자율제조", r"자율제조"), ("디지털트윈", r"디지털\s?트윈"), ("제조AI", r"제조\s?AI"),
    ("데이터센터", r"데이터\s?센터"), ("클라우드", r"클라우드"), ("양자컴퓨팅", r"양자\s?컴퓨|퀀텀"),
    ("5G·6G", r"\b5G\b|\b6G\b"), ("사물인터넷", r"\bIoT\b|사물인터넷"), ("사이버보안", r"사이버\s?보안|정보보호"),
    ("수소", r"수소"), ("암모니아", r"암모니아"), ("LNG", r"\bLNG\b|액화천연가스"),
    ("SMR", r"\bSMR\b|\bSMR-\d+|소형모듈원자로"), ("원자력", r"원자력|원전"),
    ("재생에너지", r"재생에너지|신재생"),
    ("태양광", r"태양광"), ("풍력", r"풍력"), ("ESS", r"\bESS\b|에너지저장"),
    ("전력망", r"전력망|송배전|그리드"), ("탄소중립", r"탄소중립|넷제로|\bCCUS\b|탄소포집"),
    ("ESG", r"\bESG\b"), ("바이오", r"바이오|신약|제약"), ("우주·위성", r"위성|우주항공"),
    ("방산", r"방산|\bK-?방산\b"), ("공급망", r"공급망|밸류체인|서플라이"),
    ("소부장", r"소부장|소재부품장비"), ("디지털전환", r"디지털\s?전환|\bDX\b"),
]
# 사전에 없는 기술어를 잡는 접미사 (2건 이상 나온 것만 노드로 승격한다)
TECH_SUFFIX = re.compile(
    r"([가-힣A-Za-z]{2,8}(?:기술|산업|시장|플랫폼|인프라|소재|부품|장비|공정|시스템|생태계|밸류체인|공급망))"
)
# 기술어로 쓰기엔 너무 넓은 말
TECH_STOP = {"관련산업", "전체산업", "국내시장", "해외시장", "글로벌시장", "국내산업", "해당기술", "기존기술"}


def _drop_contained(names: list[str]) -> list[str]:
    """다른 이름에 통째로 들어 있는 짧은 이름을 지운다.

    '두산' 과 '두산에너빌리티' 가 함께 잡히면 노드가 둘로 갈라져 지식맵이 지저분해진다.
    더 구체적인 쪽만 남긴다.
    """
    return [name for name in names
            if not any(other != name and name in other for other in names)]


def _looks_like_tech(name: str) -> bool:
    """'수소환원제철' 처럼 기관 접미사에 걸렸지만 실은 기술어인 경우를 걸러 낸다."""
    return _is_tech_term(name)


def _relax_boundaries(pattern: str) -> str:
    r"""정규식의 `\b` 를 한국어에서도 통하는 전후방 탐색으로 바꾼다.

    파이썬의 `\b` 는 낱말 문자 경계인데 한글도 낱말 문자다. 그래서
    `\bAI\b` 는 "AI가 바꾼다" 의 AI 를 **못 잡는다** (I 와 가 사이에 경계가 없다).
    영문·숫자만 이웃으로 막고 한글은 허용하도록 바꿔 준다.
    """
    pattern = re.sub(r"\\b(?=[A-Za-z0-9])", "(?<![A-Za-z0-9])", pattern)
    pattern = re.sub(r"(?<=[A-Za-z0-9])\\b", "(?![A-Za-z0-9])", pattern)
    return pattern


# 사전은 한 번만 컴파일한다 (기사마다 수십 개 패턴을 돌리므로)
_ORG_RE = [(name, re.compile(_relax_boundaries(pattern)))
           for name, pattern in ORG_PATTERNS]
_TECH_RE = [(name, re.compile(_relax_boundaries(pattern), re.IGNORECASE))
            for name, pattern in TECH_PATTERNS]


def extract_orgs(text: str, limit: int = 4) -> list[str]:
    """기사에서 기업·기관 이름을 뽑는다 (사전 → 접미사 → 문장 주체 순)."""
    found: list[str] = []
    for name, pattern in _ORG_RE:
        if pattern.search(text) and name not in found:
            found.append(name)
    found = _drop_contained(found)

    for match in ORG_SUFFIX.findall(text):
        if match in found or len(match) < 3 or _looks_like_tech(match):
            continue
        found.append(match)
    found = _drop_contained(found)

    if not found:
        head = SUBJECT_HEAD.match(text)
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
    return found[:limit]


# 예전 이름 (호출부 호환)
extract_companies = extract_orgs


def extract_techs(text: str, limit: int = 5) -> list[str]:
    """기사에서 기술·산업 주제어를 뽑는다 (사전 → 접미사 자동 추출)."""
    found: list[str] = []
    for name, pattern in _TECH_RE:
        if pattern.search(text) and name not in found:
            found.append(name)

    for match in TECH_SUFFIX.findall(text):
        token = match.strip()
        if token in TECH_STOP or token in found or len(token) < 4:
            continue
        # 이미 사전 용어로 잡힌 개념이면 중복 노드를 만들지 않는다
        if any(name in token for name in found):
            continue
        found.append(token)
    return found[:limit]


def _is_tech_term(name: str) -> bool:
    """이름 하나가 기술어 사전에 걸리는지 (기관/기술 판별용)."""
    return any(pattern.search(name) for _, pattern in _TECH_RE)


def build_graph(items: list[dict[str, Any]], unit_name: str,
                max_orgs: int = 12, max_techs: int = 14) -> dict[str, Any]:
    """상위 기사에서 기관–기술 관계 그래프를 만든다.

    무엇을 노드로 삼는가
      - 기술·산업 주제어: 사전(`TECH_PATTERNS`) + 접미사 자동 추출 + 보고서 검색어.
        예전에는 보고서 검색어만 썼기 때문에 가지가 3~4개뿐이었다.
      - 기업·기관: 사전(`ORG_PATTERNS`) + 접미사 + 문장 주체.
      제목만 보던 것을 **제목 + 요약**으로 넓혔다.

    무엇을 선으로 잇는가
      - 보고서 ↔ 기술 : 보고서 검색어로 걸린 기술
      - 기관 ↔ 기술   : 같은 기사에 함께 등장 (근거 1건부터)
      - 기술 ↔ 기술   : 같은 기사에 함께 등장 (2건 이상일 때만 — 우연 연결 차단)
      - 기관 ↔ 기관   : 같은 기사에 함께 등장 (2건 이상 — 협력·경쟁 관계 후보)

    **기사 목록과의 연동**: 각 노드에 그 노드를 만든 기사 인덱스(`articles_idx`)를,
    각 기사에는 자기가 속한 노드 id 목록(`node_ids`)을 넣는다. 화면은 이
    두 방향 색인으로 기사 ↔ 노드를 서로 하이라이트한다. 인덱스는 넘겨받은
    `items` 순서 기준이므로 정렬을 바꿔 다시 만들 때마다 함께 갱신된다.
    """
    from collections import defaultdict

    org_hits: dict[str, list[int]] = defaultdict(list)
    tech_hits: dict[str, list[int]] = defaultdict(list)
    seed_techs: set[str] = set()          # 보고서 검색어에서 온 기술 (항상 남긴다)
    org_tech: dict[tuple[str, str], list[int]] = defaultdict(list)
    tech_tech: dict[tuple[str, str], list[int]] = defaultdict(list)
    org_org: dict[tuple[str, str], list[int]] = defaultdict(list)
    per_item_orgs: list[list[str]] = []
    per_item_techs: list[list[str]] = []

    for index, item in enumerate(items):
        title = item.get("title", "")
        text = f"{title} {item.get('summary', '')}"

        keywords = [k for k in (item.get("matched_keywords") or [item.get("keyword", "")]) if k]
        seed_techs.update(keywords)
        techs = list(dict.fromkeys(keywords + extract_techs(text)))
        orgs = extract_orgs(text)
        per_item_techs.append(techs)
        per_item_orgs.append(orgs)

        for tech in techs:
            tech_hits[tech].append(index)
        for org in orgs:
            org_hits[org].append(index)

        for org in orgs:
            for tech in techs:
                org_tech[(org, tech)].append(index)
        for i in range(len(techs)):
            for j in range(i + 1, len(techs)):
                tech_tech[tuple(sorted((techs[i], techs[j])))].append(index)
        for i in range(len(orgs)):
            for j in range(i + 1, len(orgs)):
                org_org[tuple(sorted((orgs[i], orgs[j])))].append(index)

    # 등장 기사 수 상위만 남긴다. 보고서 검색어 기술은 개수와 무관하게 유지.
    ranked_orgs = sorted(org_hits.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:max_orgs]
    ranked_techs = sorted(tech_hits.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    kept_techs = {name for name, _ in ranked_techs[:max_techs]} | (seed_techs & set(tech_hits))
    ranked_techs = [(name, idx) for name, idx in ranked_techs if name in kept_techs]
    kept_orgs = {name for name, _ in ranked_orgs}

    def titles_of(indexes: list[int], take: int = 3) -> list[str]:
        return [items[i].get("title", "") for i in indexes[:take]]

    nodes: list[dict[str, Any]] = [{
        "id": "us", "type": "us", "label": str(unit_name or "").strip(),
        "weight": len(items), "articles": [], "articles_idx": list(range(len(items))),
    }]
    for name, indexes in ranked_orgs:
        nodes.append({"id": f"c:{name}", "type": "company", "label": name,
                      "kind": "기업·기관", "weight": len(indexes),
                      "articles": titles_of(indexes), "articles_idx": indexes})
    for name, indexes in ranked_techs:
        nodes.append({"id": f"t:{name}", "type": "tech", "label": name,
                      "kind": "보고서 키워드" if name in seed_techs else "기사에서 추출",
                      "weight": len(indexes), "articles": titles_of(indexes),
                      "articles_idx": indexes})

    links: list[dict[str, Any]] = []

    def link(source: str, target: str, label: str, indexes: list[int], relation: str) -> None:
        links.append({"source": source, "target": target, "label": label,
                      "weight": len(indexes), "relation_type": relation,
                      "articles": titles_of(indexes), "articles_idx": indexes})

    for name, indexes in ranked_techs:
        if name in seed_techs:
            link("us", f"t:{name}", "보고서 키워드", indexes, "extracted")
    for (org, tech), indexes in org_tech.items():
        if org in kept_orgs and tech in kept_techs:
            link(f"c:{org}", f"t:{tech}", f"기사 {len(indexes)}건", indexes, "extracted")
    # 동시 등장 관계는 근거가 2건 이상일 때만 — 한 기사에서 우연히 겹친 것은 뺀다
    for (a, b), indexes in tech_tech.items():
        if len(indexes) >= 2 and a in kept_techs and b in kept_techs:
            link(f"t:{a}", f"t:{b}", f"함께 언급 {len(indexes)}건", indexes, "co_occurrence")
    for (a, b), indexes in org_org.items():
        if len(indexes) >= 2 and a in kept_orgs and b in kept_orgs:
            link(f"c:{a}", f"c:{b}", f"함께 언급 {len(indexes)}건", indexes, "co_occurrence")

    # 보고서 검색어가 아닌 기술은 중앙 노드와 직접 연결이 없다. 어디에도 붙지 못한
    # 노드는 떠 있게 되므로 중앙에 약한 선으로 매달아 준다.
    connected = {node_id for l in links for node_id in (l["source"], l["target"])}
    for name, indexes in ranked_techs:
        if f"t:{name}" not in connected:
            link("us", f"t:{name}", "기사에서 추출", indexes, "seed")
    for name, indexes in ranked_orgs:
        if f"c:{name}" not in connected:
            link("us", f"c:{name}", "기사에서 추출", indexes, "seed")

    # 잘려 나간 노드는 기사 쪽 색인에서도 지운다 (없는 노드를 가리키지 않도록)
    live = {node["id"] for node in nodes}
    for index, item in enumerate(items):
        ids = [f"t:{t}" for t in per_item_techs[index]] + [f"c:{o}" for o in per_item_orgs[index]]
        item["node_ids"] = [nid for nid in dict.fromkeys(ids) if nid in live]

    return {"nodes": nodes, "links": links}


def _short(text: str, limit: int) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def search_many(keywords: list[str], per_keyword: int = 30, limit: int = 60,
                lookback_days: int = LOOKBACK_DAYS) -> dict[str, Any]:
    """여러 키워드의 넓은 후보군을 합쳐 두 정렬 방식이 공유하도록 만든다.

    합칠 때 같은 기사가 여러 검색어에 걸리면 걸린 검색어 전부로 다시 채점한다
    (`rescore`). 예전에는 점수에 +0.04 만 더했는데, 그러면 보고서 주제에
    정면으로 맞는 기사와 스쳐 지나간 기사가 거의 같은 점수가 됐다.
    """
    from concurrent.futures import ThreadPoolExecutor

    terms = keywords[:5]
    if not terms:
        return {"items": [], "keywords": [], "ok": False, "reason": "검색할 키워드가 없습니다."}
    with ThreadPoolExecutor(max_workers=min(5, len(terms))) as pool:
        results = list(pool.map(lambda k: search(k, per_keyword, lookback_days), terms))

    merged_by_title: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    counts: list[dict[str, Any]] = []
    for keyword, result in zip(terms, results):
        if not result["ok"]:
            failures.append(result["reason"])
            counts.append({"keyword": keyword, "count": 0})
            continue
        counts.append({"keyword": keyword, "count": len(result["items"])})
        for item in result["items"]:
            key = re.sub(r"\W+", "", item["title"].casefold())[:80]
            current = merged_by_title.get(key)
            if current is None:
                merged_by_title[key] = {**item, "keyword": keyword, "matched_keywords": [keyword]}
                continue
            matched = current.setdefault("matched_keywords", [])
            if keyword not in matched:
                matched.append(keyword)
            if _article_time(item) > _article_time(current):
                current["published_at"] = item.get("published_at", "")
                current["date"] = item.get("date", "")
    merged = list(merged_by_title.values())
    for item in merged:
        item["score"] = rescore(item)
        item["keyword"] = " · ".join(item.get("matched_keywords", [])[:2])
    merged = balanced_pool(merged, limit)
    return {
        "items": merged,
        "keywords": counts,
        "ok": bool(merged) or not failures,
        "reason": failures[0] if failures and not merged else "",
        "lookback_days": lookback_days,
        "version": CACHE_VERSION,
    }
