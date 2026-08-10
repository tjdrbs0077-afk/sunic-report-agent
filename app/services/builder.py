"""표준 양식 PPTX 생성 — _ref/report_ai_prototype/build_prototype.py 이식.

데모 데이터 생성부(BUSINESS_UNITS, make_demo_slides 등)는 제외하고
프로파일 추출·슬라이드 생성·병합 로직만 옮겼다.
"""
from __future__ import annotations

import math
import re
from copy import deepcopy
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import yaml
from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_SHAPE_TYPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

from app import config
from app.services.ingest import normalize_body_items

EMU = 914400
BLACK = RGBColor(0, 0, 0)
WHITE = RGBColor(255, 255, 255)

# ── 표준 본문 번호·글머리 (standard_rules.yaml body_levels) ──────────
# 생성 PPTX 단락에 buAutoNum/buChar 를 명시적으로 기록한다.
# 이전에는 단락 level 만 지정해 번호가 아예 찍히지 않거나 임의로 보였다.

_LEVEL_FALLBACK = [
    {"marL": 265113, "indent": -265113, "bullet": "auto:1.", "line_spacing": 100, "spc_before": 10},
    {"marL": 538163, "indent": -266700, "bullet": "auto:1)", "line_spacing": 100, "spc_before": 10},
    {"marL": 714375, "indent": -179388, "bullet": "wingdings:❑", "line_spacing": 100, "spc_before": 5},
    {"marL": 892175, "indent": -177800, "bullet": "arial:–", "line_spacing": 100, "spc_before": 5},
    {"marL": 1081088, "indent": -188913, "bullet": "arial:•", "line_spacing": 100, "spc_before": 5},
]
_AUTONUM_TYPES = {"1.": "arabicPeriod", "1)": "arabicParenR", "(1)": "arabicParenBoth", "a.": "alphaLcPeriod"}
_BULLET_FONTS = {"wingdings": "Wingdings", "arial": "Arial", "char": "Arial"}
_std_levels_cache: list[dict[str, Any]] | None = None


def _std_levels() -> list[dict[str, Any]]:
    global _std_levels_cache
    if _std_levels_cache is None:
        levels = _LEVEL_FALLBACK
        try:
            rules = yaml.safe_load(config.RULES_FILE.read_text(encoding="utf-8")) or {}
            loaded = rules.get("body_levels") or []
            if len(loaded) >= 5:
                levels = loaded
        except Exception:  # noqa: BLE001 — 규칙 파일이 없어도 기본값으로 생성한다
            pass
        _std_levels_cache = levels
    return _std_levels_cache


def reset_rule_cache() -> None:
    """양식 기준을 저장하거나 교체한 뒤 단계별 생성 규칙을 다시 읽게 한다."""
    global _std_levels_cache
    _std_levels_cache = None


def _apply_bullet(paragraph, level: int, first: bool = False) -> None:
    """단락에 표준 들여쓰기·줄간격·앞 간격과 번호/글머리 기호를 명시한다.

    buAutoNum 은 같은 텍스트 프레임 안 같은 레벨에서 1. 2. 3. 으로 자동 증가한다.
    스키마 순서(lnSpc → spcBef → buFont → buAutoNum/buChar)를 지켜서 넣는다.
    """
    spec = _std_levels()[max(0, min(4, level))]
    pPr = paragraph._p.get_or_add_pPr()
    pPr.set("marL", str(int(spec.get("marL", 0))))
    pPr.set("indent", str(int(spec.get("indent", 0))))
    for tag in ("a:lnSpc", "a:spcBef", "a:spcAft", "a:buNone", "a:buFont", "a:buAutoNum", "a:buChar"):
        for el in pPr.findall(qn(tag)):
            pPr.remove(el)

    # 단계별 줄간격 + 단락 앞 간격 (샘플 실측: 레벨1·2 = 10pt, 3~5 = 5pt)
    ln = pPr.makeelement(qn("a:lnSpc"), {})
    line_spacing = float(spec.get("line_spacing", 100))
    ln.append(ln.makeelement(qn("a:spcPct"), {"val": str(int(round(line_spacing * 1000)))}))
    pPr.append(ln)
    spc_pt = 0 if first else float(spec.get("spc_before", 0))   # 첫 단락은 위 여백 불필요
    bef = pPr.makeelement(qn("a:spcBef"), {})
    bef.append(bef.makeelement(qn("a:spcPts"), {"val": str(int(spc_pt * 100))}))
    pPr.append(bef)

    kind, _, val = str(spec.get("bullet", "")).partition(":")
    if kind == "auto":
        pPr.append(pPr.makeelement(qn("a:buAutoNum"), {"type": _AUTONUM_TYPES.get(val, "arabicPeriod")}))
    elif val:
        pPr.append(pPr.makeelement(qn("a:buFont"), {"typeface": _BULLET_FONTS.get(kind, kind.title())}))
        pPr.append(pPr.makeelement(qn("a:buChar"), {"char": val}))


def clean_body_items(items: list[dict[str, Any]], page_title: str) -> list[dict[str, Any]]:
    """본문에서 제목 중복·섹션 코드를 걷어낸다.

    ingest 수정 이전에 추출된 기존 보고서 JSON 을 위한 방어선이다
    (재업로드 없이도 생성 결과가 깨끗해진다).
    """
    return normalize_body_items(items, page_title)


def inch(v: int | float) -> float:
    return round(float(v) / EMU, 6)


def parse_hex(value: str | None, fallback: str = "#000000") -> RGBColor:
    raw = (value or fallback).lstrip("#")
    if len(raw) != 6:
        raw = fallback.lstrip("#")
    return RGBColor(int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))


def _set_cell_border(cell, color: str, width_pt: float = 0.75) -> None:
    """PowerPoint 표 셀의 네 방향 선 색을 동일하게 설정한다."""
    raw = str(color or "#7F7F7F").lstrip("#").upper()
    if len(raw) != 6:
        raw = "7F7F7F"
    tc_pr = cell._tc.get_or_add_tcPr()
    for tag in ("a:lnL", "a:lnR", "a:lnT", "a:lnB"):
        old = tc_pr.find(qn(tag))
        if old is not None:
            tc_pr.remove(old)
        line = etree.SubElement(tc_pr, qn(tag), {"w": str(int(round(width_pt * 12700)))})
        solid = etree.SubElement(line, qn("a:solidFill"))
        etree.SubElement(solid, qn("a:srgbClr"), {"val": raw})
        etree.SubElement(line, qn("a:prstDash"), {"val": "solid"})


def safe_rgb(color) -> str | None:
    try:
        if color.rgb is not None:
            return f"#{color.rgb}"
    except Exception:
        return None
    return None


