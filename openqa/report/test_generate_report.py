from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from generate_report import (
    find_biglinux_job,
    find_biglinux_jobs,
    load_application_metrics,
    load_application_metrics_from_jobs,
    load_module_runtimes,
    module_result,
    render_report,
    validation_badge,
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
                '{"system":{"kernel":"7.1"},"applications":[{"name":"Writer","status":"passed","rss_mib_peak":120.5,"pss_mib_peak":98.2,"process_count_peak":3,"application_exit_code":0}]}',
                encoding="utf-8",
            )

            job, variables = find_biglinux_job(root)
            system, applications = load_application_metrics(job)

        self.assertEqual(job, biglinux)
        self.assertEqual(variables["DISTRI"], "biglinux")
        self.assertEqual(system["kernel"], "7.1")
        self.assertEqual(applications[0]["name"], "Writer")
        self.assertEqual(applications[0]["pss_mib_peak"], 98.2)

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

    def test_renders_per_application_memory(self) -> None:
        report = render_report(
            {"DISTRI": "BigLinux"},
            [],
            {},
            [
                {
                    "name": "Dolphin",
                    "status": "passed",
                    "rss_mib_peak": 120.5,
                    "pss_mib_peak": 98.2,
                    "process_count_peak": 3,
                }
            ],
        )

        self.assertIn("RSS pico", report)
        self.assertIn("120.5 MiB", report)
        self.assertIn("98.2 MiB", report)

    def test_renders_application_failure_reason(self) -> None:
        report = render_report(
            {"DISTRI": "BigLinux"},
            [],
            {},
            [{"name": "Broken App", "status": "failed", "error": "window not found"}],
        )

        self.assertIn("Motivo", report)
        self.assertIn("window not found", report)

    def test_accepts_simple_atspi_open_validation(self) -> None:
        report = render_report(
            {"DISTRI": "BigLinux"},
            [],
            {},
            [
                {
                    "name": "App",
                    "status": "passed",
                    "accessible_window": True,
                    "validation_mode": "atspi-open",
                }
            ],
        )

        self.assertIn('class="badge badge-passed"', report)

    def test_labels_mpv_x11_fallback_without_claiming_atspi(self) -> None:
        badge = validation_badge(
            {
                "status": "passed",
                "validation_mode": "x11-open",
                "accessible_window": False,
            }
        )

        self.assertIn("Fallback X11", badge)
        self.assertNotIn("badge-passed", badge)

    def test_aggregates_application_metrics_from_all_firmware_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bios = root / "bios"
            uefi = root / "uefi"
            bios.mkdir()
            uefi.mkdir()
            (bios / "vars.json").write_text(
                '{"DISTRI":"biglinux","BUILD":"candidate-release_bios"}',
                encoding="utf-8",
            )
            (uefi / "vars.json").write_text(
                '{"DISTRI":"biglinux","BUILD":"candidate-release_uefi","UEFI":"1"}',
                encoding="utf-8",
            )
            (bios / "application-metrics.json").write_text(
                '{"applications":[{"name":"Dolphin"}]}', encoding="utf-8"
            )
            (uefi / "application-metrics.json").write_text(
                '{"applications":[{"name":"Brave"}]}', encoding="utf-8"
            )

            jobs = find_biglinux_jobs(root)
            system, applications = load_application_metrics_from_jobs(jobs)

        self.assertEqual(len(jobs), 2)
        self.assertEqual(system["jobs_tested"], 2)
        self.assertEqual(
            [(item["job"], item["firmware"]) for item in applications],
            [
                ("candidate-release_bios", "BIOS"),
                ("candidate-release_uefi", "UEFI"),
            ],
        )

    def test_reads_compressed_application_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory)
            metrics = job / "application-metrics.json.gz"
            with gzip.open(metrics, "wt", encoding="utf-8") as stream:
                json.dump(
                    {"system": {"kernel": "7.1"}, "applications": [{"name": "GIMP"}]},
                    stream,
                )

            system, applications = load_application_metrics(job)

        self.assertEqual(system["kernel"], "7.1")
        self.assertEqual(applications[0]["name"], "GIMP")


if __name__ == "__main__":
    unittest.main()
