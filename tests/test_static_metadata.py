"""배포 링크 미리보기 메타데이터 회귀 테스트."""
import unittest
from pathlib import Path


class StaticMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = (Path(__file__).parents[1] / "app" / "static" / "index.html").read_text(encoding="utf-8")

    def test_document_title_uses_product_name(self):
        self.assertIn("<title>DOCU-C</title>", self.index)

    def test_open_graph_preview_uses_product_name_and_logo(self):
        self.assertIn('<meta property="og:title" content="DOCU-C">', self.index)
        self.assertIn('<meta property="og:site_name" content="DOCU-C">', self.index)
        self.assertIn('<meta property="og:image" content="https://suni-c-4team-report-agent.onrender.com/static/assets/DC_logo.png?v=3">', self.index)


if __name__ == "__main__":
    unittest.main()