def _font_xml(run, latin: str = "Corbel", east_asia: str = "나눔스퀘어") -> None:
    # 한글 전용 런은 a:latin에도 한글 폰트를 지정한다. PowerPoint가 런의 대표 글꼴로
    # a:latin을 표시하므로 Corbel로 두면 한글 텍스트가 Corbel로 지정된 것처럼 보이고,
    # 한글 폰트 미설치 환경에서 대체 글꼴로 렌더링되는 문제가 있다.
    text = run.text or ""
    if not re.search(r"[A-Za-z]", text) and re.search(r"[가-힣]", text):
        latin = east_asia
    rpr = run._r.get_or_add_rPr()
    for tag, name in (("a:latin", latin), ("a:ea", east_asia), ("a:cs", "Tahoma")):
        node = rpr.find(qn(tag))
        if node is None:
            node = etree.SubElement(rpr, qn(tag))
        node.set("typeface", name)


def exact_template_profile(path: Path) -> dict[str, Any]:
    """원본 PPT가 실제 사용하는 슬라이드·레이아웃·텍스트 위계 실측값을 추출한다."""
    prs = Presentation(path)
    layout = prs.slide_layouts[11]
    layout_table = next(s for s in layout.shapes if s.shape_type == MSO_SHAPE_TYPE.TABLE)
    source1 = prs.slides[0]
    source2 = prs.slides[1]
    source3 = prs.slides[2]

    def find_title(slide):
        return next(s for s in slide.shapes if getattr(s, "has_text_frame", False) and s.top < Inches(0.8) and s.left < Inches(1.2))

    def find_sidebar(slide):
        return next(s for s in slide.shapes if s.name == "직사각형 1")

    def find_body(slide):
        return next(s for s in slide.shapes if getattr(s, "is_placeholder", False) and s.width > Inches(8))

    title = find_title(source1)
    sidebar = find_sidebar(source1)
    body = find_body(source1)
    footnote = next(s for s in source2.shapes if getattr(s, "has_text_frame", False) and s.top > Inches(7.0))
    tables1 = sorted([s for s in source1.shapes if s.shape_type == MSO_SHAPE_TYPE.TABLE], key=lambda x: x.top)
    tables3 = sorted([s for s in source3.shapes if s.shape_type == MSO_SHAPE_TYPE.TABLE], key=lambda x: x.top)

    profile: dict[str, Any] = {
        "canvas": {"width": inch(prs.slide_width), "height": inch(prs.slide_height), "background": "#FFFFFF"},
        "title": {
            "x": inch(title.left), "y": inch(title.top), "w": 7.2, "h": inch(title.height),
            "font_latin": "Corbel", "font_ea": "나눔스퀘어 ExtraBold", "font_size": 24,
            "bold": True, "text_color": "#000000", "fill": "transparent", "align": "left", "word_wrap": False,
        },
        "frame": {
            "x": inch(layout_table.left), "y": inch(layout_table.top), "w": inch(layout_table.width), "h": inch(layout_table.height),
            "header_h": inch(layout_table.table.rows[0].height),
            "sidebar_w": inch(layout_table.table.columns[0].width),
            "header_fill": safe_rgb(layout_table.table.cell(0, 0).fill.fore_color) or "#B7D3EE",
            "border_color": "#7F7F7F", "header_text_color": "#000000", "header_font_size": 14,
            "header_font_latin": "Corbel", "header_font_ea": "나눔스퀘어 ExtraBold",
        },
        "sidebar": {
            "x": inch(sidebar.left), "y": inch(sidebar.top), "w": inch(sidebar.width), "h": inch(sidebar.height),
            "font_latin": "Corbel", "font_ea": "나눔스퀘어 ExtraBold", "font_size": 14,
            "bold": True, "text_color": "#000000", "fill": "transparent", "align": "center", "word_wrap": False,
        },
        "body": {
            "x": inch(body.left), "y": inch(body.top), "w": inch(body.width), "h": inch(body.height),
            "font_latin": "Corbel", "font_ea": "나눔스퀘어", "text_color": "#000000", "fill": "transparent",
            "level_sizes": [14, 13, 12, 11, 10],
            "level_ea_fonts": ["나눔스퀘어 ExtraBold", "나눔스퀘어", "나눔스퀘어", "나눔스퀘어", "나눔스퀘어"],
            "level_bold": [True, True, False, False, False],
        },
        "footnote": {
            "x": inch(footnote.left), "y": inch(footnote.top), "w": inch(footnote.width), "h": inch(footnote.height),
            "font_latin": "Corbel", "font_ea": "나눔스퀘어", "font_size": 8,
            "bold": False, "text_color": "#000000", "fill": "transparent", "align": "left", "word_wrap": False,
        },
        "table_type1": _table_profile(tables1[0]),
        "table_type3_top": _table_profile(tables3[0]),
        "table_type3_bottom": _table_profile(tables3[1]),
        "timeline": {
            "x": 2.70, "y": 6.25, "w": 7.65, "h": 0.82,
            "title": {"x": 2.70, "y": 6.757, "w": 1.89, "h": 0.315, "font_size": 10},
            "line_y": 6.702,
            "centers": [3.625, 4.967, 6.351, 7.749, 8.816, 9.920],
            "date_y": 6.351, "note_y": 6.757,
            "date_font_size": 9, "note_font_size": 8,
        },
        "page_number": {"x": 8.271, "y": 7.243, "w": 2.528, "h": 0.25, "font_size": 8},
        "source": {
            "file": path.name, "slide_count": len(prs.slides), "layout_name": layout.name,
            "recognition": "Exact OOXML geometry + inherited hierarchy from layout/master",
        },
    }
    profile["resolved_hierarchy"] = _read_placeholder_hierarchy(path)
    return profile


def _table_profile(shape) -> dict[str, Any]:
    t = shape.table
    return {
        "x": inch(shape.left), "y": inch(shape.top), "w": inch(shape.width), "h": inch(shape.height),
        "row_heights": [inch(r.height) for r in t.rows],
        "col_widths": [inch(c.width) for c in t.columns],
        "header_fill": safe_rgb(t.cell(0, 0).fill.fore_color) or "#DCE6F2",
        "header_font_size": 10.5, "body_font_size": 10,
        "font_latin": "Corbel", "font_ea": "나눔스퀘어",
        "text_color": "#000000", "fill": "transparent",
    }


