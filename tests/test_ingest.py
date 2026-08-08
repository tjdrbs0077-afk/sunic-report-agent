from __future__ import annotations

import unittest

from app.services.ingest import (
    _choose_title,
    _order_body_entries,
    normalize_body_items,
    strip_explicit_list_prefix,
)
from app.services.builder import _chunk_body


def entry(text: str, *, x: float = 0.6, y: float = 0.7, font: float = 14, bold: bool = False) -> dict:
    return {
        "text": text,
        "x": x,
        "y": y,
        "w": 5.0,
        "h": 0.4,
        "bottom": y + 0.4,
        "level": 0,
        "font_size": font,
        "bold": bold,
        "paragraph_index": 0,
        "shape_name": text,
        "is_placeholder": False,
        "is_bottom": False,
    }


class IngestNormalizationTests(unittest.TestCase):
    def test_existing_markers_are_removed_without_damaging_numeric_content(self) -> None:
        self.assertEqual(strip_explicit_list_prefix("1. 안정 공급 유지"), "안정 공급 유지")
        self.assertEqual(strip_explicit_list_prefix("① 안정 공급 유지"), "안정 공급 유지")
        self.assertEqual(strip_explicit_list_prefix("①"), "")
        self.assertEqual(strip_explicit_list_prefix("99.9%"), "99.9%")
        self.assertEqual(strip_explicit_list_prefix("2026 단계별 실행 로드맵"), "2026 단계별 실행 로드맵")

    def test_legacy_title_and_standalone_numbers_do_not_reappear_as_body(self) -> None:
        items = [
            {"text": "4대 추진 전략", "level": 0, "bold": True},
            {"text": "①", "level": 0, "bold": True},
            {"text": "②", "level": 1, "bold": True},
            {"text": "안정 공급 유지", "level": 2, "bold": True},
            {"text": "운영 효율화", "level": 3, "bold": True},
            {"text": "배관 인프라 안정성 유지", "level": 3, "bold": False},
        ]
        normalized = normalize_body_items(items, "4대 추진 전략")
        self.assertEqual([item["text"] for item in normalized], [
            "안정 공급 유지",
            "운영 효율화",
            "배관 인프라 안정성 유지",
        ])
        self.assertEqual([item["level"] for item in normalized], [0, 1, 1])

    def test_circled_number_cards_are_read_in_number_order(self) -> None:
        entries = [
            entry("①", x=0.9, y=2.1, font=17, bold=True),
            entry("②", x=7.1, y=2.1, font=17, bold=True),
            entry("안정 공급 유지", x=1.7, y=2.2, font=14, bold=True),
            entry("운영 효율화", x=7.9, y=2.2, font=14, bold=True),
            entry("안정성 유지 설명", x=0.9, y=3.0, font=11),
            entry("운영 효율화 설명", x=7.1, y=3.0, font=11),
            entry("③", x=0.9, y=4.8, font=17, bold=True),
            entry("④", x=7.1, y=4.8, font=17, bold=True),
            entry("저탄소 서비스", x=1.7, y=4.9, font=14, bold=True),
            entry("고객 플랫폼", x=7.9, y=4.9, font=14, bold=True),
            entry("저탄소 설명", x=0.9, y=5.7, font=11),
            entry("플랫폼 설명", x=7.1, y=5.7, font=11),
        ]
        ordered = _order_body_entries(entries)
        self.assertEqual([item["text"] for item in ordered], [
            "안정 공급 유지",
            "안정성 유지 설명",
            "운영 효율화",
            "운영 효율화 설명",
            "저탄소 서비스",
            "저탄소 설명",
            "고객 플랫폼",
            "플랫폼 설명",
        ])

    def test_title_selection_ignores_font_guides_section_codes_and_metrics(self) -> None:
        entries = [
            entry("04. GOALS & KPI", y=0.4, font=11, bold=True),
            entry("사업 목표 · 핵심 성과지표", y=0.72, font=27, bold=True),
            entry("나눔스퀘어 ExtraBold(볼드)", y=0.2, font=30, bold=True),
            entry("99.9%", x=6.6, y=2.1, font=34, bold=True),
        ]
        self.assertEqual(_choose_title(entries, 7.5)["text"], "사업 목표 · 핵심 성과지표")

    def test_empty_body_remains_empty_instead_of_repeating_the_title(self) -> None:
        self.assertEqual(normalize_body_items([], "표지 제목"), [])
        self.assertEqual(_chunk_body([], 7.5, 5.0, 5.0, [14, 13, 12, 11, 10], 1.0), [[]])


if __name__ == "__main__":
    unittest.main()
