# SPDX-License-Identifier: GPL-2.0-or-later
"""Failure-path tests for the same report interface used by reusable CI."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from finalize_report import finalize
from report_fixture import create, verify
from report_outcome import summarize

ROOT = Path(__file__).resolve().parents[2]


class PipelineTests(unittest.TestCase):
    def test_synthetic_producer_has_expected_exit_and_verdict(self):
        for scenario, expected, exit_code in (("success", "ok", 0), ("failure", "fail", 17),
                                               ("incomplete", "unknown", 0)):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.assertEqual(create(scenario, root), exit_code)
                self.assertEqual(summarize(root)["result"], expected)

    def test_cli_regeneration_preserves_recorded_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create("success", root / "evidence")
            output = root / "report"
            finalize(root / "evidence", output, context={"name": "bios", "status": "failure", "runner_exit_code": "101"})
            run = subprocess.run([sys.executable, str(ROOT / "openqa/report/finalize_report.py"),
                                  "--results-root", str(root / "evidence"), "--output-dir", str(output)],
                                 env={"PATH": os.environ["PATH"]}, capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stderr)
            result = json.loads((output / "RESULTADO.json").read_text())
            self.assertEqual(result["result"], "fail")
            self.assertEqual(result["context"]["runner_exit_code"], "101")

    def test_missing_artifacts_cannot_pass_publication_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "three published artifacts"):
                verify(Path(tmp))

    def test_report_fixture_has_no_image_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create("success", root)
            self.assertFalse(list(root.rglob("*.png")))
            self.assertFalse(list(root.rglob("*.svg")))
