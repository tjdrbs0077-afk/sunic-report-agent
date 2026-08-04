"""⑤ 챗봇 — 단일 통합 챗봇 (v2).

질문 하나로 보고서 근거와 외부 뉴스·일반 지식을 함께 다룬다.

ANTHROPIC_API_KEY 설정 시
    선택한 보고서 **전문** + 수집한 공개 뉴스를 **한 번의 LLM 호출**에 실어
    [p.N] / [기사 N] 인용이 달린 답변을 생성한다. 해석·평가형 질문에도
    근거를 종합해 답한다.

키가 없으면
    기존 오프라인 동작으로 폴백 — TF-IDF 발췌 답변 + 질문 라우팅 가드
    (외부형→뉴스 목록, 해석형→한계 안내, 약근거→경고).

전송 정책 (v2 에서 변경 — 팀 합의 사항)
    v1: 보고서 본문 절대 비전송 → 답변 품질 한계로 폐기.
    v2: 보고서 전문이 **답변 생성 목적에 한해** Claude API 로 전송된다.
        무엇이 전송되었는지 disclosure 로 매 답변 화면에 공개한다.
        Anthropic API 는 기본적으로 입력을 모델 학습에 사용하지 않는다.
        그래프(insight_graph.json)에는 여전히 정제된 검색어와 공개 기사만
        저장된다 — 보고서 본문·질문 원문은 저장하지 않는다.
"""
from __future__ import annotations

import os
import re
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import config
from app.services import entity, graph_store, knowledge, llm, news, store
from app.services.retrieve import MIN_SCORE, retrieve
from app.services.retrieve import slide_document

router = APIRouter(prefix="/api", tags=["chat"])

MODE_STYLE = {
    "brief": "2문장 이내로 짧게",
    "easy": "비전공자도 이해할 수 있는 쉬운 표현으로",
    "detail": "배경과 연결관계까지 자세히",
}

# 보고서 전문 전송 시 상한 (문자) — 초과분은 잘라내고 답변에 그 사실을 밝힌다
MAX_REPORT_CHARS = 24000

UNIFIED_SYSTEM = """당신은 사내 사업기획보고서 검토 담당자를 돕는 어시스턴트입니다.

지켜야 할 것:
- 보고서 본문이 주어지면 그 내용을 최우선 근거로 사용하고, 보고서에서 가져온 내용 뒤에 [p.페이지번호] 를 답니다.
- 참고 뉴스가 주어지고 질문과 관련이 있으면 사용한 문장 뒤에 [기사 N] 을 답니다. 관련 없으면 무시합니다.
- 보고서에 없는 내용을 보고서에 있는 것처럼 말하지 않습니다. 일반 지식으로 보충할 때는 그 사실을 문장에 밝힙니다.
- 실현 가능성·리스크 평가 같은 판단형 질문에는 보고서 근거를 종합해 견해를 제시하되, 판단의 근거와 한계를 함께 밝힙니다.
- 최신 수치나 날짜를 근거 없이 단정하지 않습니다. 모르면 모른다고 답합니다."""


class ChatRequest(BaseModel):
    question: str
    mode: str = "easy"
    report_id: str | None = None
    use_news: bool = True
    # v1 호환 — 프론트 구버전이 보내던 필드. 통합 후에는 무시한다.
    scope: Literal["report", "context"] | None = None


# ──────────────────────────────────────────────────────────────
# 오프라인 폴백용 라우팅 가드 (LLM 미설정 시에만 사용)
# ──────────────────────────────────────────────────────────────

_LOCATION_RE = re.compile(r"어디|몇\s*페이지|출처|근거\s*(가|는|를)?\s*(뭐|무엇|어디)")
_EXTERNAL_RE = re.compile(r"뉴스|기사|보도|언론|외부|트렌드|근황|경쟁사|타사|업계\s*동향|최근\s*동향|시장\s*동향")
_INTERPRETIVE_RE = re.compile(
    r"실현\s*가능|가능성|타당|현실적|평가해|어떻게\s*(생각|보|평가)|전망|괜찮|성공할|잘\s*될|"
    r"장단점|리스크\s*(가|는)?\s*(크|많|어떻)|문제없|비판|의견")
WEAK_SCORE = 0.12


