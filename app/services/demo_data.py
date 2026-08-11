"""시연용 가상 보고서 생성 — _ref/report_ai_prototype/build_prototype.py 의 데이터 생성부 이식.

업로드할 PPT가 없어도 화면을 채워 시연할 수 있게 한다. 모든 내용은 가상이며
각주에 그 사실을 남긴다. '위반 포함' 옵션은 자동 수정·미리보기 시연용으로
비표준 글머리·연속 공백·단계 초과를 일부러 섞는다.
"""
from __future__ import annotations

import copy
import random
from datetime import datetime
from typing import Any

BUSINESS_UNITS: list[dict[str, Any]] = [
    {"id": "ai_dc", "name": "AI 데이터센터", "short": "AI DC\nSolution", "topic": "AI DC Solution 확보",
     "keywords": ["AI 데이터센터", "GPU", "냉각", "전력", "실증", "멤버사"],
     "partners": ["SK텔레콤", "SK하이닉스", "SK에코플랜트", "SK E&S"],
     "goal": "고밀도 AI 연산 인프라의 통합 솔루션 확보"},
    {"id": "energy", "name": "차세대 에너지", "short": "NEXT\nENERGY", "topic": "차세대 무탄소 전력 솔루션 실증",
     "keywords": ["SMR", "SFR", "무탄소 전력", "규제", "실증", "지역 수용성"],
     "partners": ["SK이노베이션", "SK E&S", "SK에코플랜트", "연구기관"],
     "goal": "장기 전력 공급원 확보와 규제 대응 체계 구축"},
    {"id": "smart_factory", "name": "스마트 제조", "short": "SMART\nFACTORY", "topic": "AI 기반 자율제조 운영체계 구축",
     "keywords": ["디지털 트윈", "예지보전", "품질", "공정", "데이터", "자동화"],
     "partners": ["SK하이닉스", "SK실트론", "SK C&C", "설비 파트너"],
     "goal": "공정 데이터 기반 생산성 향상과 비가동 시간 절감"},
    {"id": "mobility", "name": "친환경 모빌리티", "short": "GREEN\nMOBILITY", "topic": "전기·수소 모빌리티 통합 플랫폼 확대",
     "keywords": ["EV", "수소", "충전", "배터리", "플랫폼", "물류"],
     "partners": ["SK온", "SK엔무브", "SK렌터카", "지자체"],
     "goal": "충전·운영·에너지 데이터를 연결한 모빌리티 서비스 확대"},
    {"id": "battery", "name": "배터리소재", "short": "BATTERY\nMATERIAL", "topic": "전고체 배터리 소재 양산 검증",
     "keywords": ["전고체 배터리", "황화물 전해질", "리튬메탈 음극", "건식 전극", "파일럿 라인", "수율"],
     "partners": ["SK온", "SK아이이테크놀로지", "소재 협력사", "대학 연구팀"],
     "goal": "차세대 배터리 소재의 양산 공정 확보"},
    {"id": "hydrogen", "name": "수소에너지", "short": "HYDROGEN\nENERGY", "topic": "청정수소 생산·공급 밸류체인 구축",
     "keywords": ["청정수소", "수전해", "액화수소", "충전소", "인허가", "수요처"],
     "partners": ["SK E&S", "SK가스", "플랜트 파트너", "지자체"],
     "goal": "생산부터 공급까지 이어지는 수소 밸류체인 확보"},
    {"id": "ai_semi", "name": "AI반도체", "short": "AI\nSEMICON", "topic": "AI 추론 전용 반도체 사업화",
     "keywords": ["NPU", "PIM", "HBM", "파운드리", "전력효율", "소프트웨어 스택"],
     "partners": ["SK하이닉스", "SK텔레콤", "팹리스 파트너", "클라우드 고객사"],
     "goal": "추론 특화 반도체와 소프트웨어 스택의 동시 확보"},
]

