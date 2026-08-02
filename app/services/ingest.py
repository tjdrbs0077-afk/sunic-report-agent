"""PPTX 추출 — _ref/report_ai_prototype/ppt_ingest.py 이식."""
from __future__ import annotations

import re
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

EMU = 914400
DATE_RE = re.compile(r"(?:['’]?\d{2}[.\-/](?:Q?[1-4]|\d{1,2})(?:월)?|\d{4}[.\-/]\d{1,2}(?:[.\-/]\d{1,2})?|Q[1-4])", re.I)
STOPWORDS = {
    "그리고", "또한", "관련", "대한", "위한", "통해", "사업", "추진", "내용", "보고", "검토", "현황",
    "계획", "주요", "기반", "중심", "대상", "구분", "페이지", "자료", "결과", "예정", "필요",
}


def inch(value: int | float) -> float:
    return float(value) / EMU


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\x0b", " ")).strip()


def safe_stem(filename: str) -> str:
    stem = Path(filename).stem.strip() or "업로드 보고서"
    return re.sub(r"[\\/:*?\"<>|]+", "_", stem)[:80]


def _iter_shapes(shapes) -> Iterable[Any]:
    for shape in shapes:
        yield shape
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _iter_shapes(shape.shapes)


def _font_size_pt(paragraph) -> float:
    sizes: list[float] = []
    for run in paragraph.runs:
        if run.font.size:
            sizes.append(float(run.font.size.pt))
    return max(sizes) if sizes else 11.0


def _shape_text_entries(slide, slide_h: float) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for shape in _iter_shapes(slide.shapes):
        if shape.shape_type == MSO_SHAPE_TYPE.TABLE or not getattr(shape, "has_text_frame", False):
            continue
        x, y, w, h = map(inch, (shape.left, shape.top, shape.width, shape.height))
        for pi, paragraph in enumerate(shape.text_frame.paragraphs):
            text = clean_text(paragraph.text)
            if not text:
                continue
            entries.append({
                "text": text,
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "bottom": y + h,
                "level": int(getattr(paragraph, "level", 0) or 0),
                "font_size": _font_size_pt(paragraph),
                "bold": any(bool(run.font.bold) for run in paragraph.runs),
                "paragraph_index": pi,
                "shape_name": shape.name,
                "is_placeholder": bool(getattr(shape, "is_placeholder", False)),
                "is_bottom": y > slide_h * 0.84,
            })
    return entries


def _extract_tables(slide) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for shape in _iter_shapes(slide.shapes):
        if shape.shape_type != MSO_SHAPE_TYPE.TABLE:
            continue
        table = shape.table
        matrix = [[clean_text(table.cell(r, c).text) for c in range(len(table.columns))] for r in range(len(table.rows))]
        if not matrix:
            continue
        headers = matrix[0]
        rows = [row for row in matrix[1:] if any(row)]
        tables.append({"headers": headers, "rows": rows, "y": inch(shape.top)})
    return sorted(tables, key=lambda x: x["y"])


def _choose_title(entries: list[dict[str, Any]], slide_h: float) -> dict[str, Any] | None:
    candidates = [e for e in entries if e["y"] < slide_h * 0.30 and not e["is_bottom"]]
    if not candidates:
        candidates = [e for e in entries if not e["is_bottom"]]
    if not candidates:
        return None
    # 위쪽 위치·큰 폰트·placeholder·짧은 제목형 문자열에 가중치 합산.
    # (v4는 튜플 비교라 placeholder 여부가 폰트 크기를 무조건 이겨 24pt 제목 상자가 밀리는 문제가 있었음)
    return max(
        candidates,
        key=lambda e: (
            (4 if e["is_placeholder"] else 0)
            + e["font_size"] * 1.8
            + max(0, 3 - e["y"])
            + (2 if len(e["text"]) <= 45 else 0)
        ),
    )


def _estimate_level(entry: dict[str, Any], max_font: float) -> int:
    if entry["level"]:
        return max(0, min(4, entry["level"]))
    delta = max_font - entry["font_size"]
    level = 0 if delta < 1 else 1 if delta < 2.5 else 2 if delta < 4.5 else 3
    if entry["x"] > 2.5:
        level += 1
    return max(0, min(4, level))


def _shorten(text: str, limit: int = 180) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _keywords(texts: list[str], top_k: int = 8) -> list[str]:
    tokens: list[str] = []
    for text in texts:
        for token in re.findall(r"[A-Za-z][A-Za-z0-9+._-]{2,}|[가-힣]{2,}", text):
            t = token.strip("._-")
            if len(t) < 2 or t in STOPWORDS or t.isdigit():
                continue
            tokens.append(t)
    return [token for token, _ in Counter(tokens).most_common(top_k)]


