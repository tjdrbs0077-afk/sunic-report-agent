"""질문 의도 분류 — 질문이 요구하는 '작업'을 판별한다.

특정 질문 문장 목록이 아니라 언어적 표지(요청 동사·의문사·시제 표현)로
분류한다. 새 유형이 필요하면 INTENTS 에 항목을 추가하면 된다 —
각 항목이 (패턴, LLM 지침, 근거 정책)을 함께 들고 있어
chat.py 는 유형별 분기 코드를 갖지 않는다.

우선순위: external > location > compare > summary > analysis > fact
(external 이 먼저인 이유 — "경쟁사의 최근 동향"은 비교가 아니라 외부 질문)
"""
from __future__ import annotations

import re
from typing import Any

# 근거 정책: scope = "retrieved"(관련 페이지만) | "full"(보고서 전체 구조화)
INTENTS: list[dict[str, Any]] = [
    {
        "name": "external",
        "label": "외부 정보·최신 동향",
        "pattern": re.compile(
            r"뉴스|기사|보도|언론|최신|오늘|요즘|근황|현재\s*(상황|기준|시점)|"
            r"실시간|시세|주가|이번\s*(주|달)|동향"),
        "scope": "retrieved", "top_k": 3,
        "guidance": ("이 질문은 보고서 밖의 최신 정보를 요구합니다. 참고 뉴스가 있으면 그것으로 답하고, "
                     "보고서 내용은 배경 맥락으로만 사용하세요. 뉴스가 없으면 보고서만으로는 "
                     "답할 수 없다고 안내하세요."),
    },
    {
        "name": "location",
        "label": "위치·출처 확인",
        "pattern": re.compile(r"어디에?\s*(나와|있|적혀|나오)|몇\s*페이지|어느\s*페이지|출처|어디서\s*확인"),
        "scope": "retrieved", "top_k": 3,
        "guidance": ("위치 질문입니다. 해당 내용이 있는 페이지 번호와 페이지 제목을 간결하게 안내하세요. "
                     "불필요한 분석이나 요약을 덧붙이지 마세요."),
    },
    {
        "name": "compare",
        "label": "비교",
        "pattern": re.compile(r"비교|차이|대비|다른\s*점|공통점|vs|버서스|어느\s*쪽"),
        "scope": "full", "top_k": 5,
        "guidance": ("비교 질문입니다. 먼저 비교 기준을 세우고 공통점과 차이점을 정리하세요. "
                     "한쪽의 근거만 보고서에 있으면 비교가 제한적이라는 사실을 명시하세요."),
    },
    {
        "name": "summary",
        "label": "요약",
        "pattern": re.compile(r"요약|정리해|간추|핵심만|한\s*[줄문]|[세3]\s*줄|브리핑|개요만|알아야\s*할"),
        "scope": "full", "top_k": 5,
        "guidance": ("요약 질문입니다. 페이지별 요약을 나열하지 말고, 여러 페이지의 근거를 "
                     "주제별(예: 시장→전략→실행→재무→리스크)로 종합해 구조화하세요."),
    },
    {
        "name": "analysis",
        "label": "분석·평가·피드백",
        "pattern": re.compile(
            r"실현\s*가능|가능성|타당|현실적|평가|분석해|약점|강점|위험|리스크|"
            r"개선|보완|문제점|부족한|우려|시사점|피드백|의견|생각|전망이?\s*어때"),
        "scope": "full", "top_k": 5,
        "guidance": ("분석·평가 질문입니다. 거절하지 말고 보고서 근거로 판단 가능한 내용을 분석하세요. "
                     "보고서에 명시된 사실과 당신의 해석을 구분하고, 해석에는 '보고서 근거를 종합하면', "
                     "'이 내용으로 볼 때' 같은 표현을 쓰세요. 근거가 부족한 부분은 단정하지 마세요."),
    },
    {
        "name": "fact",
        "label": "사실 확인",
        "pattern": None,  # 기본값
        "scope": "retrieved", "top_k": 5,
        "guidance": ("사실 확인 질문입니다. 보고서에 명시된 사실(수치·이름·날짜)을 첫 문장에서 "
                     "직접 답하고 페이지를 표시하세요. 보고서에 없으면 없다고 답하세요."),
    },
]

_BY_NAME = {i["name"]: i for i in INTENTS}


def classify(question: str) -> dict[str, Any]:
    """질문 → 의도 항목. 매칭 없으면 fact."""
    for item in INTENTS:
        if item["pattern"] and item["pattern"].search(question or ""):
            return item
    return _BY_NAME["fact"]


def by_name(name: str) -> dict[str, Any]:
    return _BY_NAME.get(name, _BY_NAME["fact"])