SLIDE_TOPICS: list[tuple[int, str]] = [
    (1, "사업 개요 및 전체 일정"), (2, "추진 배경과 문제 정의"), (3, "핵심 과제 및 실행 대안"),
    (2, "솔루션 구성과 적용 범위"), (3, "이해관계자 및 협의 현황"), (2, "투자·예산 운영 원칙"),
    (1, "1단계 추진 일정"), (3, "주요 리스크 및 대응 방안"), (2, "성과지표 및 목표 수준"),
    (3, "실증 계획과 검증 기준"), (2, "운영 모델과 역할 분담"), (3, "인프라 후보 및 선정 기준"),
    (2, "파트너십 추진 방향"), (3, "규제·보안·품질 대응"), (2, "조직 체계와 의사결정 구조"),
    (3, "확산 전략과 적용 순서"), (2, "경영진 의사결정 요청사항"), (1, "2단계 확산 일정"),
    (2, "기대효과 및 측정 방법"), (3, "종합 결론과 후속 조치"),
]

# '위반 포함' 옵션이 섞어 넣는 비표준 글머리 (validator 가 잡아내는 기호)
BAD_BULLETS = ["▶", "※", "◆", "✓", "■"]


def paragraph(text: str, level: int = 0, bold: bool | None = None) -> dict[str, Any]:
    return {"text": text, "level": level, "bold": bold}


def unit_by_id(unit_id: str) -> dict[str, Any] | None:
    return next((u for u in BUSINESS_UNITS if u["id"] == unit_id), None)


def make_demo_slides(unit: dict[str, Any]) -> list[dict[str, Any]]:
    name, short, topic = unit["name"], unit["short"], unit["topic"]
    kws, partners, goal = unit["keywords"], unit["partners"], unit["goal"]
    slides: list[dict[str, Any]] = []
    for idx, (ptype, page_title) in enumerate(SLIDE_TOPICS, 1):
        phase = 1 if idx <= 10 else 2
        body = [paragraph(topic, 0), paragraph(f"Phase {phase} · {page_title}", 1)]
        if idx == 1:
            body += [paragraph("경영진 보고", 2, True), paragraph(goal, 3),
                     paragraph(f"{partners[0]} 중심 실무협의 후 CEO 보고", 4),
                     paragraph(f"{partners[1]}·{partners[2]} 공동 검토", 4)]
        elif idx == 2:
            body += [paragraph("현황", 2, True),
                     paragraph(f"{kws[0]} 관련 수요는 확대되고 있으나 보고서별 정보와 의사결정 기준이 분산", 3),
                     paragraph(f"{kws[1]}·{kws[2]} 조건을 통합한 공통 실행안 필요", 4),
                     paragraph("보고 단계별 핵심 쟁점과 근거를 일관된 형식으로 관리", 4)]
        else:
            section = ["추진 내용", "검토 결과", "협의 사항", "핵심 판단", "실행 방향"][idx % 5]
            body += [paragraph(section, 2, True),
                     paragraph(f"{kws[(idx-1) % len(kws)]} 중심의 실행 범위와 담당 조직을 구체화", 3),
                     paragraph(f"{partners[(idx-1) % len(partners)]}와 세부 기준 협의", 4),
                     paragraph(f"성과는 {kws[(idx+1) % len(kws)]} 지표와 일정 준수율로 확인", 4)]
        summary = (f"{name}는 ‘{page_title}’ 페이지에서 {body[2]['text']}를 중심으로 추진 방향을 제시한다. "
                   f"핵심 근거는 {body[3]['text']}이며, {body[-1]['text']}를 후속 확인사항으로 관리한다.")
        slide: dict[str, Any] = {
            "slide_number": idx, "template_type": ptype, "page_title": page_title, "sidebar": short,
            "body": body, "summary": summary,
            "evidence": [
                {"label": "페이지 제목", "quote": page_title, "location": "상단 제목"},
                {"label": "핵심 문구", "quote": body[2]["text"], "location": "본문 3단계"},
                {"label": "세부 근거", "quote": body[3]["text"], "location": "본문 4단계"},
            ],
            "footnote": f"※ 본 자료는 {name} 시연을 위해 생성한 가상 데이터이며 실제 사업정보가 아닙니다.",
            "source_slide_number": idx,
        }
        if ptype == 1:
            slide["table1"] = {"headers": ["구분", "협의 경과"], "rows": [
                [partners[0], f"{kws[0]} 범위 및 프로젝트 목표 협의"],
                [partners[1], f"{kws[1]} 기술조건과 운영방안 검토"],
                [partners[2], f"{kws[2]} 인프라 및 비용 구조 검토"],
                [partners[3], f"{kws[3]} 관련 협력 가능성 확인"],
                ["보고서", "단계별 의사결정 자료 통합"],
            ]}
            base = 26 + idx // 18
            slide["timeline"] = [f"'{base}.4", f"'{base}.5", f"'{base}.6", f"'{base}.8", f"'{base}.10", f"'{base+1}.Q1"]
            slide["timeline_note"] = ["Kick-off", "요건정의", "대안검토", "실증", "CEO보고", "확대"]
        elif ptype == 3:
            slide["table1"] = {"headers": ["구분", "개요", "추진방안"], "rows": [
                [kws[0], f"{kws[0]} 적용 범위 정의", f"{partners[0]} 주관 검토"],
                [kws[1], f"{kws[1]} 기술 조건 확인", f"{partners[1]} 공동 실증"],
                [kws[2], f"{kws[2]} 운영 기준 수립", "보고서 통합 관리"],
            ]}
            slide["table2"] = {"headers": ["구분", "개요", "지원 적극성", "Infra", "수용성"], "rows": [
                ["후보 A", f"{kws[3]} 기반", "높음", "보유", "높음"],
                ["후보 B", f"{kws[4]} 연계", "중간", "보유", "중간"],
                ["후보 C", f"{kws[5]} 확장", "검토", "추가", "조건부"],
            ]}
        slides.append(slide)
    return slides