def _read_placeholder_hierarchy(path: Path) -> list[dict[str, Any]]:
    ns = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main", "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    out: list[dict[str, Any]] = []
    with ZipFile(path) as z:
        root = etree.fromstring(z.read("ppt/slideLayouts/slideLayout12.xml"))
        ph = None
        for sp in root.findall(".//p:sp", ns):
            pnode = sp.find(".//p:ph", ns)
            if pnode is not None and pnode.get("type") == "body":
                ph = sp
                break
        if ph is None:
            return out
        lst = ph.find(".//a:lstStyle", ns)
        if lst is None:
            return out
        for level in range(1, 6):
            node = lst.find(f"a:lvl{level}pPr", ns)
            if node is None:
                continue
            rpr = node.find("a:defRPr", ns)
            bullet = ""
            if node.find("a:buAutoNum", ns) is not None:
                bullet = node.find("a:buAutoNum", ns).get("type", "number")
            elif node.find("a:buChar", ns) is not None:
                bullet = node.find("a:buChar", ns).get("char", "")
            elif node.find("a:buNone", ns) is not None:
                bullet = "none"
            line_pct = node.find("a:lnSpc/a:spcPct", ns)
            before_pts = node.find("a:spcBef/a:spcPts", ns)
            out.append({
                "level": level - 1,
                "size_pt": (float(rpr.get("sz")) / 100) if rpr is not None and rpr.get("sz") else None,
                "margin_left_in": float(node.get("marL", 0)) / EMU,
                "indent_in": float(node.get("indent", 0)) / EMU,
                "line_spacing": (float(line_pct.get("val")) / 1000) if line_pct is not None else None,
                "spc_before": (float(before_pts.get("val")) / 100) if before_pts is not None else None,
                "bullet": bullet,
            })
    return out


def remove_shape(shape) -> None:
    shape._element.getparent().remove(shape._element)


def clone_slide(prs: Presentation, source_index: int):
    source = prs.slides[source_index]
    dest = prs.slides.add_slide(source.slide_layout)
    for sh in list(dest.shapes):
        remove_shape(sh)
    # _spTree 전체를 복사하면 루트 구조 노드(nvGrpSpPr/grpSpPr)까지 중복되어
    # LibreOffice에서는 열리지만 Microsoft PowerPoint에서는 손상 파일로 거부된다.
    # 실제 도형 요소만 복사해 슬라이드 XML의 필수 순서를 보존한다.
    for shape in source.shapes:
        dest.shapes._spTree.insert_element_before(deepcopy(shape._element), "p:extLst")
    return dest


def _find_title(slide):
    return next((s for s in slide.shapes if getattr(s, "has_text_frame", False) and s.top < Inches(0.8) and s.left < Inches(1.2)), None)


def _find_sidebar(slide):
    return next((s for s in slide.shapes if s.name == "직사각형 1"), None)


def _find_body(slide):
    return next((s for s in slide.shapes if getattr(s, "is_placeholder", False) and s.width > Inches(8)), None)


def _text_units(line: str) -> float:
    """전각(한글 등) 문자 1.0em, 반각(영문·숫자) 0.55em으로 줄 폭을 추정한다."""
    return sum(1.0 if ord(ch) > 0x2E80 else 0.55 for ch in line)


def _estimated_fit_size(text: str, width_in: float, height_in: float, base_pt: float, min_pt: float = 6.0, line_factor: float = 1.25, wrap: bool = True) -> float:
    """한/영 혼용 텍스트 박스의 보수적 폰트 크기 추정.

    python-pptx에서는 PowerPoint 실제 렌더러를 쓸 수 없으므로 글자 폭 추정으로
    넘침 여부를 판단해 폰트를 줄인다. wrap=False(줄바꿈 없음)면 가장 긴 줄이
    박스 폭 안에 들어가는 크기까지 줄인다 — 좌측 사업단명 등이 밖으로
    튀어나오는 문제를 막는다.
    """
    text = str(text or "")
    if not text.strip() or width_in <= 0 or height_in <= 0:
        return base_pt
    raw_lines = text.splitlines() or [text]
    size = float(base_pt)
    while size > min_pt:
        units_per_line = max(2.0, (width_in * 72) / size)
        if wrap:
            lines = sum(max(1, math.ceil(_text_units(l) / units_per_line)) for l in raw_lines)
            fits_width = True
        else:
            lines = len(raw_lines)
            fits_width = all(_text_units(l) <= units_per_line * 0.96 for l in raw_lines)
        fits_height = lines * size * line_factor <= height_in * 72 * 0.92
        if fits_width and fits_height:
            break
        size -= 0.5
    return round(max(min_pt, size), 1)


MIN_BODY_SCALE = 0.45


def _body_required_pt(items: list[dict[str, Any]], width_in: float, sizes: list[float], scale: float) -> float:
    """주어진 배율에서 본문이 차지하는 세로 높이(pt)를 추정한다.

    표준 양식의 단락 앞 간격(spc_before, 샘플 실측)도 함께 계산해
    간격을 넉넉히 줘도 상자를 넘치지 않게 자동 맞춤이 동작한다.
    """
    levels_spec = _std_levels()
    required = 0.0
    for i, item in enumerate(items):
        level = max(0, min(4, int(item.get("level", 0))))
        size = float(sizes[level]) * scale
        usable_width = max(0.8, width_in - 0.18 * level)
        units_per_line = max(4.0, (usable_width * 72) / size)
        lines = max(1, math.ceil(_text_units(str(item.get("text", ""))) / units_per_line))
        required += lines * size * 1.32
        if i > 0:
            required += float(levels_spec[level].get("spc_before", 0)) * scale
    return required


def _body_fit_scale(items: list[dict[str, Any]], width_in: float, height_in: float, sizes: list[float]) -> float:
    if not items or width_in <= 0 or height_in <= 0:
        return 1.0
    scale = 1.0
    while scale > MIN_BODY_SCALE:
        if _body_required_pt(items, width_in, sizes, scale) <= height_in * 72 * 0.94:
            break
        scale -= 0.04
    return max(MIN_BODY_SCALE, round(scale, 2))


def fit_body_items(items: list[dict[str, Any]], width_in: float, height_in: float, sizes: list[float]) -> tuple[list[dict[str, Any]], bool]:
    """상자 안에 들어갈 만큼만 남긴다. 최소 배율에서도 넘치면 뒤에서부터 덜어낸다.

    표가 있는 페이지에서 본문이 표 위로 흘러 글자가 겹치는 것을 막는다.
    잘라낸 경우 마지막 항목에 말줄임표를 붙여 잘렸다는 사실을 남긴다.
    """
    if not items or width_in <= 0 or height_in <= 0:
        return items, False
    limit_pt = height_in * 72 * 0.94
    kept = list(items)
    while len(kept) > 1 and _body_required_pt(kept, width_in, sizes, MIN_BODY_SCALE) > limit_pt:
        kept = kept[:-1]
    if len(kept) == len(items):
        return items, False
    trimmed = [dict(x) for x in kept]
    last = trimmed[-1]
    text = str(last.get("text", "")).rstrip()
    if not text.endswith("…"):
        last["text"] = text + " …"
    return trimmed, True


