"""표 배치 회귀 테스트 — 본문과 표가 겹치던 결함, 표 사이 간격이 벌어지던 결함.

양식에서 실측한 표 좌표는 '샘플 보고서의 짧은 본문'을 전제로 한 값이다.
실제 보고서를 그 좌표에 그대로 놓으면
  - 본문이 길 때 → 글자가 표 위로 흘러 겹친다
  - 본문이 짧을 때 → 상단 표와 하단 표 사이가 1.4in 벌어진다
그래서 표를 본문 아래로 흘려 쌓는다 (builder.table_tops).
"""
import unittest

from app.services.builder import (FRAME_PAD, TABLE_GAP, _body_used_height,
                                  available_body_height, body_line_gap,
                                  stack_floor, table_keys, table_tops)

# 보고양식_Sample_4팀.pptx 실측 좌표 (data/template_profile.json 과 같은 값)
PROFILE = {
    "frame": {"x": 0.298612, "y": 0.690927, "w": 10.249893, "h": 6.524349},
    "body": {"x": 1.814237, "y": 1.200095, "w": 8.710776, "h": 6.015182,
             "level_sizes": [14, 13, 12, 11, 10]},
    "table_type1": {"x": 2.89757, "y": 3.548492, "w": 7.519097, "h": 2.322441},
    "table_type3_top": {"x": 2.897568, "y": 2.512108, "w": 7.519096, "h": 1.237892},
    "table_type3_bottom": {"x": 2.897569, "y": 5.17644, "w": 7.519096, "h": 0.83248},
    "timeline": {"x": 2.7, "y": 6.25, "w": 7.65, "h": 0.82},
}
FLOOR = PROFILE["frame"]["y"] + PROFILE["frame"]["h"] - FRAME_PAD


def _body(lines: int) -> list[dict]:
    return [{"level": i % 3, "text": "냉각 중심의 실행 범위와 담당 조직을 구체화"}
            for i in range(lines)]


def _rect(key: str, tops: dict[str, float]) -> tuple[float, float]:
    """(위, 아래) 좌표."""
    return tops[key], tops[key] + PROFILE[key]["h"]


class TableStackingTests(unittest.TestCase):
    def test_tables_never_overlap_the_body(self):
        for lines in (2, 5, 9, 14, 25, 60):
            tops = table_tops(3, PROFILE, _body(lines))
            used = min(_body_used_height(_body(lines), PROFILE),
                       available_body_height(3, PROFILE))
            body_bottom = PROFILE["body"]["y"] + used
            self.assertGreaterEqual(
                round(min(tops.values()), 3), round(body_bottom, 3) - 0.001,
                f"본문 {lines}줄에서 표가 본문 글자 위로 올라온다",
            )

    def test_tables_never_overlap_each_other(self):
        for lines in (2, 9, 25):
            tops = table_tops(3, PROFILE, _body(lines))
            _, top_bottom = _rect("table_type3_top", tops)
            bottom_top, _ = _rect("table_type3_bottom", tops)
            self.assertGreaterEqual(round(bottom_top, 3), round(top_bottom, 3))

    def test_gap_between_tables_is_tight(self):
        """실측 좌표 그대로면 1.426in 이 벌어진다 — 그 절반도 안 되게."""
        tops = table_tops(3, PROFILE, _body(3))
        _, top_bottom = _rect("table_type3_top", tops)
        bottom_top, _ = _rect("table_type3_bottom", tops)
        self.assertAlmostEqual(bottom_top - top_bottom, TABLE_GAP, places=3)

    def test_table_hugs_the_end_of_the_body_text(self):
        """표는 '본문 다음 문단'처럼 글 바로 아래 문단 간격만큼만 띄운다.

        양식 실측 y(2.512)를 지키면 본문이 짧을 때 글 끝과 표 사이가 텅 빈다.
        """
        for lines in (1, 3, 6):
            tops = table_tops(3, PROFILE, _body(lines))
            body_end = PROFILE["body"]["y"] + _body_used_height(_body(lines), PROFILE)
            self.assertAlmostEqual(tops["table_type3_top"] - body_end,
                                   body_line_gap(PROFILE), places=2,
                                   msg=f"본문 {lines}줄에서 글과 표 사이가 문단 간격이 아니다")

    def test_gap_matches_the_body_paragraph_spacing(self):
        """간격은 별도 상수가 아니라 본문 문단 간격(10pt)에서 온다."""
        self.assertAlmostEqual(body_line_gap(PROFILE), 10 / 72, places=3)

    def test_long_body_pushes_the_first_table_down(self):
        short = table_tops(3, PROFILE, _body(2))["table_type3_top"]
        long = table_tops(3, PROFILE, _body(12))["table_type3_top"]
        self.assertGreater(long, short)

    def test_tables_stay_inside_the_frame(self):
        for ptype in (1, 3):
            for lines in (2, 12, 40):
                tops = table_tops(ptype, PROFILE, _body(lines))
                for key in table_keys(ptype):
                    self.assertLessEqual(round(_rect(key, tops)[1], 3),
                                         round(stack_floor(ptype, PROFILE), 3) + 0.001)

    def test_type1_table_never_reaches_the_timeline_band(self):
        """유형 1 하단에는 타임라인 띠가 고정으로 깔린다 — 표가 그 위를 덮으면 안 된다."""
        self.assertLess(stack_floor(1, PROFILE), PROFILE["timeline"]["y"])
        for lines in (2, 8, 20, 50):
            tops = table_tops(1, PROFILE, _body(lines))
            self.assertLessEqual(round(_rect("table_type1", tops)[1], 3),
                                 round(PROFILE["timeline"]["y"], 3))

    def test_pages_without_tables_get_no_layout(self):
        self.assertEqual(table_tops(2, PROFILE, _body(5)), {})
        self.assertEqual(table_keys(2), [])


class AvailableBodyHeightTests(unittest.TestCase):
    def test_body_gets_the_room_left_above_the_table_stack(self):
        """예전에는 표의 실측 y 에서 잘라 본문이 0.86in 밖에 못 썼다."""
        available = available_body_height(3, PROFILE)
        stack = (PROFILE["table_type3_top"]["h"] + PROFILE["table_type3_bottom"]["h"]
                 + TABLE_GAP)
        expected = FLOOR - stack - body_line_gap(PROFILE) - PROFILE["body"]["y"]
        self.assertAlmostEqual(available, round(expected, 3), places=3)
        self.assertGreater(available, 2.5)

    def test_type1_body_room_stops_above_the_timeline(self):
        room = available_body_height(1, PROFILE)
        end = PROFILE["body"]["y"] + room + body_line_gap(PROFILE) + PROFILE["table_type1"]["h"]
        self.assertLessEqual(round(end, 3), round(PROFILE["timeline"]["y"], 3))

    def test_pages_without_tables_use_the_whole_body_box(self):
        self.assertAlmostEqual(available_body_height(2, PROFILE),
                               round(PROFILE["body"]["h"], 3), places=3)


if __name__ == "__main__":
    unittest.main()
