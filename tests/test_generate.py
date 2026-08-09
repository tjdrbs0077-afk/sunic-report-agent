import unittest

from app.routers.generate import generation_suffix


class GenerateNamingTests(unittest.TestCase):
    def test_editor_download_is_named_as_edited_copy(self):
        self.assertEqual(generation_suffix({}, edited_copy=True), "_수정본")

    def test_saved_layout_uses_edited_suffix_for_legacy_generate(self):
        overrides = {"global": {"title": {"font_size": 22}}, "slides": {}}
        self.assertEqual(generation_suffix(overrides), "_편집본")

    def test_plain_generate_keeps_auto_layout_suffix(self):
        self.assertEqual(generation_suffix({}), "_자동배열본")


if __name__ == "__main__":
    unittest.main()