def set_text_exact(shape, text: str, cfg: dict[str, Any], vertical=MSO_ANCHOR.MIDDLE) -> None:
    tf = shape.text_frame
    tf.clear()
    wrap = bool(cfg.get("word_wrap", True))
    base_size = float(cfg.get("font_size", 12))
    min_size = float(cfg.get("min_font_size", 6))
    fitted_size = _estimated_fit_size(text, inch(shape.width), inch(shape.height), base_size, min_size, wrap=wrap)
    # 줄바꿈 없이 맞추려다 글자가 지나치게 작아지면(기준의 70% 미만) 줄바꿈으로 전환한다.
    # 좌측 '구 분' 라벨처럼 좁고 긴 박스에서 글자가 밖으로 나가거나 깨알같이 작아지는 것을 막는다.
    if not wrap and fitted_size < base_size * 0.7:
        wrapped_size = _estimated_fit_size(text, inch(shape.width), inch(shape.height), base_size, min_size, wrap=True)
        if wrapped_size > fitted_size:
            wrap, fitted_size = True, wrapped_size
    tf.word_wrap = wrap
    tf.vertical_anchor = vertical
    p = tf.paragraphs[0]
    p.alignment = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}.get(cfg.get("align"), PP_ALIGN.LEFT)
    r = p.add_run()
    r.text = text
    _font_xml(r, cfg.get("font_latin", "Corbel"), cfg.get("font_ea", "나눔스퀘어"))
    r.font.size = Pt(fitted_size)
    r.font.bold = bool(cfg.get("bold", False))
    r.font.color.rgb = parse_hex(cfg.get("text_color"), "#000000")
    fill = cfg.get("fill")
    if fill and fill != "transparent":
        shape.fill.solid(); shape.fill.fore_color.rgb = parse_hex(fill, "#FFFFFF")
    elif fill == "transparent":
        try: shape.fill.background()
        except Exception: pass


def write_body_exact(shape, items: list[dict[str, Any]], cfg: dict[str, Any]) -> None:
    tf = shape.text_frame
    tf.clear()
    tf.word_wrap = True
    # 원본 placeholder의 여백·위계를 유지한다. 정확한 번호/글머리 형식은 레이아웃이 정의한다.
    sizes = [float(x) for x in cfg.get("level_sizes", [14, 13, 12, 11, 10])]
    items, _ = fit_body_items(items, inch(shape.width), inch(shape.height), sizes)
    scale = _body_fit_scale(items, inch(shape.width), inch(shape.height), sizes)
    fitted_sizes = [max(6.0, round(x * scale, 1)) for x in sizes]
    hidden_color = parse_hex(cfg.get("hidden_color"), "#FFFFFF")
    ea_fonts = cfg.get("level_ea_fonts", ["나눔스퀘어 ExtraBold"] * 3 + ["나눔스퀘어"] * 2)
    bolds = cfg.get("level_bold", [True, True, False, False, False])
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        level = max(0, min(4, int(item.get("level", 0))))
        p.level = level
        p.alignment = PP_ALIGN.LEFT
        _apply_bullet(p, level, first=(i == 0))   # 표준 번호·들여쓰기·줄간격을 단락에 명시
        r = p.add_run(); r.text = item.get("text", "")
        _font_xml(r, cfg.get("font_latin", "Corbel"), ea_fonts[level])
        r.font.size = Pt(fitted_sizes[level])
        # 원본의 볼드 여부는 따르지 않는다 — 표준 양식은 레벨 스펙이 결정한다
        # (원본 SK 템플릿은 본문 전체가 볼드라 그대로 두면 양식 위반이 된다)
        r.font.bold = bool(bolds[level])
        # 이어지는 장의 대주제는 흰색으로 숨긴다 (스펙 4장 연속 슬라이드 규칙).
        # 번호·들여쓰기 체계는 그대로 유지된다.
        r.font.color.rgb = hidden_color if item.get("hidden") else parse_hex(cfg.get("text_color"), "#000000")


def _clear_runs(paragraph) -> None:
    for child in list(paragraph._p):
        if child.tag in {qn("a:r"), qn("a:br"), qn("a:fld")}:
            paragraph._p.remove(child)


def replace_cell_text(cell, text: str, header: bool, key: bool, cfg: dict[str, Any], width_in: float = 1.5, height_in: float = 0.35) -> None:
    tf = cell.text_frame
    while len(tf.paragraphs) > 1:
        tf._txBody.remove(tf.paragraphs[-1]._p)
    p = tf.paragraphs[0]
    _clear_runs(p)
    r = p.add_run(); r.text = text
    heading_ea = cfg.get("header_font_ea", "나눔스퀘어 ExtraBold")
    _font_xml(r, cfg.get("font_latin", "Corbel"), heading_ea if (header or key) else cfg.get("font_ea", "나눔스퀘어"))
    base_size = float(cfg.get("header_font_size", 10.5) if header else cfg.get("body_font_size", 10))
    r.font.size = Pt(_estimated_fit_size(text, width_in, height_in, base_size, 6.0, 1.15))
    r.font.bold = bool(header or key)
    r.font.color.rgb = parse_hex(cfg.get("text_color"), "#000000")
    if header:
        p.alignment = PP_ALIGN.CENTER
        cell.fill.solid(); cell.fill.fore_color.rgb = parse_hex(cfg.get("header_fill"), "#DCE6F2")
    elif key:
        # 참고 양식: 데이터 행의 맨 왼쪽 구분 열은 따뜻한 회색으로 구분한다.
        cell.fill.solid(); cell.fill.fore_color.rgb = parse_hex(cfg.get("first_col_fill"), "#EEECE1")


def fill_table_preserve(shape, spec: dict[str, Any], cfg: dict[str, Any]) -> None:
    t = shape.table
    headers, rows = spec.get("headers", []), spec.get("rows", [])
    for c in range(len(t.columns)):
        replace_cell_text(
            t.cell(0, c), headers[c] if c < len(headers) else "", True, False, cfg,
            inch(t.columns[c].width), inch(t.rows[0].height),
        )
    for r in range(1, len(t.rows)):
        src = rows[r - 1] if r - 1 < len(rows) else []
        for c in range(len(t.columns)):
            replace_cell_text(
                t.cell(r, c), src[c] if c < len(src) else "", False, c == 0, cfg,
                inch(t.columns[c].width), inch(t.rows[r].height),
            )


