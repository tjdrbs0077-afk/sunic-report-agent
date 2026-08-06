"""⑤ 챗봇 — 근거형 통합 챗봇 (v3).

파이프라인 (모든 질문에 동일하게 적용 — 질문별 하드코딩 없음):
  1. 의도 분류      services/intent.py — 사실/위치/요약/비교/분석/외부
  2. 근거 검색      services/retrieve.py — 하이브리드 TF-IDF + 콘텐츠 가중치
  3. 충분성 판단    점수 + 질문 토큰의 실제 등장 + 페이지 내용 품질
  4. 답변 생성
     - LLM (키 설정 시): 의도별 근거 정책에 따라 관련 페이지 발췌 또는
       보고서 전체를 **구조화**(제목·요약·본문·표·근거문장·점수)해 전달.
       결론 먼저·나열 금지·[p.N] 인용을 시스템 프롬프트로 강제.
       생성 후 존재하지 않는 페이지 인용은 제거(인용 검증).
     - 오프라인 폴백: 제목 나열이 아니라 본문·표에서 질문 토큰과 맞는
       문장을 찾아 직접 답변을 합성. 근거가 부족하면 솔직하게 안내.
  5. 응답 메타      answer_meta — 경로(llm/offline)·폴백 사유·의도·충분성을
                    UI 에 그대로 표시해 "왜 이 답이 나왔는지" 를 밝힌다.

전송 정책 (v2 유지): LLM 사용 시 보고서 발췌/구조화 본문이 Claude API 로
전송되며, 무엇이 나갔는지 disclosure 로 매 답변 공개한다.
⑥ 지식맵과는 연동하지 않는다 — 챗봇 질문은 어디에도 저장되지 않는다.
"""
from __future__ import annotations

import os
import re
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import config
from app.services import intent, knowledge, llm, news, store
from app.services.retrieve import (MIN_SCORE, STRONG_SCORE, content_weight,
                                   query_terms, retrieve, slide_document, term_overlap)

router = APIRouter(prefix="/api", tags=["chat"])

MODE_STYLE = {
    "brief": "2~3문장으로 짧게",
    "easy": "비전공자도 이해할 수 있는 쉬운 표현으로",
    "detail": "배경과 연결관계까지 자세히",
}

# LLM 에 보내는 근거 텍스트 상한 (문자)
MAX_EVIDENCE_CHARS = 18000

REPORT_SYSTEM = """당신은 사내 사업기획 보고서를 검토하고 질문에 답하는 전문 분석가입니다.

답변 원칙:
- 사용자의 질문 의도를 먼저 파악하고, 질문에 대한 답을 첫 문장에 제시하세요.
- 제공된 페이지 제목이나 요약을 그대로 나열하지 마세요. 여러 근거를 종합하여 자연스럽고 구체적인 한국어 답변을 작성하세요.
- 보고서의 사업 내용·수치·계획을 설명할 때는 제공된 보고서 근거만 사용하고, 없는 사실·수치·페이지·관계를 만들지 마세요.
- 개념·정의·원리·과학·기술·산업 배경을 묻는 질문에는 보고서에 직접 설명이 없어도 널리 확립된 일반 지식으로 답하세요.
- 일반 지식으로 답한 부분은 '일반 배경지식'이라고 구분하고 [p.N] 인용을 붙이지 마세요. [p.N]은 실제 보고서 근거에만 사용하세요.
- 배경지식 질문은 '일반적인 직접 답변 → 보고서와의 연결점(있는 경우)' 순서로 답하세요. 보고서에 없다는 이유만으로 답변을 거절하지 마세요.
- 보고서에 근거한 각 핵심 주장 뒤에는 근거 페이지를 [p.N] 형식으로 표시하세요.
- 분석·평가·피드백 질문에는 보고서 근거로 판단 가능한 내용을 분석하세요. 무조건 거절하지 마세요. 다만 보고서에 적힌 사실과 근거를 종합한 해석을 명확히 구분하세요. 해석에는 "보고서 근거를 종합하면" 같은 표현을 쓰세요.
- 근거가 부족하면 부족하다고 말하고 추측하지 마세요.
- 최신 뉴스나 외부 시장 정보처럼 보고서만으로 답할 수 없는 질문에는, 참고 뉴스가 제공된 경우 그것을 [기사 N] 인용으로 사용하고, 없으면 보고서 밖 정보가 필요하다고 안내하세요.
- 답변 구조는 '직접 답변 → 핵심 근거/분석 → 확인할 페이지 → (필요 시) 근거의 한계' 를 참고하되 기계적으로 강제하지 마세요."""