def _normalize_table(spec: dict[str, Any], max_cols: int, max_rows: int) -> dict[str, Any]:
    headers = list(spec.get("headers", []))[:max_cols]
    if not headers:
        headers = ["구분", "주요 내용"][:max_cols]
    rows = []
    for row in spec.get("rows", [])[:max_rows]:
        row2 = list(row)[:max_cols]
        row2 += [""] * (len(headers) - len(row2))
        rows.append(row2)
    while len(rows) < min(2, max_rows):
        rows.append([""] * len(headers))
    return {"headers": headers, "rows": rows}


def extract_presentation(path: Path, report_id: str | None = None, display_name: str | None = None) -> dict[str, Any]:
    prs = Presentation(path)
    if not prs.slides:
        raise ValueError("슬라이드가 없는 PPT입니다.")
    slide_h = inch(prs.slide_height)
    name = display_name or safe_stem(path.name)
    rid = report_id or f"upload_{uuid.uuid4().hex[:10]}"
    slides: list[dict[str, Any]] = []
    all_texts: list[str] = []

    for slide_no, slide in enumerate(prs.slides, 1):
        entries = _shape_text_entries(slide, slide_h)
        tables = _extract_tables(slide)
        title_entry = _choose_title(entries, slide_h)
        page_title = _shorten(title_entry["text"], 70) if title_entry else f"페이지 {slide_no}"

        foot_entries = [e for e in entries if e["is_bottom"] and e is not title_entry and not re.fullmatch(r"[‹<>#\s\d/]+", e["text"])]
        footnote = _shorten(" · ".join(e["text"] for e in foot_entries[:2]), 220)
        body_entries = [
            e for e in entries
            if e is not title_entry and e not in foot_entries
            and not re.fullmatch(r"[‹<>#\s\d/]+", e["text"])
            and e["text"] not in {"구분", "구 분", "주요 내용", "Project 진행 일정(案)"}
            # 표준 양식 장식 텍스트(표 캡션 【 표 】 등)는 본문이 아니다
            and not re.fullmatch(r"【.*】", e["text"].replace(" ", ""))
        ]
        max_font = max((e["font_size"] for e in body_entries), default=12)
        body: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in sorted(body_entries, key=lambda e: (round(e["y"], 2), round(e["x"], 2), e["paragraph_index"])):
            text = _shorten(entry["text"], 180)
            key = text.casefold()
            if not text or key in seen:
                continue
            seen.add(key)
            body.append({"text": text, "level": _estimate_level(entry, max_font), "bold": bool(entry["bold"]) or None})
            if len(body) >= 12:
                break
        if not body:
            body = [{"text": page_title, "level": 0, "bold": True}]
        elif body[0]["level"] > 0:
            body.insert(0, {"text": page_title, "level": 0, "bold": True})

        date_tokens: list[str] = []
        for entry in entries:
            date_tokens.extend(DATE_RE.findall(entry["text"]))
        date_tokens = list(dict.fromkeys(date_tokens))[:6]
        if len(tables) >= 2:
            template_type = 3
        elif tables:
            template_type = 1
        else:
            template_type = 2

        key_quotes = [page_title] + [item["text"] for item in body[:3]]
        evidence = [
            {"label": "페이지 제목", "quote": page_title, "location": "원본 슬라이드 상단 제목"},
        ]
        for i, quote in enumerate(key_quotes[1:3], 1):
            evidence.append({"label": f"핵심 근거 {i}", "quote": quote, "location": "원본 슬라이드 본문"})
        summary_parts = [item["text"] for item in body[:3] if item["text"] != page_title]
        summary = f"‘{page_title}’ 페이지는 " + ("; ".join(summary_parts) if summary_parts else "원본 슬라이드의 핵심 내용을 정리한다") + "."
        slide_data: dict[str, Any] = {
            "slide_number": slide_no,
            "template_type": template_type,
            "page_title": page_title,
            "sidebar": _shorten(name, 20).replace(" ", "\n", 1),
            "body": body,
            "summary": summary,
            "evidence": evidence,
            "footnote": footnote or f"※ 출처: 업로드 파일 {path.name}, 원본 p.{slide_no}",
            "source_slide_number": slide_no,
        }
        if template_type == 1:
            slide_data["table1"] = _normalize_table(tables[0], 2, 5)
            slide_data["timeline"] = date_tokens + [""] * (6 - len(date_tokens))
            slide_data["timeline_note"] = ["원본 일정"] * len(date_tokens) + [""] * (6 - len(date_tokens))
        elif template_type == 3:
            slide_data["table1"] = _normalize_table(tables[0], 3, 3)
            slide_data["table2"] = _normalize_table(tables[1], 5, 3)
        slides.append(slide_data)
        all_texts.extend([page_title] + [item["text"] for item in body])

    kws = _keywords(all_texts)
    topic = slides[0]["page_title"] if slides else name
    unit = {
        "id": rid,
        "name": name,
        "short": _shorten(name, 20),
        "topic": topic,
        "keywords": kws,
        "partners": [],
        "goal": topic,
        "source": "uploaded",
        "source_file": path.name,
    }
    return {"unit": unit, "slides": slides}