def _apply_geometry(shape, cfg: dict[str, Any]) -> None:
    for attr, key in (("left", "x"), ("top", "y"), ("height", "h")):
        if key in cfg:
            setattr(shape, attr, Inches(float(cfg[key])))
    if "w" not in cfg:
        return
    target_width = Inches(float(cfg["w"]))
    # 표는 GraphicFrame 폭만 바꾸면 열 너비가 그대로 남는다. 기존 비율을 유지해 함께 조정한다.
    if getattr(shape, "has_table", False):
        columns = list(shape.table.columns)
        current_width = sum(int(column.width) for column in columns)
        if columns and current_width > 0:
            used = 0
            for column in columns[:-1]:
                width = int(round(int(target_width) * int(column.width) / current_width))
                column.width = width
                used += width
            columns[-1].width = max(1, int(target_width) - used)
    shape.width = target_width


def apply_rule_fonts(profile: dict[str, Any]) -> dict[str, Any]:
    """config/standard_rules.yaml의 직접 편집값을 생성 프로파일 전체에 반영한다.

    기준을 직접 수정하면 글꼴뿐 아니라 제목·본문·표·프레임·각주도 생성 PPT에 적용된다.
    """
    from app.services import validator

    rules = validator.load_rules()
    fonts = rules.get("fonts") or {}
    latin = fonts.get("latin") or "Corbel"
    korean = fonts.get("korean") or "나눔스퀘어"
    heading = fonts.get("heading_korean") or korean
    for key in ("title", "sidebar"):
        profile[key]["font_latin"] = latin
        profile[key]["font_ea"] = heading
    profile["frame"]["header_font_latin"] = latin
    profile["frame"]["header_font_ea"] = heading
    profile["body"]["font_latin"] = latin
    profile["body"]["font_ea"] = korean
    profile["body"]["level_ea_fonts"] = [heading, korean, korean, korean, korean]
    # 레벨별 크기·볼드도 standard_rules.yaml body_levels 를 단일 진실로 삼는다
    title_rules = rules.get("title") or {}
    for key in ("font_size", "bold", "x", "y"):
        if key in title_rules:
            profile["title"][key] = title_rules[key]

    rule_levels = rules.get("body_levels") or []
    if len(rule_levels) >= 5:
        profile["body"]["level_sizes"] = [
            float(lv.get("size", d)) for lv, d in zip(rule_levels, [14, 13, 12, 11, 10])]
        profile["body"]["level_bold"] = [bool(lv.get("bold", False)) for lv in rule_levels[:5]]
    profile["footnote"]["font_latin"] = latin
    profile["footnote"]["font_ea"] = korean
    footnote_rules = rules.get("footnote") or {}
    if "font_size" in footnote_rules:
        profile["footnote"]["font_size"] = float(footnote_rules["font_size"])

    table_rules = rules.get("table") or {}
    for key in ("table_type1", "table_type3_top", "table_type3_bottom"):
        profile[key]["font_latin"] = latin
        profile[key]["font_ea"] = korean
        profile[key]["header_font_ea"] = heading
        if "x_in" in table_rules:
            profile[key]["x"] = float(table_rules["x_in"])
        if "width_in" in table_rules:
            profile[key]["w"] = float(table_rules["width_in"])
        for rule_key in ("header_fill", "first_col_fill", "header_font_size", "body_font_size"):
            if rule_key in table_rules:
                profile[key][rule_key] = table_rules[rule_key]

    frame_rules = rules.get("frame") or {}
    for key in ("header_fill", "border_color", "header_font_size"):
        if key in frame_rules:
            profile["frame"][key] = frame_rules[key]
    return profile