class ChatRequest(BaseModel):
    question: str
    mode: str = "easy"
    report_id: str | None = None
    use_news: bool = True
    # v1 호환 — 무시
    scope: Literal["report", "context"] | None = None


# ──────────────────────────────────────────────────────────────
# 근거 충분성 판단 — 점수 하나가 아니라 세 신호를 함께 본다
# ──────────────────────────────────────────────────────────────

def assess_sufficiency(question: str, found: list[tuple[dict[str, Any], float]],
                       ) -> dict[str, Any]:
    """{level: sufficient|partial|insufficient, matched_terms, top_score}"""
    core, expanded = query_terms(question)
    terms = core + expanded
    if not found:
        return {"level": "insufficient", "matched_terms": [], "top_score": 0.0}
    top_slide, top_score = found[0]
    matched: list[str] = []
    for slide, score in found[:3]:
        if score >= MIN_SCORE:
            matched.extend(term_overlap(slide, terms))
    matched = list(dict.fromkeys(matched))
    # 실질 콘텐츠 페이지에서 질문 토큰이 실제로 확인되는가
    solid_hit = any(score >= MIN_SCORE and content_weight(slide) >= 0.6
                    and term_overlap(slide, terms)
                    for slide, score in found[:3])
    if (top_score >= STRONG_SCORE and matched) or top_score >= 0.35:
        level = "sufficient"
    elif solid_hit or (top_score >= MIN_SCORE and matched):
        level = "partial"
    else:
        level = "insufficient"
    return {"level": level, "matched_terms": matched, "top_score": round(top_score, 3)}


# ──────────────────────────────────────────────────────────────
# LLM 경로 — 구조화 근거 + 의도별 지침
# ──────────────────────────────────────────────────────────────

def _slide_block(slide: dict[str, Any], score: float | None = None) -> str:
    lines = [f"[p.{slide.get('slide_number')}] 제목: {slide.get('page_title', '')}"
             + (f"  (검색 점수 {score:.2f})" if score is not None else "")]
    if slide.get("summary"):
        lines.append(f"요약: {slide['summary']}")
    body = [b.get("text", "") for b in slide.get("body", []) if b.get("text")]
    if body:
        lines.append("본문: " + " / ".join(body))
    for key in ("table1", "table2"):
        table = slide.get(key)
        if table and table.get("rows"):
            head = " | ".join(table.get("headers", []))
            rows = " ; ".join(" | ".join(r) for r in table["rows"])
            lines.append(f"표({head}): {rows}")
    quotes = [e.get("quote", "") for e in slide.get("evidence", []) if e.get("quote")]
    if quotes:
        lines.append("근거 문장: " + " / ".join(f"“{q}”" for q in dict.fromkeys(quotes)))
    return "\n".join(lines)


