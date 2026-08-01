from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from generate_report import (
    find_biglinux_job,
    load_application_metrics,
    load_module_runtimes,
    module_result,
    render_report,
)


class GenerateReportTest(unittest.TestCase):
    def test_reads_module_duration_and_worst_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "details-applications.json")
            path.write_text(
                json.dumps(
                    {
                        "details": [
                            {
                                "result": "ok",
                                "frametime": ["0.2", "1.4"],
                                "screenshot": "one.png",
                            },
                            {"result": "fail", "frametime": ["2.0", "3.25"]},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = module_result(path, 17)

        self.assertEqual(result.name, "applications")
        self.assertEqual(result.result, "fail")
        self.assertEqual(result.duration_seconds, 17)
        self.assertEqual(result.checks, 2)
        self.assertEqual(result.screenshots, 1)

    def test_reads_authoritative_module_runtime_from_autoinst_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory)
            (job / "autoinst-log.txt").write_text(
                "||| finished boot_menu tests (runtime: 65 s)\n"
                "||| finished applications tests (runtime: 159.5 s)\n",
                encoding="utf-8",
            )

            runtimes = load_module_runtimes(job)

        self.assertEqual(runtimes, {"boot_menu": 65.0, "applications": 159.5})

    def test_finds_biglinux_job_and_optional_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            other = root / "other"
            biglinux = root / "biglinux"
            other.mkdir()
            biglinux.mkdir()
            (other / "vars.json").write_text('{"DISTRI":"example"}', encoding="utf-8")
            (biglinux / "vars.json").write_text(
                '{"DISTRI":"biglinux"}', encoding="utf-8"
            )
            (biglinux / "application-metrics.json").write_text(
                '{"system":{"kernel":"7.1"},"applications":[{"name":"Writer"}]}',
                encoding="utf-8",
            )

            job, variables = find_biglinux_job(root)
            system, applications = load_application_metrics(job)

        self.assertEqual(job, biglinux)
        self.assertEqual(variables["DISTRI"], "biglinux")
        self.assertEqual(system["kernel"], "7.1")
        self.assertEqual(applications[0]["name"], "Writer")

    def test_escapes_untrusted_result_content(self) -> None:
        report = render_report(
            {"DISTRI": "BigLinux <script>", "BUILD": 'build"unsafe'},
            [],
            {},
            [{"name": "<img src=x>", "status": "passed", "action": "save & close"}],
        )

        self.assertNotIn("<script>", report)
        self.assertNotIn("<img src=x>", report)
        self.assertIn("BigLinux &lt;script&gt;", report)
        self.assertIn("&lt;img src=x&gt;", report)
        self.assertIn("save &amp; close", report)


if __name__ == "__main__":
    unittest.main()
