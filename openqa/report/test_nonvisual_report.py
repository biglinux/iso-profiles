import json
from pathlib import Path
import tempfile
import unittest
from nonvisual_report import load_nonvisual, render_nonvisual_html, render_nonvisual_markdown, EXPECTED


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

    def test_empty_outputs_do_not_claim_four_completed_tasks(self):
        for render in (render_nonvisual_html, render_nonvisual_markdown):
            output = render([])
            self.assertIn("Não há evidência", output)
            self.assertIn("opcionais", output)
            self.assertNotIn("cobre quatro", output)

    def test_partial_output_does_not_claim_complete_task_coverage(self):
        output = render_nonvisual_markdown([{"name": "kate", "status": "inconclusive"}])
        self.assertIn("0/1", output)
        self.assertIn("com evidência registrada", output)
        self.assertNotIn("cobre quatro", output)