def _evidence_blocks(payload: dict[str, Any], found: list[tuple[dict[str, Any], float]],
                     scope: str) -> tuple[str, str]:
    """(근거 텍스트, 설명 라벨). scope=full 이면 전체, retrieved 면 관련 페이지만."""
    slides = payload.get("slides", [])
    scores = {s["slide_number"]: sc for s, sc in found}
    if scope == "full":
        blocks = [_slide_block(s, scores.get(s["slide_number"])) for s in slides]
        label = f"보고서 구조화 본문 전체 {len(slides)}페이지"
    else:
        picked = [(s, sc) for s, sc in found if sc >= MIN_SCORE] or found[:2]
        blocks = [_slide_block(s, sc) for s, sc in picked]
        label = f"관련 페이지 발췌 {len(blocks)}건 (p.{', p.'.join(str(s['slide_number']) for s, _ in picked)})"
    text = "\n\n".join(blocks)
    if len(text) > MAX_EVIDENCE_CHARS:
        text = text[:MAX_EVIDENCE_CHARS] + "\n(분량 제한으로 이후 페이지 생략 — 답변에서 이 사실을 밝히세요)"
    return text, label


def _llm_prompt(question: str, mode: str, it: dict[str, Any],
                report_name: str | None, evidence: str | None,
                sufficiency: dict[str, Any] | None,
                articles: list[dict[str, Any]]) -> str:
    parts: list[str] = [f"[질문 유형] {it['label']} — {it['guidance']}"]
    if it["name"] == "background":
        parts.append(
            "[배경지식 답변 정책] 보고서에 해당 정의나 원리가 없어도 답변해야 합니다. "
            "확립된 일반 지식으로 질문에 직접 답하고, 그 부분에는 페이지 인용을 만들지 마세요. "
            "제공된 보고서 근거는 사업 맥락을 덧붙일 때만 사용하세요.")
    if evidence:
        parts.append(f"[보고서: {report_name}]\n{evidence}")
        if sufficiency and sufficiency["level"] != "sufficient":
            if it["name"] == "background":
                parts.append(
                    "[근거 상태] 보고서 근거는 배경 개념과 직접 관련성이 낮을 수 있습니다. "
                    "일반 배경지식 답변은 충분히 제공하고, 보고서와 실제로 연결되는 내용만 별도로 인용하세요.")
            else:
                parts.append("[근거 상태] 검색된 근거가 " +
                             ("부분적입니다. 확인되는 범위만 답하고 부족한 부분은 부족하다고 밝히세요."
                              if sufficiency["level"] == "partial" else
                              "질문과 직접 관련성이 낮습니다. 억지로 답하지 말고, 보고서에서 확인되지 않는다고 "
                              "밝힌 뒤 가장 가까운 참고 내용만 안내하세요."))
    if articles:
        block = "\n\n".join(
            f"[기사 {i}] {a['title']} ({a.get('source', '')} {a.get('date', '')})\n{a.get('summary', '')}"
            for i, a in enumerate(articles, 1))
        parts.append(f"[참고 뉴스]\n{block}")
    parts.append(f"[질문]\n{question}")
    parts.append(f"{MODE_STYLE.get(mode, MODE_STYLE['easy'])} 답하세요.")
    return "\n\n".join(parts)


_CITE_RE = re.compile(r"\[p\.(\d+)\]")


def validate_citations(answer: str, payload: dict[str, Any] | None) -> tuple[str, str | None]:
    """존재하지 않는 페이지 인용을 제거한다 (환각 방지)."""
    if not payload or not answer:
        return answer, None
    valid = {s.get("slide_number") for s in payload.get("slides", [])}
    bad = sorted({int(n) for n in _CITE_RE.findall(answer) if int(n) not in valid})
    if not bad:
        return answer, None
    cleaned = _CITE_RE.sub(lambda m: "" if int(m.group(1)) in bad else m.group(0), answer)
    return cleaned, f"존재하지 않는 페이지 인용 {bad} 를 답변에서 제거했습니다."


# ──────────────────────────────────────────────────────────────
# 오프라인 폴백 — 제목 나열이 아니라 본문에서 직접 답을 찾는다
# ──────────────────────────────────────────────────────────────

