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
from report_fixture import create, verify, published_artifacts
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
    def test_cli_reads_single_flattened_download(self):
        # Reproduce download-artifact's real single-match extraction layout.
        for scenario, expected in (("success", "ok"), ("failure", "fail"), ("incomplete", "unknown")):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                create(scenario, root / "download")
                output = root / "report"
                run = subprocess.run([sys.executable, str(ROOT / "openqa/report/finalize_report.py"),
                    "--results-root", str(root / "download"), "--output-dir", str(output), "--latest-attempts"],
                    env={"PATH": os.environ["PATH"], "GITHUB_RUN_ID": "123"},
                    capture_output=True, text=True, timeout=15)
                self.assertEqual(run.returncode, 0, run.stderr)
                summary = json.loads((output / "RESULTADO.json").read_text())
                self.assertEqual(summary["result"], expected)
                self.assertEqual(summary["application_counts"], {"skipped": 1})

    def test_named_newest_attempt_wins_over_flat_files(self):
        from finalize_report import latest_artifacts
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create("success", root)
            create("success", root / "openqa-bios-123-1")
            create("failure", root / "openqa-bios-123-2")
            self.assertEqual(latest_artifacts(root, "123"), [root / "openqa-bios-123-2"])

    def test_other_run_directory_is_not_a_flat_download(self):
        from finalize_report import latest_artifacts
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create("success", root / "openqa-bios-999-1")
            self.assertEqual(latest_artifacts(root, "123"), [])

    def test_isotovideo_failure_cannot_be_hidden_by_outer_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create("success", root)
            result = summarize(root, {"runner_exit_code": "0", "isotovideo_exit_code": "101"})
            self.assertEqual(result["result"], "fail")
            self.assertTrue(any("isotovideo" in problem for problem in result["problems"]))

    def test_corrupt_execution_metadata_cannot_approve(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create("success", root)
            (root / "run-status.json").write_bytes(b"invalid JSON")
            self.assertEqual(summarize(root)["result"], "unknown")


class PartialRerunReportsTest(unittest.TestCase):
    def artifacts(self, root, names):
        paths = []
        for name in names:
            path = root / ("biglinux-iso-validation-reportcheck-" + name)
            path.mkdir()
            paths.append(path)
        return paths

    def test_partial_rerun_retains_prior_successful_scenario(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self.artifacts(root, ["success-123-1", "failure-123-2", "incomplete-123-2"])
            self.assertEqual(set(published_artifacts(root)), set(paths))

    def test_attempt_order_is_numeric(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self.artifacts(root, ["success-123-1", "failure-123-2", "failure-123-10", "incomplete-123-1"])
            self.assertNotIn(paths[1], published_artifacts(root))
            self.assertIn(paths[2], published_artifacts(root))

    def test_broken_new_attempt_does_not_restore_old_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self.artifacts(root, ["failure-123-1", "failure-123-2", "incomplete-123-1", "success-123-1"])
            (paths[0] / "RESULTADO.json").write_text('{"result":"fail"}')
            (paths[1] / "RESULTADO.json").write_text('broken JSON')
            with self.assertRaises(json.JSONDecodeError):
                verify(root)

    def test_mixed_run_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.artifacts(root, ["success-123-1", "failure-123-1", "incomplete-456-1"])
            with self.assertRaisesRegex(ValueError, "different workflow runs"):
                published_artifacts(root)
