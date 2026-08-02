"""표준 양식 PPTX 생성 — _ref/report_ai_prototype/build_prototype.py 이식.

데모 데이터 생성부(BUSINESS_UNITS, make_demo_slides 등)는 제외하고
프로파일 추출·슬라이드 생성·병합 로직만 옮겼다.
"""
from __future__ import annotations

import math
from copy import deepcopy
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_SHAPE_TYPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

EMU = 914400
BLACK = RGBColor(0, 0, 0)
WHITE = RGBColor(255, 255, 255)


def inch(v: int | float) -> float:
    return round(float(v) / EMU, 6)


def parse_hex(value: str | None, fallback: str = "#000000") -> RGBColor:
    raw = (value or fallback).lstrip("#")
    if len(raw) != 6:
        raw = fallback.lstrip("#")
    return RGBColor(int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))


def safe_rgb(color) -> str | None:
    try:
        if color.rgb is not None:
            return f"#{color.rgb}"
    except Exception:
        return None
    return None


def _font_xml(run, latin: str = "Corbel", east_asia: str = "나눔스퀘어") -> None:
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
            out.append({
                "level": level - 1,
                "size_pt": (float(rpr.get("sz")) / 100) if rpr is not None and rpr.get("sz") else None,
                "margin_left_in": float(node.get("marL", 0)) / EMU,
                "indent_in": float(node.get("indent", 0)) / EMU,
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
    for element in source.shapes._spTree:
        if element.tag.endswith("}extLst"):
            continue
        dest.shapes._spTree.insert_element_before(deepcopy(element), "p:extLst")
    return dest


def _find_title(slide):
    return next((s for s in slide.shapes if getattr(s, "has_text_frame", False) and s.top < Inches(0.8) and s.left < Inches(1.2)), None)


def _find_sidebar(slide):
    return next((s for s in slide.shapes if s.name == "직사각형 1"), None)


def _find_body(slide):
    return next((s for s in slide.shapes if getattr(s, "is_placeholder", False) and s.width > Inches(8)), None)


def _estimated_fit_size(text: str, width_in: float, height_in: float, base_pt: float, min_pt: float = 6.0, line_factor: float = 1.25) -> float:
    """한/영 혼용 텍스트 박스의 보수적 폰트 크기 추정.

    python-pptx에서는 PowerPoint 실제 렌더러를 쓸 수 없으므로 박스 폭으로
    필요한 줄 수를 추정해 넘칠 때만 폰트를 줄인다.
    """
    text = str(text or "")
    if not text.strip() or width_in <= 0 or height_in <= 0:
        return base_pt
    size = float(base_pt)
    while size > min_pt:
        chars_per_line = max(3, int((width_in * 72) / (size * 0.82)))
        lines = 0
        for raw_line in text.splitlines() or [text]:
            lines += max(1, math.ceil(max(1, len(raw_line)) / chars_per_line))
        required = lines * size * line_factor
        if required <= height_in * 72 * 0.92:
            break
        size -= 0.5
    return round(max(min_pt, size), 1)


def _body_fit_scale(items: list[dict[str, Any]], width_in: float, height_in: float, sizes: list[float]) -> float:
    if not items or width_in <= 0 or height_in <= 0:
        return 1.0
    scale = 1.0
    while scale > 0.50:
        required = 0.0
        for item in items:
            level = max(0, min(4, int(item.get("level", 0))))
            size = float(sizes[level]) * scale
            usable_width = max(0.8, width_in - 0.18 * level)
            chars_per_line = max(4, int((usable_width * 72) / (size * 0.80)))
            lines = max(1, math.ceil(len(str(item.get("text", ""))) / chars_per_line))
            required += lines * size * 1.32
        if required <= height_in * 72 * 0.94:
            break
        scale -= 0.04
    return max(0.50, round(scale, 2))


def set_text_exact(shape, text: str, cfg: dict[str, Any], vertical=MSO_ANCHOR.MIDDLE) -> None:
    tf = shape.text_frame
    tf.clear()
    tf.word_wrap = bool(cfg.get("word_wrap", True))
    tf.vertical_anchor = vertical
    p = tf.paragraphs[0]
    p.alignment = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}.get(cfg.get("align"), PP_ALIGN.LEFT)
    r = p.add_run()
    r.text = text
    _font_xml(r, cfg.get("font_latin", "Corbel"), cfg.get("font_ea", "나눔스퀘어"))
    base_size = float(cfg.get("font_size", 12))
    fitted_size = _estimated_fit_size(text, inch(shape.width), inch(shape.height), base_size, float(cfg.get("min_font_size", 6)))
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
    scale = _body_fit_scale(items, inch(shape.width), inch(shape.height), sizes)
    fitted_sizes = [max(6.0, round(x * scale, 1)) for x in sizes]
    ea_fonts = cfg.get("level_ea_fonts", ["나눔스퀘어 ExtraBold"] * 3 + ["나눔스퀘어"] * 2)
    bolds = cfg.get("level_bold", [True, True, False, False, False])
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        level = max(0, min(4, int(item.get("level", 0))))
        p.level = level
        p.alignment = PP_ALIGN.LEFT
        r = p.add_run(); r.text = item.get("text", "")
        _font_xml(r, cfg.get("font_latin", "Corbel"), ea_fonts[level])
        r.font.size = Pt(fitted_sizes[level])
        r.font.bold = bool(bolds[level] if item.get("bold") is None else item.get("bold"))
        r.font.color.rgb = parse_hex(cfg.get("text_color"), "#000000")


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
    _font_xml(r, cfg.get("font_latin", "Corbel"), "나눔스퀘어 ExtraBold" if (header or key) else cfg.get("font_ea", "나눔스퀘어"))
    base_size = float(cfg.get("header_font_size", 10.5) if header else cfg.get("body_font_size", 10))
    r.font.size = Pt(_estimated_fit_size(text, width_in, height_in, base_size, 6.0, 1.15))
    r.font.bold = bool(header or key)
    r.font.color.rgb = parse_hex(cfg.get("text_color"), "#000000")
    if header:
        p.alignment = PP_ALIGN.CENTER
        cell.fill.solid(); cell.fill.fore_color.rgb = parse_hex(cfg.get("header_fill"), "#DCE6F2")


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
    for attr, key in (("left", "x"), ("top", "y"), ("width", "w"), ("height", "h")):
        if key in cfg:
            setattr(shape, attr, Inches(float(cfg[key])))


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
    for c in range(2):
        cell = frame_shape.table.cell(0, c)
        cell.fill.solid(); cell.fill.fore_color.rgb = parse_hex(frame.get("header_fill"), "#B7D3EE")
        p = cell.text_frame.paragraphs[0]
        for r in p.runs:
            _font_xml(r, frame.get("header_font_latin", "Corbel"), frame.get("header_font_ea", "나눔스퀘어 ExtraBold"))
            r.font.size = Pt(float(frame.get("header_font_size", 14)))
            r.font.bold = True
            r.font.color.rgb = parse_hex(frame.get("header_text_color"), "#000000")


def fill_slide(slide, data: dict[str, Any], slide_no: int, cfg: dict[str, Any]) -> None:
    ptype = data["template_type"]
    title = _find_title(slide)
    if title:
        _apply_geometry(title, cfg["title"]); set_text_exact(title, data["page_title"], cfg["title"])
    sidebar = _find_sidebar(slide)
    if sidebar:
        _apply_geometry(sidebar, cfg["sidebar"]); set_text_exact(sidebar, data["sidebar"], cfg["sidebar"])
    body = _find_body(slide)
    if body:
        _apply_geometry(body, cfg["body"]); write_body_exact(body, data["body"], cfg["body"])

    tables = sorted([s for s in slide.shapes if s.shape_type == MSO_SHAPE_TYPE.TABLE], key=lambda s: s.top)
    if ptype == 1 and tables:
        _apply_geometry(tables[0], cfg["table_type1"]); fill_table_preserve(tables[0], data.get("table1", {"headers": ["구분", "협의 경과"], "rows": []}), cfg["table_type1"])
    if ptype == 3 and len(tables) >= 2:
        _apply_geometry(tables[0], cfg["table_type3_top"]); fill_table_preserve(tables[0], data.get("table1", {"headers": ["구분", "개요", "추진방안"], "rows": []}), cfg["table_type3_top"])
        _apply_geometry(tables[1], cfg["table_type3_bottom"]); fill_table_preserve(tables[1], data.get("table2", {"headers": ["구분", "개요", "지원", "Infra", "수용성"], "rows": []}), cfg["table_type3_bottom"])

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
        line_y = y + h * .58
        line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x + .20), Inches(line_y), Inches(w - .22), Inches(.055))
        line.fill.solid(); line.fill.fore_color.rgb = RGBColor(191, 191, 191); line.line.fill.background()
        arrow = slide.shapes.add_shape(MSO_SHAPE.ISOSCELES_TRIANGLE, Inches(x + w - .12), Inches(line_y - .055), Inches(.16), Inches(.16))
        arrow.rotation = 90; arrow.fill.solid(); arrow.fill.fore_color.rgb = RGBColor(191, 191, 191); arrow.line.fill.background()
        title_cfg = {"font_latin": "Corbel", "font_ea": "나눔스퀘어", "font_size": tl.get("title", {}).get("font_size", 10), "bold": False, "text_color": "#000000", "fill": "transparent", "align": "left"}
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
                set_text_exact(dbox, date, {"font_latin": "Corbel", "font_ea": "나눔스퀘어", "font_size": tl.get("date_font_size", 9), "bold": False, "text_color": "#000000", "fill": "transparent", "align": "center"})
            if str(note).strip():
                nbox = slide.shapes.add_textbox(Inches(center - .48), Inches(y + h * .72), Inches(.96), Inches(.20))
                set_text_exact(nbox, note, {"font_latin": "Corbel", "font_ea": "나눔스퀘어", "font_size": tl.get("note_font_size", 8), "bold": False, "text_color": "#000000", "fill": "transparent", "align": "center"})

    # 표 캡션 【 표 】 정규화 — 스펙 3-4: Corbel 11pt Bold.
    for s in slide.shapes:
        if getattr(s, "has_text_frame", False):
            txt = s.text.strip()
            if txt.startswith("【") and txt.endswith("】"):
                for p in s.text_frame.paragraphs:
                    for r in p.runs:
                        _font_xml(r, "Corbel", "나눔스퀘어")
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


