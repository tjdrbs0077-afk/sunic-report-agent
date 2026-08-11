"""시연용 샘플 보고서의 사용자 노출 문구 회귀 테스트."""
import json
import unittest
from pathlib import Path

from app.services import demo_data


class DemoReportWordingTests(unittest.TestCase):
    def test_sample_names_do_not_use_business_unit_wording(self):
        for report in demo_data.BUSINESS_UNITS:
            with self.subTest(report=report["id"]):
                self.assertNotIn("사업단", report["name"])

    def test_generated_sample_content_does_not_use_business_unit_wording(self):
        for report in demo_data.BUSINESS_UNITS:
            with self.subTest(report=report["id"]):
                payload = demo_data.build_payload(report["id"])
                serialized = json.dumps(payload, ensure_ascii=False)
                self.assertNotIn("사업단", serialized)

    def test_sample_generation_buttons_use_report_wording(self):
        index = (Path(__file__).parents[1] / "app" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("선택 보고서 생성", index)
        self.assertIn("전체 보고서 생성", index)
        self.assertNotIn("선택 사업단 생성", index)
        self.assertNotIn("전체 사업단 생성", index)


if __name__ == "__main__":
    unittest.main()
