"""검색·분류 공용 어휘 사전.

특정 질문·특정 보고서용 규칙을 코드 여기저기에 하드코딩하지 않기 위해
언어 자원을 한곳에 모은다.

- 동의어: config/synonyms.yaml (팀원이 코드 수정 없이 추가 가능)
- 불용어·조사·요청 표현: 한국어 일반 패턴 (문서 도메인과 무관)
- 구조 페이지 패턴: 표지·목차 등 문서 일반 구조 (회사명 규칙 아님)
"""
from __future__ import annotations

import re
from functools import lru_cache

from app import config

# ── 요청 표현 — 검색 변별력이 없어 질문에서 제거한다 ─────────
REQUEST_WORDS = {
    "알려줘", "알려주세요", "말해줘", "말해주세요", "설명해줘", "설명해주세요",
    "정리해줘", "정리해주세요", "요약해줘", "찾아줘", "찾아주세요", "보여줘",
    "궁금해", "궁금합니다", "해줘", "해주세요", "주세요", "부탁해",
    "뭐야", "뭔가요", "무엇인가요", "무엇이야", "뭐지", "어때", "어떤가요",
    "있나요", "인가요", "일까", "할까",
    "보고서", "페이지", "내용", "관련", "부분", "여기", "이거", "그거",
}

# 토큰 끝에 붙는 조사 — 2글자 이상 어근이 남을 때만 떼어낸다
_PARTICLES = ("에서의", "에게서", "으로써", "으로서", "이라는", "라는", "에서",
              "에게", "으로", "까지", "부터", "처럼", "보다", "이나", "든지",
              "은", "는", "이", "가", "을", "를", "의", "에", "와", "과",
              "도", "만", "로", "요", "야")

# ── 구조 페이지(표지·목차·간지·마무리) — 문서 일반 패턴 ─────
STRUCTURAL_TITLE_RE = re.compile(
    r"^(목차|차례|contents?|agenda|index|appendix|부록|감사합니다|thank\s*you|q\s*&\s*a|끝)$",
    re.IGNORECASE)


def strip_particle(token: str) -> str:
    """조사를 뗀 어근을 돌려준다. 어근이 2글자 미만이 되면 원형 유지."""
    for p in _PARTICLES:
        if token.endswith(p) and len(token) - len(p) >= 2:
            return token[: -len(p)]
    return token


_TOKEN_RE = re.compile(r"[0-9a-zA-Z가-힣.%]+")


def tokenize(text: str) -> list[str]:
    """소문자 단어 토큰. 조사 제거 포함."""
    return [strip_particle(t.lower()) for t in _TOKEN_RE.findall(text or "")]


def content_tokens(text: str) -> list[str]:
    """검색 변별력이 있는 토큰만 — 요청어·1글자 제거."""
    return [t for t in tokenize(text) if len(t) >= 2 and t not in REQUEST_WORDS]


@lru_cache(maxsize=1)
def synonym_groups() -> list[list[str]]:
    """config/synonyms.yaml 의 동의어 그룹. 파일이 없거나 깨져도 빈 목록으로 동작."""
    path = config.CONFIG_DIR / "synonyms.yaml"
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        groups = [[str(w).lower().replace(" ", "") for w in g]
                  for g in (data.get("groups") or {}).values() if isinstance(g, list)]
        return [g for g in groups if len(g) >= 2]
    except Exception:  # noqa: BLE001 — 사전 로드 실패가 검색을 막으면 안 된다
        return []


def expand_terms(terms: list[str]) -> list[str]:
    """동의어 그룹을 적용해 확장 토큰을 돌려준다 (원 토큰 제외)."""
    expanded: list[str] = []
    seen = set(terms)
    for group in synonym_groups():
        if any(t in group for t in terms):
            for w in group:
                if w not in seen:
                    expanded.append(w)
                    seen.add(w)
    return expanded