def messify(slides: list[dict[str, Any]], seed: int = 0) -> int:
    """자동 수정 시연용으로 양식 위반을 일부러 섞는다. 넣은 위반 건수를 돌려준다."""
    rng = random.Random(seed)
    injected = 0
    for slide in slides:
        body = slide["body"]
        if len(body) < 4:
            continue
        # 비표준 글머리 기호
        i = rng.randrange(2, len(body))
        body[i]["text"] = f"{rng.choice(BAD_BULLETS)} {body[i]['text']}"
        injected += 1
        # 연속 공백
        j = rng.randrange(1, len(body))
        text = body[j]["text"]
        if " " in text.strip():
            head, _, tail = text.partition(" ")
            body[j]["text"] = f"{head}   {tail}"
            injected += 1
        # 단계 초과 (5단계 = level 5)
        if rng.random() < 0.35:
            body[-1]["level"] = 5
            injected += 1
    return injected


def build_payload(unit_id: str, messy: bool = False) -> dict[str, Any]:
    """업로드된 보고서와 같은 형태의 시연용 페이로드를 만든다."""
    source = unit_by_id(unit_id)
    if source is None:
        raise ValueError(f"알 수 없는 보고서입니다: {unit_id}")
    unit = copy.deepcopy(source)
    suffix = "_위반포함" if messy else ""
    unit["id"] = f"demo_{unit_id}{'_messy' if messy else ''}"
    unit["name"] = f"{source['name']}{suffix}"
    unit["short"] = source["short"]
    unit["source"] = "demo"
    unit["source_file"] = "시연용 가상 데이터"

    slides = make_demo_slides(source)
    if messy:
        messify(slides, seed=abs(hash(unit_id)) % 10000)

    return {
        "unit": unit,
        "slides": slides,
        "original_slides": copy.deepcopy(slides),
        "uploaded_at": datetime.now().isoformat(timespec="seconds"),
        "processing_seconds": 0.0,
    }