def offline_answer(question: str, mode: str, found: list[tuple[dict[str, Any], float]]) -> str:
    relevant = [(s, score) for s, score in found if score >= MIN_SCORE]
    if not relevant:
        return ("업로드된 사내 보고서에서 질문과 직접 관련된 내용을 확인하지 못했습니다. "
                "사업명·기술명·일정 등의 표현을 조금 더 구체적으로 입력해 주세요.")
    if _LOCATION_RE.search(question):
        return "관련 근거는 " + ", ".join(
            f"{s['slide_number']}페이지 ‘{s['page_title']}’" for s, _ in relevant) + "에서 확인됩니다."
    if mode == "brief":
        return f"{relevant[0][0]['summary']} [p.{relevant[0][0]['slide_number']}]"
    if mode == "detail":
        chunks = []
        for s, _ in relevant:
            ev = "; ".join(e["quote"] for e in s.get("evidence", [])[:3])
            chunks.append(f"{s['page_title']}: {s['summary']} 핵심 근거는 ‘{ev}’입니다. [p.{s['slide_number']}] ")
        return "\n\n".join(chunks) + "\n\n위 답변은 업로드된 보고서 내부 정보만 연결해 정리했습니다."
    first = relevant[0][0]
    answer = f"{first['summary']} [p.{first['slide_number']}]"
    if len(relevant) > 1:
        second = relevant[1][0]
        answer += f" 또한 {second['summary']} [p.{second['slide_number']}]"
    return answer


def _offline_guard(question: str,
                   relevant: list[tuple[dict[str, Any], float]],
                   ) -> tuple[str | None, dict[str, Any] | None, str | None]:
    """(answer, suggestion, notice) — 가드 미적용이면 (None, None, None)."""
    is_location = bool(_LOCATION_RE.search(question))
    if not is_location and _INTERPRETIVE_RE.search(question):
        answer = ("실현 가능성·평가 같은 판단은 오프라인 모드에서 제공하지 않습니다. "
                  "ANTHROPIC_API_KEY 를 설정하면 보고서 근거를 종합한 판단형 답변이 가능합니다.")
        if relevant:
            pages = ", ".join(f"[p.{s['slide_number']}] ‘{s['page_title']}’" for s, _ in relevant)
            answer += f" 판단에 참고할 만한 근거 페이지는 {pages} 입니다."
        return answer, None, None
    if relevant and max(score for _, score in relevant) < WEAK_SCORE:
        return None, None, ("질문과 보고서 내용의 유사도가 낮습니다. 아래 근거는 참고 수준이며, "
                            "보고서에 쓰인 표현으로 다시 물으면 정확도가 올라갑니다.")
    return None, None, None


def _offline_news_answer(feed: dict[str, Any]) -> str:
    articles = feed["articles"]
    if not articles:
        return ("외부 지식 답변을 생성하려면 ANTHROPIC_API_KEY 설정이 필요합니다. "
                f"뉴스 검색도 결과를 얻지 못했습니다. ({feed.get('error') or '사유 미상'})")
    lines = [f"‘{feed['sent_query']}’ 로 검색한 최근 기사 {len(articles)}건입니다. "
             "요약 답변을 받으려면 ANTHROPIC_API_KEY 를 설정해 주세요.\n"]
    for i, article in enumerate(articles, 1):
        lines.append(f"[{i}] {article['title']} ({article.get('date') or '날짜 미상'})")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# LLM 통합 경로
# ──────────────────────────────────────────────────────────────

def _report_text(payload: dict[str, Any]) -> tuple[str, bool]:
    """보고서 전문을 페이지 표기와 함께 평탄화한다. (text, truncated)"""
    lines = []
    for slide in payload.get("slides", []):
        lines.append(f"[p.{slide.get('slide_number')}] {slide_document(slide)}")
    text = "\n".join(lines)
    if len(text) > MAX_REPORT_CHARS:
        return text[:MAX_REPORT_CHARS], True
    return text, False


def _unified_prompt(question: str, mode: str, report_name: str | None,
                    report_text: str | None, truncated: bool,
                    articles: list[dict[str, Any]]) -> str:
    style = MODE_STYLE.get(mode, MODE_STYLE["easy"])
    parts: list[str] = []
    if report_text:
        head = f"[보고서 전문: {report_name}]"
        if truncated:
            head += " (분량 제한으로 뒷부분이 잘렸습니다 — 답변에서 이 사실을 밝히세요)"
        parts.append(f"{head}\n{report_text}")
    if articles:
        block = "\n\n".join(
            f"[기사 {i}] {a['title']} ({a.get('source', '')} {a.get('date', '')})\n{a.get('summary', '')}"
            for i, a in enumerate(articles, 1))
        parts.append(f"[참고 뉴스]\n{block}")
    parts.append(f"[질문]\n{question}")
    parts.append(f"위 자료를 근거로 {style} 답하세요. "
                 "보고서 인용은 [p.N], 뉴스 인용은 [기사 N] 표기를 사용하세요.")
    return "\n\n".join(parts)