def deep_merge(base: dict[str, Any], patch: dict[str, Any] | None) -> dict[str, Any]:
    result = deepcopy(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = deepcopy(v)
    return result


def effective_layout(profile: dict[str, Any], overrides: dict[str, Any] | None, slide_no: int) -> dict[str, Any]:
    global_patch = (overrides or {}).get("global", {})
    slide_patch = (overrides or {}).get("slides", {}).get(str(slide_no), {})
    return deep_merge(deep_merge(profile, global_patch), slide_patch)


def apply_layout_base(prs: Presentation, cfg: dict[str, Any]) -> None:
    # 전 슬라이드 배경.
    bg = parse_hex(cfg.get("canvas", {}).get("background"), "#FFFFFF")
    for slide in prs.slides:
        slide.background.fill.solid(); slide.background.fill.fore_color.rgb = bg
    # 외곽 프레임은 레이아웃에서 상속되므로 한 번만 수정한다.
    layout = prs.slide_layouts[11]
    frame_shape = next(s for s in layout.shapes if s.shape_type == MSO_SHAPE_TYPE.TABLE)
    frame = cfg["frame"]
    _apply_geometry(frame_shape, frame)
    frame_shape.table.columns[0].width = Inches(float(frame["sidebar_w"]))
    frame_shape.table.columns[1].width = Inches(float(frame["w"] - frame["sidebar_w"]))
    frame_shape.table.rows[0].height = Inches(float(frame["header_h"]))
    frame_shape.table.rows[1].height = Inches(float(frame["h"] - frame["header_h"]))
    for row in frame_shape.table.rows:
        for cell in row.cells:
            _set_cell_border(cell, frame.get("border_color", "#7F7F7F"))
    for c in range(2):
        cell = frame_shape.table.cell(0, c)
        cell.fill.solid(); cell.fill.fore_color.rgb = parse_hex(frame.get("header_fill"), "#B7D3EE")
        p = cell.text_frame.paragraphs[0]
        for r in p.runs:
            _font_xml(r, frame.get("header_font_latin", "Corbel"), frame.get("header_font_ea", "나눔스퀘어 ExtraBold"))
            r.font.size = Pt(float(frame.get("header_font_size", 14)))
            r.font.bold = True
            r.font.color.rgb = parse_hex(frame.get("header_text_color"), "#000000")


TABLE_GAP = 0.26        # 표와 표 사이 (양식 실측 좌표는 1.4in 이나 벌어져 있다)
FRAME_PAD = 0.12        # 프레임 안쪽 바닥 여유
MIN_GAP = 0.08          # 자리가 모자랄 때까지 줄일 수 있는 최소 간격


def body_line_gap(cfg: dict[str, Any] | None = None) -> float:
    """본문 문단과 문단 사이 간격(inch).

    표는 '본문 다음 문단'처럼 딱 이만큼만 띄우고 바로 이어 붙인다.
    양식 실측 좌표(표 y)를 지키려 들면 본문이 짧을 때 표가 한참 아래로
    떨어져 글과 표 사이가 텅 빈다.
    """
    try:
        levels = _std_levels()
        spc = float(levels[0].get("spc_before", 10)) if levels else 10.0
    except Exception:
        spc = 10.0
    return round(max(spc, 4.0) / 72, 3)


def table_keys(ptype: int) -> list[str]:
    if ptype == 1:
        return ["table_type1"]
    if ptype == 3:
        return ["table_type3_top", "table_type3_bottom"]
    return []


def stack_floor(ptype: int, cfg: dict[str, Any]) -> float:
    """표 더미가 넘어서면 안 되는 바닥 좌표(inch).

    유형 1 은 하단에 타임라인 띠가 고정으로 깔려 있으므로 그 위에서 멈춘다.
    (이걸 빼먹으면 표 마지막 줄과 타임라인 글자가 겹친다.)
    """
    floor = float(cfg["frame"]["y"]) + float(cfg["frame"]["h"]) - FRAME_PAD
    timeline = cfg.get("timeline") if ptype == 1 else None
    if timeline:
        floor = min(floor, float(timeline["y"]) - FRAME_PAD)
    return floor


def available_body_height(ptype: int, cfg: dict[str, Any]) -> float:
    """해당 유형에서 본문이 실제로 쓸 수 있는 세로 길이(inch).

    표는 본문 아래로 흘려 쌓으므로(`table_tops`), 본문이 쓸 수 있는 높이는
    '바닥에서 표 더미와 간격을 뺀 만큼'이다. 예전에는 양식에서 실측한
    표의 y 좌표에서 멈추게 했는데, 그 좌표가 샘플 보고서의 짧은 본문을 전제로
    한 값이라 유형 3 에서 본문이 0.86in 밖에 못 쓰고 대부분 잘려 나갔다.
    """
    body = cfg["body"]
    top, height = float(body["y"]), float(body["h"])
    keys = table_keys(ptype)
    if keys:
        stack = sum(float(cfg[key]["h"]) for key in keys) + TABLE_GAP * (len(keys) - 1)
        height = min(height, stack_floor(ptype, cfg) - stack - body_line_gap(cfg) - top)
    return max(0.4, round(height, 3))


def _body_used_height(items: list[dict[str, Any]], cfg: dict[str, Any]) -> float:
    """본문이 실제로 차지하는 세로 길이(inch) — 표를 어디서부터 놓을지 정하는 값."""
    body = cfg["body"]
    sizes = body.get("level_sizes") or [14, 13, 12, 11, 10]
    return _body_required_pt(items, float(body["w"]), sizes, 1.0) / 72


def table_tops(ptype: int, cfg: dict[str, Any],
               body_items: list[dict[str, Any]]) -> dict[str, float]:
    """본문 아래로 표를 차례로 쌓아 각 표의 y 좌표를 정한다.

    양식에서 실측한 표 좌표를 그대로 쓰면 세 가지가 깨진다.
      - 본문이 샘플보다 길면 본문 글자가 표 위로 흘러 **겹친다**
      - 본문이 짧으면 글 끝과 표 사이가 1~1.5in 텅 빈다
      - 상단 표와 하단 표 사이에 1.4in 짜리 빈 공간이 남는다
    그래서 실측 y 는 쓰지 않는다. 표는 **본문의 다음 문단처럼** 글 바로 아래에
    문단 간격(`body_line_gap`)만 띄우고 붙이고, 두 번째 표부터는 앞 표 아래
    `TABLE_GAP` 에 붙인다.
    """
    keys = table_keys(ptype)
    if not keys:
        return {}
    body = cfg["body"]
    used = min(_body_used_height(body_items, cfg), available_body_height(ptype, cfg))
    floor = stack_floor(ptype, cfg)

    def stack(gap_body: float, gap_table: float) -> dict[str, float]:
        cursor = float(body["y"]) + used + gap_body
        out: dict[str, float] = {}
        for i, key in enumerate(keys):
            if i:
                cursor += gap_table
            out[key] = cursor
            cursor += float(cfg[key]["h"])
        return out

    tops = stack(body_line_gap(cfg), TABLE_GAP)
    bottom = tops[keys[-1]] + float(cfg[keys[-1]]["h"])
    if bottom > floor:                       # 바닥을 넘치면 간격부터 줄인다
        tops = stack(MIN_GAP, MIN_GAP)
        bottom = tops[keys[-1]] + float(cfg[keys[-1]]["h"])
        if bottom > floor:                   # 그래도 넘치면 통째로 위로 당긴다
            shift = bottom - floor
            lowest = float(body["y"]) + 0.3
            tops = {key: max(lowest, value - shift) for key, value in tops.items()}
    return {key: round(value, 3) for key, value in tops.items()}


def _with_top(cfg_obj: dict[str, Any], top: float | None) -> dict[str, Any]:
    if top is None:
        return cfg_obj
    placed = dict(cfg_obj)
    placed["y"] = top
    return placed


def _limit_body_height(body, ptype: int, cfg: dict[str, Any]) -> None:
    available = available_body_height(ptype, cfg)
    if inch(body.height) > available:
        body.height = Inches(available)


def fill_slide(slide, data: dict[str, Any], slide_no: int, cfg: dict[str, Any]) -> None:
    ptype = data["template_type"]
    title = _find_title(slide)
    if title:
        _apply_geometry(title, cfg["title"]); set_text_exact(title, data["page_title"], cfg["title"])
    sidebar = _find_sidebar(slide)
    if sidebar:
        _apply_geometry(sidebar, cfg["sidebar"]); set_text_exact(sidebar, data["sidebar"], cfg["sidebar"])
    body_items = clean_body_items(data["body"], data.get("page_title", ""))
    body = _find_body(slide)
    if body:
        _apply_geometry(body, cfg["body"])
        _limit_body_height(body, ptype, cfg)
        write_body_exact(body, body_items, cfg["body"])

    # 표는 본문 길이에 맞춰 아래로 흘려 쌓는다 (겹침·과도한 간격 방지)
    tops = table_tops(ptype, cfg, body_items)
    tables = sorted([s for s in slide.shapes if s.shape_type == MSO_SHAPE_TYPE.TABLE], key=lambda s: s.top)
    if ptype == 1 and tables:
        placed = _with_top(cfg["table_type1"], tops.get("table_type1"))
        _apply_geometry(tables[0], placed); fill_table_preserve(tables[0], data.get("table1", {"headers": ["구분", "협의 경과"], "rows": []}), placed)
    if ptype == 3 and len(tables) >= 2:
        top_cfg = _with_top(cfg["table_type3_top"], tops.get("table_type3_top"))
        bottom_cfg = _with_top(cfg["table_type3_bottom"], tops.get("table_type3_bottom"))
        _apply_geometry(tables[0], top_cfg); fill_table_preserve(tables[0], data.get("table1", {"headers": ["구분", "개요", "추진방안"], "rows": []}), top_cfg)
        _apply_geometry(tables[1], bottom_cfg); fill_table_preserve(tables[1], data.get("table2", {"headers": ["구분", "개요", "지원", "Infra", "수용성"], "rows": []}), bottom_cfg)

    # 각주. 원본 1페이지에는 각주가 없으므로 2페이지 실측 좌표로 새로 만든다.
    foots = [s for s in slide.shapes if getattr(s, "has_text_frame", False) and s.top > Inches(7.0) and s.width > Inches(8)]
    if foots:
        foot = foots[0]
    else:
        f = cfg["footnote"]
        foot = slide.shapes.add_textbox(Inches(f["x"]), Inches(f["y"]), Inches(f["w"]), Inches(f["h"]))
    _apply_geometry(foot, cfg["footnote"]); set_text_exact(foot, data["footnote"], cfg["footnote"], MSO_ANCHOR.MIDDLE)

    # 타임라인 텍스트는 원본 선·원은 유지한 채 원좌표에 다시 만든다.
    if ptype == 1 and data.get("timeline"):
        for s in list(slide.shapes):
            if getattr(s, "has_text_frame", False) and (6.30 < inch(s.top) < 7.12) and (2.5 < inch(s.left) < 10.4):
                if s.name.startswith("Rectangle") or s.name.startswith("텍스트 개체 틀"):
                    remove_shape(s)
        tl = cfg["timeline"]
        # 샘플 화살표/원을 제거하고 타임라인 전체를 편집 가능한 블록으로 재구성한다.
        for s in list(slide.shapes):
            if s.name.startswith("Down Arrow") or s.name.startswith("Oval"):
                remove_shape(s)
        x, y, w, h = (float(tl.get(k, v)) for k, v in (("x", 2.70), ("y", 6.25), ("w", 7.65), ("h", .82)))
        body_latin = cfg["body"].get("font_latin", "Corbel")
        body_ea = cfg["body"].get("font_ea", "나눔스퀘어")
        line_y = y + h * .58
        line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x + .20), Inches(line_y), Inches(w - .22), Inches(.055))
        line.fill.solid(); line.fill.fore_color.rgb = RGBColor(191, 191, 191); line.line.fill.background()
        arrow = slide.shapes.add_shape(MSO_SHAPE.ISOSCELES_TRIANGLE, Inches(x + w - .12), Inches(line_y - .055), Inches(.16), Inches(.16))
        arrow.rotation = 90; arrow.fill.solid(); arrow.fill.fore_color.rgb = RGBColor(191, 191, 191); arrow.line.fill.background()
        title_cfg = {"font_latin": body_latin, "font_ea": body_ea, "font_size": tl.get("title", {}).get("font_size", 10), "bold": False, "text_color": "#000000", "fill": "transparent", "align": "left"}
        box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(2.2), Inches(.25))
        set_text_exact(box, "Project 진행 일정(案)", title_cfg)
        for i, (date, note) in enumerate(zip(data.get("timeline", []), data.get("timeline_note", []))):
            # 빈 슬롯은 마디·텍스트상자를 만들지 않는다 (빈 텍스트상자 양식 위반 방지).
            if not str(date).strip() and not str(note).strip():
                continue
            center = x + .82 + i * ((w - 1.18) / 5)
            dot = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(center - .065), Inches(line_y - .04), Inches(.13), Inches(.13))
            dot.fill.solid(); dot.fill.fore_color.rgb = WHITE; dot.line.color.rgb = RGBColor(127, 127, 127); dot.line.width = Pt(2)
            if str(date).strip():
                dbox = slide.shapes.add_textbox(Inches(center - .42), Inches(y + h * .28), Inches(.84), Inches(.20))
                set_text_exact(dbox, date, {"font_latin": body_latin, "font_ea": body_ea, "font_size": tl.get("date_font_size", 9), "bold": False, "text_color": "#000000", "fill": "transparent", "align": "center"})
            if str(note).strip():
                nbox = slide.shapes.add_textbox(Inches(center - .48), Inches(y + h * .72), Inches(.96), Inches(.20))
                set_text_exact(nbox, note, {"font_latin": body_latin, "font_ea": body_ea, "font_size": tl.get("note_font_size", 8), "bold": False, "text_color": "#000000", "fill": "transparent", "align": "center"})

    # 표 캡션 【 표 】 정규화 — 스펙 3-4: 11pt Bold.
    for s in slide.shapes:
        if getattr(s, "has_text_frame", False):
            txt = s.text.strip()
            if txt.startswith("【") and txt.endswith("】"):
                for p in s.text_frame.paragraphs:
                    for r in p.runs:
                        _font_xml(r, cfg["body"].get("font_latin", "Corbel"), cfg["body"].get("font_ea", "나눔스퀘어"))
                        r.font.size = Pt(11)
                        r.font.bold = True

    # 원본 샘플의 작성 안내 상자 제거.
    for s in list(slide.shapes):
        if getattr(s, "has_text_frame", False):
            txt = s.text.strip()
            if "영문 Corbel" in txt or "동일 주제" in txt or "나눔스퀘어 ExtraBold (24)" in txt or txt == "XX":
                remove_shape(s)