def _matching_lines(found: list[tuple[dict[str, Any], float]], terms: list[str],
                    limit: int = 4) -> list[tuple[int, str]]:
    """관련 페이지의 본문·표에서 질문 토큰이 등장하는 줄을 (페이지, 줄) 로 수집."""
    hits: list[tuple[float, int, str]] = []
    for slide, score in found:
        if score < MIN_SCORE:
            continue
        page = slide.get("slide_number")
        lines = [b.get("text", "") for b in slide.get("body", [])]
        for key in ("table1", "table2"):
            table = slide.get(key)
            if table:
                for row in table.get("rows", []):
                    lines.append(" — ".join(row))
        for line in lines:
            if not line or len(line) < 4:
                continue
            flat = line.lower().replace(" ", "")
            n_hit = sum(1 for t in terms if t in flat)
            if n_hit:
                rank = n_hit + (0.5 if re.search(r"\d", line) else 0) + min(len(line), 80) / 400
                hits.append((rank, page, line.strip()))
    hits.sort(key=lambda x: (-x[0], x[1]))
    out, seen = [], set()
    for _, page, line in hits:
        key = line.replace(" ", "")[:40]
        if key in seen:
            continue
        seen.add(key)
        out.append((page, line))
        if len(out) >= limit:
            break
    return out


def _offline_report_answer(question: str, it: dict[str, Any], payload: dict[str, Any],
                           found: list[tuple[dict[str, Any], float]],
                           sufficiency: dict[str, Any]) -> str:
    relevant = [(s, sc) for s, sc in found if sc >= MIN_SCORE]
    pages_note = ", ".join(f"[p.{s['slide_number']}] ‘{s['page_title']}’" for s, _ in relevant[:3])

    if sufficiency["level"] == "insufficient":
        answer = "이 질문에 대한 내용은 보고서에서 직접 확인되지 않습니다."
        if relevant:
            answer += f" 가장 가까운 참고 페이지는 {pages_note} 이지만, 질문에 대한 답으로 보기는 어렵습니다."
        answer += " 보고서 밖 정보가 필요한 질문이라면 아래 버튼으로 뉴스 검색을 이용해 보세요."
        return answer

    core, expanded = query_terms(question)
    lines = _matching_lines(found, core + expanded)

    if it["name"] == "location":
        # 목차·표지 같은 구조 페이지는 위치 안내에서 제외한다
        solid = [(s, sc) for s, sc in relevant if content_weight(s) >= 0.6] or relevant
        return ("관련 내용은 " + ", ".join(
            f"{s['slide_number']}페이지 ‘{s['page_title']}’" for s, _ in solid[:3]) +
            " 에 있습니다.") if solid else "관련 페이지를 찾지 못했습니다."

    if it["name"] == "summary":
        # 내용이 실한 페이지의 핵심 줄로 종합 (구조 페이지 제외)
        picks = []
        for slide in payload.get("slides", []):
            if content_weight(slide) < 0.6:
                continue
            title = (slide.get("page_title") or "").strip()
            # 제목 반복·섹션 번호(예: "03. MARKET")가 아닌 실제 내용 줄을 고른다
            body = [b.get("text", "") for b in slide.get("body", [])
                    if b.get("text") and b["text"].strip() != title
                    and not re.match(r"^\d{2}\.\s*[A-Z &]+$", b["text"].strip())]
            if body:
                picks.append((slide["slide_number"], f"{title}: {body[0]}" if title else body[0]))
        head = f"‘{payload.get('unit', {}).get('name', '보고서')}’ 의 핵심 내용입니다. "
        parts = [f"{txt} [p.{n}]" for n, txt in picks[:5]]
        return head + " · ".join(parts) + (
            "\n\n※ 오프라인 발췌 요약입니다. API 키 설정 시 주제별로 종합된 요약이 제공됩니다.")

    if lines:  # fact · analysis · compare 공통 — 본문에서 직접 답을 찾는다
        body = " ".join(f"{line} [p.{page}]" for page, line in lines[:3])
        if it["name"] == "analysis":
            answer = ("보고서 근거를 종합하면(오프라인 발췌 기반) 다음 내용이 판단에 관련됩니다: "
                      + body +
                      " ※ 이는 보고서 발췌이며, 종합 분석·평가는 API 키 설정 시 제공됩니다.")
        elif it["name"] == "compare":
            answer = ("비교에 활용할 수 있는 보고서 근거입니다: " + body +
                      " ※ 보고서에 한쪽 근거만 있다면 비교가 제한적일 수 있습니다.")
        else:
            answer = f"보고서에 따르면 {body}"
        if sufficiency["level"] == "partial":
            answer += " (질문과의 관련도가 높지 않아 참고 수준입니다.)"
        return answer

    # 매칭 줄이 없으면 정직하게
    answer = "질문에 딱 맞는 문장은 찾지 못했습니다."
    if pages_note:
        answer += f" 관련 가능성이 있는 페이지는 {pages_note} 입니다. 페이지를 열어 직접 확인해 주세요."
    return answer


