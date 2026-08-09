import unittest
from unittest.mock import patch

from app.routers.reports import _set_report_archived, filter_report_index


class ReportArchiveTests(unittest.TestCase):
    def test_filter_defaults_legacy_reports_to_active(self):
        items = [{"id": "legacy"}, {"id": "archived", "archived": True}]
        self.assertEqual([item["id"] for item in filter_report_index(items)], ["legacy"])
        self.assertEqual([item["id"] for item in filter_report_index(items, True)], ["archived"])

    @patch("app.routers.reports.store.save_report_index")
    @patch("app.routers.reports.store.load_report_index")
    def test_archive_and_restore_preserve_report(self, load_index, save_index):
        items = [{"id": "r1", "name": "보고서", "status": "done"}]
        load_index.return_value = items

        archived = _set_report_archived("r1", True)
        self.assertTrue(archived["archived"])
        self.assertTrue(archived["archived_at"])

        restored = _set_report_archived("r1", False)
        self.assertFalse(restored["archived"])
        self.assertEqual(restored["archived_at"], "")
        self.assertEqual(save_index.call_count, 2)


if __name__ == "__main__":
    unittest.main()
