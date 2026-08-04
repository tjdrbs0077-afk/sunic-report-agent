"""외부 LLM 호출 어댑터.

CLAUDE.md 규칙: 외부 LLM 은 **환경변수가 있을 때만** 동작한다.
설정이 없으면 모든 함수가 None 을 돌려주고, 호출부는 오프라인(TF-IDF) 응답으로 폴백한다.

지원 제공자
-----------
anthropic : POST {base}/v1/messages
            헤더 x-api-key + anthropic-version, 응답 content[0].text
openai    : POST {url}  (chat/completions 호환)
            헤더 Authorization: Bearer, 응답 choices[0].message.content

환경변수
--------
LLM_PROVIDER   anthropic | openai   (미지정 시 키 종류로 자동 판별)
ANTHROPIC_API_KEY / LLM_API_KEY     API 키
ANTHROPIC_MODEL  / LLM_MODEL        모델명 (기본 claude-sonnet-5)
ANTHROPIC_BASE_URL                  기본 https://api.anthropic.com
LLM_API_URL                         openai 호환 엔드포인트 전체 URL

보안 주의 (v2 전송 정책)
------------------------
이 모듈로 넘어온 문자열은 그대로 외부로 나간다.
v2 부터 보고서 전문이 답변 생성 목적에 한해 전송된다 (팀 합의).
호출부(routers/chat.py)는 전송 내역을 disclosure 로 사용자에게 공개해야 한다.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"  # 문서 요약·근거 인용 용도에 충분, Opus 대비 저비용
DEFAULT_BASE_URL = "https://api.anthropic.com"
TIMEOUT_SEC = 40


def _env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def provider_config() -> dict[str, str] | None:
    """설정된 제공자 정보를 반환. 미설정이면 None."""
    key = _env("ANTHROPIC_API_KEY", "LLM_API_KEY")
    if not key:
        return None

    provider = _env("LLM_PROVIDER").lower()
    if not provider:
        # 키 접두사와 URL 설정으로 자동 판별한다.
        provider = "anthropic" if key.startswith("sk-ant-") or not _env("LLM_API_URL") else "openai"

    if provider == "anthropic":
        base = _env("ANTHROPIC_BASE_URL") or DEFAULT_BASE_URL
        return {
            "provider": "anthropic",
            "key": key,
            "model": _env("ANTHROPIC_MODEL", "LLM_MODEL") or DEFAULT_ANTHROPIC_MODEL,
            "url": base.rstrip("/") + "/v1/messages",
        }

    url = _env("LLM_API_URL")
    if not url:
        return None
    return {
        "provider": "openai",
        "key": key,
        "model": _env("LLM_MODEL") or "gpt-4o-mini",
        "url": url,
    }


def is_enabled() -> bool:
    return provider_config() is not None


def active_model() -> str | None:
    cfg = provider_config()
    return cfg["model"] if cfg else None


def _post_json(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any] | None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # 인증 실패·요금·모델명 오류를 조용히 삼키지 않는다.
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise LLMError(f"{exc.code} {exc.reason} — {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise LLMError(f"연결 실패 — {exc}") from exc
    except json.JSONDecodeError as exc:
        raise LLMError("응답이 JSON 이 아닙니다") from exc


class LLMError(RuntimeError):
    """외부 LLM 호출 실패. 호출부가 잡아서 폴백하되, 사유는 사용자에게 알린다."""


def complete(system: str, user: str, max_tokens: int = 1200, temperature: float = 0.1) -> str | None:
    """단발 호출. 미설정이면 None, 실패하면 LLMError."""
    cfg = provider_config()
    if cfg is None:
        return None

    if cfg["provider"] == "anthropic":
        # Claude 5 계열은 `temperature` 파라미터를 폐기했다.
        # 이 필드를 보내면 Messages API가 400 invalid_request_error를
        # 반환하므로 Anthropic에서는 모델 기본 생성 설정을 사용한다.
        data = _post_json(
            cfg["url"],
            {
                "x-api-key": cfg["key"],
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            {
                "model": cfg["model"],
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        try:
            blocks = data["content"]
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        except (KeyError, TypeError) as exc:
            raise LLMError(f"예상과 다른 응답 형식: {str(data)[:200]}") from exc
        return text.strip() or None

    data = _post_json(
        cfg["url"],
        {"Authorization": f"Bearer {cfg['key']}", "Content-Type": "application/json"},
        {
            "model": cfg["model"],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
    )
    try:
        return (data["choices"][0]["message"]["content"] or "").strip() or None
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"예상과 다른 응답 형식: {str(data)[:200]}") from exc