def _offline_news_answer(feed: dict[str, Any]) -> str:
    articles = feed["articles"]
    if not articles:
        return ("보고서 밖 최신 정보가 필요한 질문입니다. 뉴스 검색에서도 결과를 얻지 못했습니다. "
                f"({feed.get('error') or '사유 미상'})")
    lines = [f"‘{feed['sent_query']}’ 로 검색한 최근 기사 {len(articles)}건입니다. "
             "요약 답변은 API 키 설정 시 제공됩니다.\n"]
    for i, article in enumerate(articles, 1):
        lines.append(f"[{i}] {article['title']} ({article.get('date') or '날짜 미상'})")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# 엔드포인트
# ──────────────────────────────────────────────────────────────

@router.post("/chat")
def chat(req: ChatRequest):
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="질문이 비어 있습니다.")

    # 1) 의도 분류
    it = intent.classify(question)

    # 2) 근거 검색 + 충분성 판단
    payload = store.report_payload(req.report_id) if req.report_id else None
    found = retrieve(payload, question, top_k=it["top_k"]) if payload else []
    sufficiency = assess_sufficiency(question, found) if payload else None
    relevant = [(s, sc) for s, sc in found if sc >= MIN_SCORE]

    # 3) 뉴스 — 외부형 질문이거나 보고서가 없을 때만 검색어를 내보낸다
    need_news = req.use_news and (
        it["name"] == "external" or (not payload and it["name"] != "background"))
    query = news.extract_query(question)
    feed = (news.search_news(query, limit=5) if need_news
            else {"articles": [], "channel": "off", "sent_query": query, "error": None})
    articles = feed["articles"]

    notices: list[str] = []
    suggestion: dict[str, Any] | None = None
    answer: str | None = None
    evidence_label: str | None = None
    fallback_reason: str | None = None

    # 4) 답변 생성 — LLM 우선
    if llm.is_enabled():
        evidence, report_name = None, None
        if payload:
            report_name = payload.get("unit", {}).get("name", req.report_id)
            evidence, evidence_label = _evidence_blocks(payload, found, it["scope"])
        try:
            answer = llm.complete(
                REPORT_SYSTEM,
                _llm_prompt(question, req.mode, it, report_name, evidence, sufficiency, articles))
            if answer:
                answer, cite_note = validate_citations(answer, payload)
                if cite_note:
                    notices.append(cite_note)
        except llm.LLMError as exc:
            fallback_reason = f"LLM 호출 실패: {exc}"
            evidence_label = None
    else:
        fallback_reason = "API 키 미설정"

    # 5) 오프라인 폴백 — 나열이 아니라 직접 답변 합성
    if not answer:
        if payload and it["name"] != "external":
            answer = _offline_report_answer(question, it, payload, found, sufficiency)
            if sufficiency["level"] == "insufficient" or it["name"] == "external":
                suggestion = {"scope": "context", "question": question}
        else:
            answer = _offline_news_answer(feed)
            if payload:
                suggestion = None  # 이미 뉴스 목록으로 답함
        if it["name"] == "external" and payload:
            suggestion = suggestion or {"scope": "context", "question": question}

    if need_news and feed.get("error"):
        notices.append(f"뉴스 수집 실패 — {feed['error']}")
    internal = knowledge.search(query)
    if not internal["connected"]:
        notices.append(internal["note"])

    # 6) 전송 내역 공개
    sent: list[str] = []
    llm_used = bool(answer) and llm.is_enabled() and not fallback_reason
    if llm_used:
        target = f"질문 원문"
        if evidence_label:
            target += f" · {evidence_label}"
        sent.append(f"{target} → Claude API (학습에 사용되지 않음)")
    if need_news:
        sent.append(f"뉴스 검색어 ‘{query}’ → 뉴스 검색")
    external_call = bool(sent)

    return {
        "answer": answer,
        "suggestion": suggestion,
        "sources": [
            {
                "slide_number": s["slide_number"],
                "page_title": s["page_title"],
                "summary": s["summary"],
                "evidence": s.get("evidence", []),
                "score": round(score, 4),
            }
            for s, score in relevant
        ],
        "articles": articles,
        "answer_meta": {
            "path": "llm" if llm_used else "offline",
            "model": llm.active_model() if llm_used else None,
            "intent": it["name"],
            "intent_label": it["label"],
            "sufficiency": sufficiency["level"] if sufficiency else None,
            "matched_terms": sufficiency["matched_terms"][:6] if sufficiency else [],
            "fallback_reason": fallback_reason,
            "evidence_scope": evidence_label,
            "knowledge_source": "general_background" if it["name"] == "background" else "report",
        },
        "disclosure": {
            "external_call": external_call,
            "sent_text": " / ".join(sent) or None,
            "channel": feed.get("channel"),
            "model": llm.active_model(),
            "label": ("보고서 발췌가 답변 생성 목적으로만 전송되었습니다 · 전송 내역은 아래에 공개됩니다"
                      if llm_used and evidence_label else
                      "보고서 본문은 전송되지 않았습니다"),
        },
        "notice": " · ".join(notices) or None,
    }


