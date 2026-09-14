import json
from pathlib import Path
import tempfile
import unittest
from nonvisual_report import load_nonvisual, render_nonvisual_html, EXPECTED


class NonvisualReportTest(unittest.TestCase):
    def test_absence_never_claims_accessibility(self):
        self.assertIn("Não há evidência", render_nonvisual_html([]))

    def test_incomplete_cases_are_inconclusive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "nonvisual-contracts.json").write_text('{"schema_version":1,"cases":[]}')
            self.assertEqual(load_nonvisual(path)[0]["status"], "inconclusive")

    def test_pass_needs_independent_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "nonvisual-contracts.json").write_text(json.dumps({"schema_version": 1,
                "cases": [{"name": name, "status": "passed"} for name in EXPECTED]}))
            self.assertTrue(all(x["status"] == "inconclusive" for x in load_nonvisual(path)))

    def test_untrusted_content_is_escaped(self):
        self.assertNotIn("<script>", render_nonvisual_html([{"name": "<script>"}]))
