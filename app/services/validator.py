"""양식 검증기 — 업로드된 PPTX를 config/standard_rules.yaml 규칙과 대조해 위반 목록을 만든다.

각 위반 항목은 SUNIC UI의 .fixlist / .fb-item 마크업에 그대로 들어가는 형태:
{category, severity, slide_no, message, detail, auto_fixable}
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.oxml.ns import qn
from pptx.util import Inches

from app import config

CATEGORY_SEVERITY = {
    "글머리 기호": "high",
    "글꼴": "high",
    "글자 크기": "mid",
    "들여쓰기": "mid",
    "표 규격": "mid",
    "정리": "low",
}

# 표준 글머리(자동번호 1. / 1) / ❑ / – / •) 외에 텍스트 맨 앞에 직접 쓰인 기호
BAD_BULLET_CHARS = set("▶▷◆◇■□※✓√●○◎☞▸»*·◦▪")

# 표준 3종 폰트 외에 스펙이 허용하는 보조 폰트와 테마 참조
FONT_EXTRAS = {"Tahoma", "Arial", "Wingdings", "+mn-lt", "+mn-ea", "+mj-lt", "+mj-ea", "+mn-cs", "+mj-cs"}

SIZE_TOL = 0.5   # pt
GEOM_TOL = 0.10  # inch
MAX_ISSUES = 500


def load_rules() -> dict[str, Any]:
    if not config.RULES_FILE.exists():
        return {}
    return yaml.safe_load(config.RULES_FILE.read_text(encoding="utf-8")) or {}


def _iter_shapes(shapes):
    for shape in shapes:
        yield shape
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _iter_shapes(shape.shapes)


def _run_ea_font(run) -> str | None:
    rpr = run._r.find(qn("a:rPr"))
    if rpr is None:
        return None
    ea = rpr.find(qn("a:ea"))
    return ea.get("typeface") if ea is not None else None


def _nearest(value: float, candidates: list[float]) -> float:
    return min(candidates, key=lambda c: abs(c - value))


def validate_pptx(path: Path) -> dict[str, Any]:
    rules = load_rules()
    fonts = rules.get("fonts") or {}
    allowed_fonts = {fonts.get("latin"), fonts.get("korean"), fonts.get("heading_korean")} - {None} | FONT_EXTRAS
    body_levels = rules.get("body_levels") or []
    level_sizes = [float(x.get("size", s)) for x, s in zip(body_levels, [14, 13, 12, 11, 10])] or [14, 13, 12, 11, 10]
    title_size = float((rules.get("title") or {}).get("font_size", 24))
    table_rules = rules.get("table") or {}
    footnote_size = float((rules.get("footnote") or {}).get("font_size", 8))
    cleanup = rules.get("cleanup") or {}
    max_level = len(level_sizes) - 1

    issues: list[dict[str, Any]] = []
    seen: set[tuple] = set()

    def add(category: str, slide_no: int, message: str, detail: str) -> None:
        key = (category, slide_no, message)
        if key in seen or len(issues) >= MAX_ISSUES:
            return
        seen.add(key)
        issues.append({
            "category": category,
            "severity": CATEGORY_SEVERITY[category],
            "slide_no": slide_no,
            "message": message,
            "detail": detail,
            "auto_fixable": True,
        })

    prs = Presentation(path)
    slide_h = float(prs.slide_height) / 914400

    for slide_no, slide in enumerate(prs.slides, 1):
        for shape in _iter_shapes(slide.shapes):
            # 표 규격: 좌측 기준 x_in, 폭 width_in 고정
            if shape.shape_type == MSO_SHAPE_TYPE.TABLE:
                x_in = float(shape.left) / 914400
                w_in = float(shape.width) / 914400
                std_x = float(table_rules.get("x_in", 2.89757))
                std_w = float(table_rules.get("width_in", 7.519097))
                if abs(x_in - std_x) > GEOM_TOL or abs(w_in - std_w) > GEOM_TOL:
                    add("표 규격", slide_no,
                        f"표 위치·폭 조정 필요 (L {x_in:.2f}in → {std_x:.2f}in, W {w_in:.2f}in → {std_w:.2f}in)",
                        f"슬라이드 {slide_no}의 표 — 표준: 좌 7.36cm, 폭 19.10cm 고정")
                continue
            if not getattr(shape, "has_text_frame", False):
                continue

            top_in = float(shape.top) / 914400 if shape.top is not None else 0.0
            left_in = float(shape.left) / 914400 if shape.left is not None else 0.0
            is_title_area = top_in < 0.8 and left_in < 1.2
            # 타임라인 영역(스펙 3-6): 제목 10pt·마디 날짜 9pt·하단 설명 8pt가 표준
            is_timeline_band = 6.1 < top_in < 7.15 and left_in > 2.4
            is_bottom_area = top_in > slide_h * 0.84 and not is_timeline_band

            if not shape.text_frame.text.strip():
                # 도형(선·화살표·마디 원 등)은 텍스트프레임이 비어 있는 것이 정상 — 순수 텍스트상자만 위반
                if cleanup.get("remove_empty_textbox", True) and shape.shape_type == MSO_SHAPE_TYPE.TEXT_BOX:
                    add("정리", slide_no, "빈 텍스트상자 제거 대상", f"슬라이드 {slide_no}의 '{shape.name}'")
                continue

            for paragraph in shape.text_frame.paragraphs:
                text = paragraph.text.strip()
                if not text:
                    continue
                level = int(paragraph.level or 0)
                # 표 캡션 【 표 】 — 스펙 3-4: Corbel 11pt Bold가 표준
                is_caption = text.startswith("【") and text.endswith("】")

                # 글머리 기호 — 하단(각주) 영역의 ※ 표기는 스펙상 정상이므로 제외
                if not is_bottom_area and text[0] in BAD_BULLET_CHARS:
                    add("글머리 기호", slide_no,
                        f"'{text[0]}' → 표준 글머리(1. / 1) / ❑ / – / •) 교체 필요",
                        f"슬라이드 {slide_no}의 {level + 1}단계 문단 “{text[:30]}”")

                # 들여쓰기 — 5단계 초과
                if level > max_level:
                    add("들여쓰기", slide_no,
                        f"{level + 1}단계 문단 → {max_level + 1}단계 이내로 정리 필요",
                        f"슬라이드 {slide_no} “{text[:30]}”")

                # 정리 — 연속 공백
                if cleanup.get("collapse_spaces", True) and re.search(r"  +", paragraph.text):
                    add("정리", slide_no, "연속 공백 → 1칸으로 축소 필요", f"슬라이드 {slide_no} “{text[:30]}”")

                for run in paragraph.runs:
                    if not run.text.strip():
                        continue
                    # 글꼴
                    for font_name in (run.font.name, _run_ea_font(run)):
                        if font_name and font_name not in allowed_fonts:
                            add("글꼴", slide_no,
                                f"'{font_name}' → Corbel · 나눔스퀘어 계열로 교체 필요",
                                f"슬라이드 {slide_no} “{run.text[:30]}”")
                            break
                    # 글자 크기
                    if run.font.size is None:
                        continue
                    pt = float(run.font.size.pt)
                    if is_caption:
                        if abs(pt - 11.0) > SIZE_TOL:
                            add("글자 크기", slide_no,
                                f"표 캡션 {pt:g}pt → 11pt 통일 필요",
                                f"슬라이드 {slide_no}의 표 캡션")
                    elif is_title_area:
                        if abs(pt - title_size) > SIZE_TOL:
                            add("글자 크기", slide_no,
                                f"제목 {pt:g}pt → {title_size:g}pt 통일 필요",
                                f"슬라이드 {slide_no}의 페이지 제목")
                    elif is_timeline_band:
                        if not any(abs(pt - allowed) <= SIZE_TOL for allowed in (8, 9, 10)):
                            add("글자 크기", slide_no,
                                f"타임라인 {pt:g}pt → 9pt(날짜)·8pt(설명) 통일 필요",
                                f"슬라이드 {slide_no}의 타임라인 영역")
                    elif is_bottom_area:
                        if abs(pt - footnote_size) > SIZE_TOL:
                            add("글자 크기", slide_no,
                                f"각주 {pt:g}pt → {footnote_size:g}pt 통일 필요",
                                f"슬라이드 {slide_no}의 하단 각주")
                    else:
                        expected = level_sizes[min(level, max_level)]
                        if abs(pt - expected) > SIZE_TOL:
                            add("글자 크기", slide_no,
                                f"본문 {pt:g}pt → {expected:g}pt 통일 필요",
                                f"슬라이드 {slide_no}의 {level + 1}단계 문단")

    counts: dict[str, int] = {}
    for issue in issues:
        counts[issue["category"]] = counts.get(issue["category"], 0) + 1
    by_category = [
        {"category": category, "count": count, "severity": CATEGORY_SEVERITY[category]}
        for category, count in sorted(counts.items(), key=lambda kv: -kv[1])
    ]
    return {"total": len(issues), "by_category": by_category, "issues": issues}