@router.get("/chat/capabilities")
def capabilities():
    """UI 가 시작할 때 무엇이 켜져 있는지 확인한다.

    llm_enabled 가 false 로 나올 때 원인을 바로 짚을 수 있도록 진단 정보를 함께 준다.
    **키 값 자체는 절대 반환하지 않는다** — 변수명과 접두사 형태만 노출한다.
    """
    key_present = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()
                       or os.environ.get("LLM_API_KEY", "").strip())
    model = llm.active_model()
    hints: list[str] = []
    if not key_present:
        if not config.ENV_KEYS_LOADED:
            hints.append(".env 파일을 찾지 못했습니다. 프로젝트 루트(run.bat 와 같은 폴더)에 있어야 합니다.")
        else:
            hints.append("`.env` 는 읽었지만 ANTHROPIC_API_KEY 가 없습니다. 변수명 철자를 확인하세요.")
    elif model and not model.startswith(("claude-", "gpt-", "gemini-")):
        hints.append(f"ANTHROPIC_MODEL 값 '{model}' 이 모델 ID 형식이 아닙니다. "
                     "콘솔의 키 이름이 아니라 claude-sonnet-5 같은 모델 ID 를 넣으세요.")

    return {
        "llm_enabled": llm.is_enabled(),
        "llm_model": model,
        "news_channel": "naver_api" if news._naver_credentials() else "google_rss",
        "internal_db_connected": knowledge.is_connected(),
        "diagnostics": {
            "env_file_loaded": bool(config.ENV_KEYS_LOADED),
            "env_keys": config.ENV_KEYS_LOADED,   # 이름만, 값은 없음
            "api_key_present": key_present,
            "hints": hints,
        },
    }
