"""근거형 질의응답 — TF-IDF 검색 + (환경변수 설정 시) LLM 호출."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import store
from app.services.retrieve import MIN_SCORE, retrieve

router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    report_id: str
    question: str
    mode: str = "easy"


def resolve_endpoint(model: str, url: str = "") -> tuple[str, str] | None:
    """모델 이름만으로 호출 주소와 형식을 정한다. URL을 직접 넣으면 그 값이 우선.

    돌려주는 값: (요청 URL, 형식) — 형식은 "anthropic" 또는 "openai".
    """
    model = model.strip()
    url = url.strip()
    if model.startswith("claude-"):
        style = "anthropic"
        default_url = "https://api.anthropic.com/v1/messages"
    elif model.startswith(("gpt-", "o1", "o3", "o4", "chatgpt")):
        style = "openai"
        default_url = "https://api.openai.com/v1/chat/completions"
    elif url:
        # 모르는 모델이라도 주소를 직접 주면 OpenAI 호환으로 시도한다.
        style = "openai"
        default_url = url
    else:
        return None
    return (url or default_url), style


def call_optional_llm(question: str, mode: str, unit_name: str, sources: list[dict[str, Any]]) -> str | None:
    key, model = (os.environ.get(k, "").strip() for k in ("LLM_API_KEY", "LLM_MODEL"))
    url = os.environ.get("LLM_API_URL", "").strip()
    if not (key and model):
        return None
    resolved = resolve_endpoint(model, url)
    if resolved is None:
        return None
    url, style = resolved
    source_text = "\n\n".join(
        f"[출처 {i+1}: {unit_name} {s['slide_number']}페이지]\n{s['summary']}\n"
        + "\n".join(f"- {e['quote']}" for e in s.get("evidence", []))
        for i, s in enumerate(sources)
    )
    level = {"brief": "2문장 이내", "easy": "비전공자가 이해하기 쉬운 표현", "detail": "세부 연결관계까지 자세히"}.get(mode, "쉽게")
    prompt = f"""당신은 사내 보고서 전용 질의응답 도우미입니다.
아래 제공된 사내 보고서 근거만 사용하세요. 외부 지식이나 추측을 추가하지 마세요.
근거에 없는 내용은 '업로드된 보고서에서 확인되지 않습니다'라고 답하세요.
답변은 {level}로 작성하고, 문장 끝에 [p.번호] 주석을 붙이세요.

질문: {question}

{source_text}
"""
    if style == "anthropic":
        payload = {
            "model": model,
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
    else:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        }
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=35) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if style == "anthropic":
            # 응답 형식: {"content": [{"type": "text", "text": "..."}]}
            for block in data.get("content", []):
                if block.get("type") == "text" and block.get("text", "").strip():
                    return block["text"].strip()
            return None
        return data["choices"][0]["message"]["content"].strip()
    except (urllib.error.URLError, KeyError, IndexError, TypeError, json.JSONDecodeError):
        return None


def offline_answer(question: str, mode: str, found: list[tuple[dict[str, Any], float]]) -> str:
    relevant = [(s, score) for s, score in found if score >= MIN_SCORE]
    if not relevant:
        return "업로드된 사내 보고서에서 질문과 직접 관련된 내용을 확인하지 못했습니다. 사업명·기술명·일정 등의 표현을 조금 더 구체적으로 입력해 주세요."
    if any(word in question for word in ["어디", "몇 페이지", "출처", "근거"]):
        return "관련 근거는 " + ", ".join(f"{s['slide_number']}페이지 ‘{s['page_title']}’" for s, _ in relevant) + "에서 확인됩니다."
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


@router.post("/chat")
def chat(req: ChatRequest):
    payload = store.report_payload(req.report_id)
    found = retrieve(payload, req.question, top_k=3)
    slides = [s for s, score in found if score >= MIN_SCORE]
    answer = call_optional_llm(req.question, req.mode, payload["unit"]["name"], slides)
    if not answer:
        answer = offline_answer(req.question, req.mode, found)
    sources = [
        {
            "slide_number": s["slide_number"],
            "page_title": s["page_title"],
            "summary": s["summary"],
            "evidence": s.get("evidence", []),
            "score": round(score, 4),
        }
        for s, score in found
        if score >= MIN_SCORE
    ]
    return {"answer": answer, "sources": sources, "scope": "업로드된 사내 보고서만 사용"}