def _remove_slide_at(prs: Presentation, index: int) -> None:
    slide_id = prs.slides._sldIdLst[index]
    rel_id = slide_id.rId
    prs.part.drop_rel(rel_id)
    prs.slides._sldIdLst.remove(slide_id)


def _validate_generated_pptx(path: Path) -> None:
    """다운로드 전에 PPTX 압축과 슬라이드 루트 구조를 검증한다.

    python-pptx와 LibreOffice는 중복된 spTree 구조 노드를 묵인하지만 Microsoft
    PowerPoint는 파일 전체를 손상된 것으로 거부한다. 서버에서 그 상태를 미리 차단한다.
    """
    ns = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main"}
    try:
        with ZipFile(path) as package:
            damaged = package.testzip()
            if damaged:
                raise ValueError(f"PPTX 압축 항목이 손상되었습니다: {damaged}")
            slide_names = [
                name for name in package.namelist()
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
            ]
            if not slide_names:
                raise ValueError("PPTX에 슬라이드 XML이 없습니다.")
            for name in slide_names:
                root = etree.fromstring(package.read(name))
                tree = root.find("p:cSld/p:spTree", ns)
                if tree is None:
                    raise ValueError(f"{name}에 슬라이드 도형 트리가 없습니다.")
                nv_count = len(tree.findall("p:nvGrpSpPr", ns))
                grp_count = len(tree.findall("p:grpSpPr", ns))
                if nv_count != 1 or grp_count != 1:
                    raise ValueError(
                        f"{name}의 루트 그룹 구조가 잘못되었습니다 "
                        f"(nvGrpSpPr={nv_count}, grpSpPr={grp_count})."
                    )
        # 관계·콘텐츠 타입까지 python-pptx가 다시 읽을 수 있는지 최종 확인한다.
        Presentation(path)
    except (OSError, KeyError, etree.XMLSyntaxError) as exc:
        raise ValueError(f"생성된 PPTX 구조를 읽을 수 없습니다: {exc}") from exc


