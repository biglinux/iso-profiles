# SPDX-License-Identifier: GPL-2.0-or-later
"""Failure-injection coverage: a red/empty run must still emit usable reports."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
from finalize_report import emergency_pdf, finalize, latest_artifacts
from generate_report import module_result, render_report
from report_outcome import environment_context, module_outcome, summarize

REPOSITORY = Path(__file__).resolve().parents[2]


def fixture(root, result="ok", *, variables=True, details=None):
    work = root / "openqa-bios-build-123-1" / "work"
    (work / "testresults").mkdir(parents=True)
    if variables:
        (work / "vars.json").write_text(json.dumps({"DISTRI": "biglinux", "TEST": "bios", "UEFI": "0"}))
    (work / "testresults" / "result-live_desktop.json").write_text(json.dumps({
        "result": result, "execution_time": 1.5,
        "details": details if details is not None else [{"result": "ok"}]}))
    return work


class OutcomeTests(unittest.TestCase):
    def test_top_level_failure_cannot_be_hidden_by_good_details(self):
        self.assertEqual(module_outcome({"result": "fail", "details": [{"result": "ok"}]}), "fail")

    def test_module_with_no_details_keeps_its_result(self):
        for value in ("ok", "fail", "softfail", "skipped", "unknown"):
            with self.subTest(value=value):
                self.assertEqual(module_outcome({"result": value}), value)

    def test_skip_and_unknown_are_not_promoted_by_information(self):
        for value in ("skipped", "unknown"):
            self.assertEqual(module_outcome({"result": value, "details": [{"result": "ok"}]}), value)

    def test_runtime_comes_from_module_when_log_is_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = fixture(Path(temporary))
            self.assertEqual(module_result(work / "testresults/result-live_desktop.json").duration_seconds, 1.5)

    def test_partial_results_without_vars_are_not_discarded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture(root, "fail", variables=False)
            result = summarize(root)
            self.assertEqual(result["result"], "fail")
            self.assertEqual(len(result["modules"]), 1)

    def test_invalid_utf8_result_is_inconclusive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work = fixture(root)
            (work / "testresults/result-live_desktop.json").write_bytes(b"\xff\x00")
            self.assertEqual(summarize(root)["result"], "unknown")

    def test_missing_scheduled_module_prevents_green_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work = fixture(root)
            (work / "testresults/test_order.json").write_text(json.dumps([{"name": "live_desktop"}, {"name": "applications"}]))
            self.assertEqual(summarize(root)["result"], "unknown")

    def test_successful_modules_cannot_hide_failed_ci(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture(root)
            self.assertEqual(summarize(root, {"jobs": {"plan": {"result": "failure"}}})["result"], "fail")

    def test_failed_application_cannot_hide_behind_successful_module(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work = fixture(root)
            (work / "testresults/installed-application-smoke.json").write_text(json.dumps({
                "applications": [{"desktop_id": "broken.desktop", "status": "failed"}]}))
            self.assertEqual(summarize(root)["result"], "fail")

    def test_optional_application_skip_does_not_fail_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work = fixture(root)
            (work / "testresults/installed-application-smoke.json").write_text(json.dumps({
                "applications": [{"desktop_id": "optional.desktop", "status": "skipped"}]}))
            result = summarize(root)
            self.assertEqual(result["result"], "ok")
            self.assertEqual(result["application_counts"], {"skipped": 1})

    def test_missing_plan_prevents_green_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture(root)
            result = summarize(root, {"expected_plans": ["bios", "uefi"]})
            self.assertEqual(result["result"], "unknown")
            self.assertTrue(any("uefi" in reason for reason in result["problems"]))

    def test_no_test_evidence_is_never_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(summarize(Path(temporary), {"status": "success"})["result"], "unknown")

    def test_context_does_not_persist_outputs_or_secrets(self):
        with patch.dict(os.environ, {"REPORT_STEPS_JSON": json.dumps({
            "test": {"outcome": "failure", "outputs": {"password": "DO_NOT_PUBLISH"}}}),
            "REPORT_NEEDS_JSON": json.dumps({"plan": {"result": "failure", "outputs": {"token": "SECRET"}}})}):
            text = json.dumps(environment_context())
        self.assertNotIn("DO_NOT_PUBLISH", text)
        self.assertNotIn("SECRET", text)
        self.assertNotIn("outputs", text)

    def test_latest_attempt_is_numeric_and_does_not_select_older_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("openqa-bios-build-123-2", "openqa-bios-build-123-10",
                         "openqa-uefi-build-123-1", "openqa-bios-build-999-20"):
                (root / name).mkdir()
            selected = [p.name for p in latest_artifacts(root, "123")]
        self.assertEqual(selected, ["openqa-bios-build-123-10", "openqa-uefi-build-123-1"])


class FinalizerTests(unittest.TestCase):
    def check_products(self, output, pdf=False):
        for name in ("RESULTADO.md", "RESULTADO.json", "run-status.json", "biglinux-validation-report.html"):
            self.assertGreater((output / name).stat().st_size, 0, name)
        if pdf:
            self.assertTrue((output / "biglinux-iso-validation.pdf").read_bytes().startswith(b"%PDF-1.4"))

    def test_all_test_outcomes_produce_reports_without_changing_verdict(self):
        for value in ("ok", "fail", "softfail", "unknown"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "artifacts"
                output = Path(temporary) / "report"
                fixture(root, value)
                self.assertEqual(finalize(root, output, context={}), 0)
                self.check_products(output)
                self.assertEqual(json.loads((output / "RESULTADO.json").read_text())["result"], value)

    def test_failure_before_any_module_still_reports_failed_workflow(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "report"
            result = finalize(root / "missing", output, context={"status": "failure", "steps": {"kvm": {"outcome": "failure"}}})
            self.assertEqual(result, 0)
            self.check_products(output)
            self.assertIn("kvm", (output / "RESULTADO.md").read_text())
            self.assertEqual(json.loads((output / "RESULTADO.json").read_text())["result"], "fail")

    def test_missing_pdf_dependency_emits_fallback_and_reports_renderer_error(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(sys.modules, {"build_pdf_report": None}):
            root = Path(temporary)
            self.assertEqual(finalize(root / "missing", root / "report", pdf=True, context={}), 1)
            self.check_products(root / "report", pdf=True)
            self.assertIn("pdf:", (root / "report/RESULTADO.md").read_text())

    def test_broken_html_renderer_cannot_remove_summary(self):
        def broken(*args):
            args[1].write_text("partial")
            raise RuntimeError("DO_NOT_PUBLISH_EXCEPTION_PAYLOAD")
        with tempfile.TemporaryDirectory() as temporary, patch.dict(sys.modules, {"generate_report": types.SimpleNamespace(build=broken)}):
            root = Path(temporary)
            self.assertEqual(finalize(root / "missing", root / "report", context={}), 1)
            self.check_products(root / "report")
            self.assertNotIn("DO_NOT_PUBLISH_EXCEPTION_PAYLOAD", (root / "report/RESULTADO.md").read_text())
            self.assertNotEqual((root / "report/biglinux-validation-report.html").read_text(), "partial")

    def test_emergency_pdf_has_valid_xref_even_for_multiple_pages(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "report.pdf"
            emergency_pdf(path, ["Texto com (parênteses), barra \\ e 日本語"] * 120)
            content = path.read_bytes()
            offset = int(content.split(b"startxref\n")[1].splitlines()[0])
            self.assertTrue(content[offset:].startswith(b"xref\n"))
            self.assertIn(b"/Count 3", content)

    def test_regeneration_preserves_original_executor_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work = fixture(root)
            output = work / "report"
            context = {"status": "failure", "runner_exit_code": "101", "name": "bios"}
            self.assertEqual(finalize(root, output, context=context), 0)
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(finalize(root, output), 0)
            self.assertEqual(json.loads((output / "RESULTADO.json").read_text())["result"], "fail")
            self.assertEqual(json.loads((output / "run-status.json").read_text())["runner_exit_code"], "101")

    def test_real_cli_preflight_failure_writes_report_and_keeps_exit_code(self):
        with tempfile.TemporaryDirectory() as temporary:
            results = Path(temporary) / "results"
            command = ["bash", str(REPOSITORY / "openqa/production/run-plan.sh"),
                       "--plan", "bios", "--iso", str(Path(temporary) / "missing.iso"), "--results", str(results)]
            run = subprocess.run(command, capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 1, run.stderr)
            self.check_products(results / "report")
            context = json.loads((results / "report/run-status.json").read_text())
            self.assertEqual(context["runner_exit_code"], "1")
            self.assertIn("preflight", context["steps"])


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow = REPOSITORY / ".github/workflows/openqa-single-instance-experiment.yml"
        command = ["ruby", "-rjson", "-ryaml", "-e", "puts JSON.generate(YAML.safe_load_file(ARGV[0], permitted_classes: [], aliases: false))", str(workflow)]
        cls.jobs = json.loads(subprocess.check_output(command, text=True))["jobs"]

    def test_report_waits_for_all_results_and_runs_after_failures(self):
        report = self.jobs["report"]
        self.assertIn("always()", report["if"])
        self.assertEqual(set(report["needs"]), {"static", "plan", "applications-aggregate"})
        for name in ("Build reports from all available evidence", "Publish report in the Actions summary", "Upload the report"):
            step = next(s for s in report["steps"] if s.get("name") == name)
            self.assertIn("always()", step["if"])

    def test_report_is_required_without_ignoring_test_failures(self):
        gate = self.jobs["openqa-release-gate"]
        self.assertIn("report", gate["needs"])
        self.assertIn('"$plan_result" == success', gate["steps"][0]["run"])
        self.assertIn('"$report_result" == success', gate["steps"][0]["run"])
        self.assertIn('"$report_verdict" =~ ^(ok|softfail)$', gate["steps"][0]["run"])

    def test_plan_paths_exist_in_environment_before_setup_can_fail(self):
        self.assertIn("OPENQA_DIAGNOSTICS_DIR", self.jobs["plan"]["env"])
        self.assertIn("OPENQA_PLAN_REPORT_DIR", self.jobs["plan"]["env"])
        report = next(s for s in self.jobs["plan"]["steps"] if s.get("id") == "report")
        self.assertIn("always()", report["if"])
        self.assertIn("finalize_report.py", report["run"])


if __name__ == "__main__":
    unittest.main()