def generate_report(template_path: Path, unit: dict[str, Any], slides_data: list[dict[str, Any]], out_path: Path, overrides: dict[str, Any] | None = None) -> None:
    if not template_path.exists():
        raise FileNotFoundError(f"기준 템플릿을 찾을 수 없습니다: {template_path}")
    if not slides_data:
        raise ValueError("자동 배열할 슬라이드 데이터가 없습니다.")
    prs = Presentation(template_path)
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
    profile = exact_template_profile(template_path)
    global_cfg = effective_layout(profile, overrides, 0)
    apply_layout_base(prs, global_cfg)
    for i, data in enumerate(slides_data, 1):
        data["template_type"] = max(1, min(3, int(data.get("template_type", 2))))
        cfg = effective_layout(profile, overrides, i)
        fill_slide(prs.slides[i - 1], data, i, cfg)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp.pptx")
    prs.save(tmp)
    tmp.replace(out_path)


def append_slide_from_source(dest: Presentation, source_slide, layout_index: int = 11) -> None:
    new_slide = dest.slides.add_slide(dest.slide_layouts[layout_index])
    for sh in list(new_slide.shapes):
        remove_shape(sh)
    for element in source_slide.shapes._spTree:
        if element.tag.endswith("}extLst"):
            continue
        new_slide.shapes._spTree.insert_element_before(deepcopy(element), "p:extLst")


def merge_reports(paths: list[Path], out_path: Path) -> None:
    if not paths:
        raise ValueError("병합할 보고서가 없습니다.")
    base = Presentation(paths[0])
    for path in paths[1:]:
        src = Presentation(path)
        for slide in src.slides:
            append_slide_from_source(base, slide)
    base.save(out_path)
