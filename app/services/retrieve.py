"""슬라이드 검색 v2 — 하이브리드 TF-IDF + 콘텐츠 가중치.

v1(sklearn char 2-4gram)의 문제:
  - 조사·요청어("알려줘", "보고서")까지 매칭에 참여
  - 표지·목차처럼 내용이 없는 페이지가 짧은 문서 길이 때문에 상위 랭크
  - 동의어·중복 제거·내용 품질 반영 없음

v2 설계 (특정 보고서·회사 전용 규칙 없음):
  - 질문 정제: 조사·요청 표현 제거 (lexicon)
  - 동의어 확장: config/synonyms.yaml 그룹을 절반 가중치로 함께 검색
  - 점수 = 0.45×단어 TF-IDF 코사인 + 0.55×문자 2·3그램 코사인
  - 콘텐츠 가중치: 본문·표·수치가 실한 페이지 가점,
    표지(1페이지)·목차·간지·내용 빈약 페이지 감점
  - 거의 동일한 페이지는 중복 제거

순수 파이썬 구현 — 13페이지 수준 문서에는 외부 라이브러리가 필요 없고,
개발 환경 어디서든 동일하게 동작·테스트된다.
"""
from __future__ import annotations

import math
import re
from typing import Any

from app.services import lexicon

# 이 값 미만은 노이즈로 보고 근거로 제시하지 않는다 (콘텐츠 가중치 적용 후 기준)
MIN_SCORE = 0.06
# 이 값 이상이면 질문과 직접 관련이 있다고 본다 (충분성 판단용)
STRONG_SCORE = 0.22


# ── 슬라이드 → 텍스트 ────────────────────────────────────────

def slide_document(slide: dict[str, Any]) -> str:
    """검색·프롬프트용 평탄화 텍스트 (제목·요약·본문·표·근거 문장)."""
    parts = [slide.get("page_title", ""), slide.get("summary", "")]
    parts.extend(item.get("text", "") for item in slide.get("body", []))
    for key in ("table1", "table2"):
        table = slide.get(key)
        if table:
            parts.extend(table.get("headers", []))
            for row in table.get("rows", []):
                parts.extend(row)
    parts.extend(e.get("quote", "") for e in slide.get("evidence", []))
    return " ".join(str(x) for x in parts if x)


def _body_and_table_text(slide: dict[str, Any]) -> str:
    parts = [item.get("text", "") for item in slide.get("body", [])]
    for key in ("table1", "table2"):
        table = slide.get(key)
        if table:
            parts.extend(table.get("headers", []))
            for row in table.get("rows", []):
                parts.extend(row)
    return " ".join(str(x) for x in parts if x)


# ── 질문 분석 ────────────────────────────────────────────────

def query_terms(question: str) -> tuple[list[str], list[str]]:
    """(핵심 토큰, 동의어 확장 토큰). 핵심 토큰은 조사·요청어 제거 후."""
    core = lexicon.content_tokens(question)
    return core, lexicon.expand_terms(core)


def term_overlap(slide: dict[str, Any], terms: list[str]) -> list[str]:
    """슬라이드 본문에 실제 등장하는 질문 토큰 목록."""
    text = slide_document(slide).lower().replace(" ", "")
    return [t for t in terms if t in text]


# ── 벡터 계산 (순수 파이썬 TF-IDF) ───────────────────────────

def _char_grams(text: str) -> list[str]:
    grams: list[str] = []
    for word in lexicon.tokenize(text):
        padded = f" {word} "
        for n in (2, 3):
            grams.extend(padded[i:i + n] for i in range(len(padded) - n + 1))
    return grams


def _count(items: list[str], weight: float = 1.0) -> dict[str, float]:
    vec: dict[str, float] = {}
    for it in items:
        vec[it] = vec.get(it, 0.0) + weight
    return vec


def _cosine(qv: dict[str, float], dv: dict[str, float], idf: dict[str, float]) -> float:
    if not qv or not dv:
        return 0.0
    def w(vec: dict[str, float]) -> dict[str, float]:
        return {t: (1 + math.log(c)) * idf.get(t, 1.0) for t, c in vec.items()}
    qw, dw = w(qv), w(dv)
    dot = sum(qw[t] * dw[t] for t in qw.keys() & dw.keys())
    nq = math.sqrt(sum(v * v for v in qw.values()))
    nd = math.sqrt(sum(v * v for v in dw.values()))
    return dot / (nq * nd) if nq and nd else 0.0


def _idf(doc_vecs: list[dict[str, float]]) -> dict[str, float]:
    n = len(doc_vecs)
    df: dict[str, int] = {}
    for vec in doc_vecs:
        for t in vec:
            df[t] = df.get(t, 0) + 1
    return {t: math.log((n + 1) / (d + 0.5)) + 1.0 for t, d in df.items()}


# ── 콘텐츠 가중치 — 내용이 실한 페이지 가점, 구조 페이지 감점 ──

def content_weight(slide: dict[str, Any]) -> float:
    text = _body_and_table_text(slide)
    chars = len(re.sub(r"\s", "", text))
    w = 0.65 + 0.45 * min(1.0, chars / 350)
    if re.search(r"\d", text):
        w += 0.08                                   # 수치가 있는 페이지
    if slide.get("table1") or slide.get("table2"):
        w += 0.07                                   # 표가 있는 페이지
    title = (slide.get("page_title") or "").strip()
    structural = (
        lexicon.STRUCTURAL_TITLE_RE.match(title)    # 목차·간지·마무리 패턴
        or slide.get("slide_number") == 1           # 표지 (문서 일반 구조)
        or chars < 60                               # 내용이 거의 없는 페이지
    )
    if structural:
        w *= 0.45
    return min(w, 1.25)


# ── 검색 ─────────────────────────────────────────────────────

def retrieve(payload: dict[str, Any], question: str, top_k: int = 3,
             ) -> list[tuple[dict[str, Any], float]]:
    """질문과 관련 있는 슬라이드를 (slide, 점수) 목록으로 돌려준다."""
    slides = payload.get("slides", [])
    if not slides:
        return []

    core, expanded = query_terms(question)
    if not core and not expanded:
        core = lexicon.tokenize(question)           # 전부 걸러졌으면 원 토큰으로

    # 단어 벡터 (질문: 핵심 1.0 + 동의어 0.5)
    word_docs = [_count(lexicon.content_tokens(slide_document(s))) for s in slides]
    word_idf = _idf(word_docs)
    word_q = _count(core)
    for t, c in _count(expanded, weight=0.5).items():
        word_q[t] = word_q.get(t, 0.0) + c

    # 문자 벡터 (질문: 정제 토큰만 사용 — 조사·요청어 미포함)
    clean_query = " ".join(core + expanded)
    char_docs = [_count(_char_grams(slide_document(s))) for s in slides]
    char_idf = _idf(char_docs)
    char_q = _count(_char_grams(clean_query))

    scored: list[tuple[dict[str, Any], float]] = []
    seen_keys: set[str] = set()
    for slide, wv, cv in zip(slides, word_docs, char_docs):
        base = 0.45 * _cosine(word_q, wv, word_idf) + 0.55 * _cosine(char_q, cv, char_idf)
        score = base * content_weight(slide)
        # 거의 동일한 페이지(제목+본문 앞부분)는 첫 번째만 남긴다
        key = re.sub(r"\s", "", (slide.get("page_title", "") + slide_document(slide)[:80]).lower())
        if key in seen_keys:
            continue
        seen_keys.add(key)
        scored.append((slide, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[: min(top_k, len(scored))]