def _overflow_policy() -> dict[str, Any]:
    """넘침 처리 방식 — config/standard_rules.yaml 의 overflow 설정.

    split  : 글자 크기를 유지하고 다음 장으로 넘긴다 (기본, 스펙의 연속 슬라이드 규칙)
    shrink : 한 장에 다 넣되 글자를 줄인다 (이전 동작)
    """
    from app.services import validator

    cfg = (validator.load_rules().get("overflow") or {})
    mode = str(cfg.get("mode", "split")).lower()
    if mode not in ("split", "shrink"):
        mode = "split"
    try:
        min_scale = float(cfg.get("min_scale", 1.0))
    except (TypeError, ValueError):
        min_scale = 1.0
    return {"mode": mode, "min_scale": max(MIN_BODY_SCALE, min(1.0, min_scale))}


def _chunk_body(items: list[dict[str, Any]], width_in: float, first_h: float,
                cont_h: float, sizes: list[float], min_scale: float) -> list[list[dict[str, Any]]]:
    """본문을 상자에 들어갈 만큼씩 나눈다. 첫 장과 이어지는 장의 높이가 다르다."""
    if not items:
        return [[]]
    chunks: list[list[dict[str, Any]]] = []
    rest = list(items)
    while rest:
        height = first_h if not chunks else cont_h
        limit = height * 72 * 0.94
        take = len(rest)
        while take > 1 and _body_required_pt(rest[:take], width_in, sizes, min_scale) > limit:
            take -= 1
        chunks.append(rest[:take])
        rest = rest[take:]
        if len(chunks) >= 12:  # 안전장치 — 비정상 데이터로 무한 분할되는 것 방지
            if rest:
                chunks[-1].extend(rest)
            break
    return chunks


def expand_for_overflow(slides_data: list[dict[str, Any]], profile: dict[str, Any],
                        overrides: dict[str, Any] | None) -> list[dict[str, Any]]:
    """한 장에 안 들어가는 본문을 다음 장으로 넘겨 페이지를 늘린다.

    스펙 4장의 연속 슬라이드 규칙에 따라, 이어지는 장의 Lv1(대주제) 문단은
    흰색으로 숨겨 번호·들여쓰기 체계만 유지한다. 표·타임라인은 첫 장에만 둔다.
    """
    policy = _overflow_policy()
    if policy["mode"] != "split":
        return slides_data

    expanded: list[dict[str, Any]] = []
    for data in slides_data:
        ptype = max(1, min(3, int(data.get("template_type", 2))))
        cfg = effective_layout(profile, overrides, data.get("slide_number", 0))
        body_cfg = cfg["body"]
        sizes = [float(x) for x in body_cfg.get("level_sizes", [14, 13, 12, 11, 10])]
        width = float(body_cfg["w"])
        first_h = available_body_height(ptype, cfg)
        cont_h = available_body_height(2, cfg)
        items = data.get("body") or []

        chunks = _chunk_body(items, width, first_h, cont_h, sizes, policy["min_scale"])
        first = deepcopy(data)
        first["body"] = chunks[0]
        expanded.append(first)
        if len(chunks) == 1:
            continue

        # 이어지는 장에 반복해 넣을 대주제(Lv1) 문단
        topic = next((x for x in items if int(x.get("level", 0)) == 0), None)
        for chunk in chunks[1:]:
            cont = deepcopy(data)
            cont["template_type"] = 2  # 표·타임라인 없는 본문 전용 장
            cont.pop("table1", None); cont.pop("table2", None)
            cont.pop("timeline", None); cont.pop("timeline_note", None)
            body = list(chunk)
            if topic is not None and (not body or int(body[0].get("level", 0)) != 0):
                hidden = deepcopy(topic)
                hidden["hidden"] = True
                body.insert(0, hidden)
            cont["body"] = body
            cont["continuation"] = True
            expanded.append(cont)

    for i, data in enumerate(expanded, 1):
        data["slide_number"] = i
    return expanded


def generate_report(template_path: Path, unit: dict[str, Any], slides_data: list[dict[str, Any]], out_path: Path, overrides: dict[str, Any] | None = None) -> int:
    """표준 양식 PPTX를 만들고 실제로 생성된 장수를 돌려준다.

    본문이 넘쳐 다음 장으로 나뉘면 입력 슬라이드 수보다 많아진다.
    """
    if not template_path.exists():
        raise FileNotFoundError(f"기준 템플릿을 찾을 수 없습니다: {template_path}")
    if not slides_data:
        raise ValueError("자동 배열할 슬라이드 데이터가 없습니다.")
    prs = Presentation(template_path)
    profile = apply_rule_fonts(exact_template_profile(template_path))
    # 한 장에 안 들어가는 본문은 다음 장으로 넘긴다 (글자 크기 유지).
    slides_data = expand_for_overflow(slides_data, profile, overrides)
    # 앞 3장은 출력 위치가 아니라 유형별 원본 패턴이다. 들어오는 슬라이드마다
    # 해당 패턴을 복제한 뒤 원본 샘플 3장을 제거한다.
    source_count = len(prs.slides)
    if source_count < 3:
        raise ValueError("기준 템플릿에는 3개의 페이지 유형 샘플이 필요합니다.")
    for data in slides_data:
        source_type = max(1, min(3, int(data.get("template_type", 2))))
        clone_slide(prs, source_type - 1)
    for _ in range(source_count):
        _remove_slide_at(prs, 0)
    global_cfg = effective_layout(profile, overrides, 0)
    apply_layout_base(prs, global_cfg)
    for i, data in enumerate(slides_data, 1):
        data["template_type"] = max(1, min(3, int(data.get("template_type", 2))))
        cfg = effective_layout(profile, overrides, i)
        fill_slide(prs.slides[i - 1], data, i, cfg)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp.pptx")
    try:
        prs.save(tmp)
        _validate_generated_pptx(tmp)
        tmp.replace(out_path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return len(slides_data)


def append_slide_from_source(dest: Presentation, source_slide, layout_index: int = 11) -> None:
    new_slide = dest.slides.add_slide(dest.slide_layouts[layout_index])
    for sh in list(new_slide.shapes):
        remove_shape(sh)
    for shape in source_slide.shapes:
        new_slide.shapes._spTree.insert_element_before(deepcopy(shape._element), "p:extLst")


def merge_reports(paths: list[Path], out_path: Path) -> None:
    if not paths:
        raise ValueError("병합할 보고서가 없습니다.")
    base = Presentation(paths[0])
    for path in paths[1:]:
        src = Presentation(path)
        for slide in src.slides:
            append_slide_from_source(base, slide)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp.pptx")
    try:
        base.save(tmp)
        _validate_generated_pptx(tmp)
        tmp.replace(out_path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