# ──────────────────────────────────────────────────────────────
# 그래프 누적 (⑥ 연동) — 정제된 검색어·공개 기사만 저장
# ──────────────────────────────────────────────────────────────

def _update_insight_graph(query: str, articles: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        extraction = entity.extract(query, articles)
        delta = graph_store.merge(extraction, query)
        delta["labels"] = {n["id"]: n["label"] for n in extraction["nodes"]}
        return delta
    except Exception as exc:  # noqa: BLE001 — 그래프 갱신 실패가 답변을 막으면 안 된다
        return {
            "added_node_ids": [], "updated_node_ids": [], "added_edge_ids": [],
            "article_count": 0, "labels": {},
            "warnings": [f"엔티티 추출 실패 — {exc}"],
        }


# ──────────────────────────────────────────────────────────────
# 엔드포인트
# ──────────────────────────────────────────────────────────────

@router.post("/chat")
def chat(req: ChatRequest):
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="질문이 비어 있습니다.")

    # 1) 보고서 로드 + 근거 페이지 검색 (로컬 — 출처 패널용)
    payload = store.report_payload(req.report_id) if req.report_id else None
    found = retrieve(payload, question, top_k=3) if payload else []
    relevant = [(s, score) for s, score in found if score >= MIN_SCORE]

    # 2) 뉴스 수집 — 외부로 나가는 검색어는 질문에서 정제한 것뿐
    query = news.extract_query(question)
    feed = ({"articles": [], "channel": "off", "sent_query": query, "error": None}
            if not req.use_news else news.search_news(query, limit=5))
    articles = feed["articles"]

    notices: list[str] = []
    suggestion: dict[str, Any] | None = None
    answer: str | None = None
    report_sent = False

    # 3) 답변 생성
    if llm.is_enabled():
        report_name = None
        report_text, truncated = None, False
        if payload:
            report_name = payload.get("unit", {}).get("name", req.report_id)
            report_text, truncated = _report_text(payload)
            report_sent = True
        try:
            answer = llm.complete(
                UNIFIED_SYSTEM,
                _unified_prompt(question, req.mode, report_name, report_text, truncated, articles))
        except llm.LLMError as exc:
            notices.append(f"외부 LLM 호출 실패 — {exc}. 오프라인 답변으로 대체합니다.")
            report_sent = False

    if not answer:  # 키 없음 또는 호출 실패 → 오프라인 폴백
        if payload and not (_EXTERNAL_RE.search(question) and not _LOCATION_RE.search(question)):
            guard_answer, suggestion, guard_notice = _offline_guard(question, relevant)
            answer = guard_answer or offline_answer(question, req.mode, found)
            if guard_notice:
                notices.append(guard_notice)
        else:
            answer = _offline_news_answer(feed)

    if req.use_news and feed.get("error"):
        notices.append(f"뉴스 수집 실패 — {feed['error']}")
    internal = knowledge.search(query)
    if not internal["connected"]:
        notices.append(internal["note"])

    # 4) ⑥ 동향 그래프 누적
    graph_delta = _update_insight_graph(query, articles)

    # 5) 전송 내역 공개 — 무엇이 밖으로 나갔는지 그대로 보여준다
    sent: list[str] = []
    external = False
    if report_sent:
        external = True
        sent.append(f"질문 원문 · 보고서 전문 ‘{payload.get('unit', {}).get('name', '')}’ "
                    f"{len(payload.get('slides', []))}페이지 → Claude API (학습에 사용되지 않음)")
    elif llm.is_enabled() and answer:
        external = True
        sent.append("질문 원문 → Claude API")
    if req.use_news:
        external = True
        sent.append(f"뉴스 검색어 ‘{query}’ → 뉴스 검색")

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
        "disclosure": {
            "external_call": external,
            "sent_text": " / ".join(sent) or None,
            "channel": feed.get("channel"),
            "model": llm.active_model(),
            "label": ("보고서 전문이 답변 생성 목적으로만 전송되었습니다 · 전송 내역은 아래에 공개됩니다"
                      if report_sent else
                      "보고서 본문은 전송되지 않았습니다"),
        },
        "notice": " · ".join(notices) or None,
        "graph_delta": graph_delta,
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
