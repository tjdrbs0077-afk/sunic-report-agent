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


def _strip_tags(value: str) -> str:
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
            "title": _strip_tags(item.get("title", "")),
            "summary": _strip_tags(item.get("description", ""))[:220],
            "url": item.get("originallink") or item.get("link", ""),
            "date": _parse_date(item.get("pubDate", "")),
            "source": "네이버 뉴스",
        }
        for item in items
        if _strip_tags(item.get("title", ""))
    ]


def _search_rss(query: str, limit: int) -> list[dict[str, Any]]:
    url = f"{GOOGLE_NEWS_RSS}?q={urllib.parse.quote(query)}&hl=ko&gl=KR&ceid=KR:ko"
    root = ET.fromstring(_fetch(url).decode("utf-8", "replace"))
    results: list[dict[str, Any]] = []
    for item in root.iterfind(".//item"):
        title = _strip_tags(item.findtext("title") or "")
        if not title:
            continue
        results.append({
            "title": title,
            "summary": _strip_tags(item.findtext("description") or "")[:220],
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
