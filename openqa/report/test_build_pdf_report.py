#!/usr/bin/env python3
"""Tests for build_pdf_report.py."""

from __future__ import annotations

import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    from build_pdf_report import encoded_screenshot, read_suite
except ImportError as error:  # fpdf2 and pillow are installed by the report job
    MISSING = str(error)
    encoded_screenshot = read_suite = None
else:
    MISSING = ""


def write_suite(root: Path, name: str, uefi: bool) -> Path:
    directory = root / f"openqa-{name}-audit-abc-1"
    results = directory / "results" / "1" / "testresults"
    results.mkdir(parents=True)
    variables = {"ISO": "big.iso", "BUILD": "b1"}
    if uefi:
        variables["UEFI"] = "1"
    (results / "vars.json").write_text(json.dumps(variables), encoding="utf-8")
    return results


@unittest.skipIf(MISSING, f"report dependencies unavailable: {MISSING}")
class ReadSuiteTest(unittest.TestCase):
    def test_takes_the_last_screenshot_that_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = write_suite(root, "bios", uefi=False)
            (results / "live_desktop-2.png").write_bytes(b"png")
            (results / "details-live_desktop.json").write_text(
                json.dumps(
                    {
                        "details": [
                            {"result": "ok", "screenshot": "live_desktop-1.png"},
                            {"result": "ok", "screenshot": "live_desktop-2.png"},
                            # Named by the details but never fetched: the report
                            # must fall back rather than point at nothing.
                            {"result": "ok", "screenshot": "live_desktop-3.png"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            suite = read_suite(root / "openqa-bios-audit-abc-1")

        assert suite is not None
        self.assertEqual(suite.firmware, "BIOS")
        self.assertEqual(suite.modules, {"live_desktop": "ok"})
        self.assertEqual(suite.shots["live_desktop"].name, "live_desktop-2.png")

    def test_a_failed_step_fails_the_module(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = write_suite(root, "uefi", uefi=True)
            (results / "details-installer_install.json").write_text(
                json.dumps({"details": [{"result": "ok"}, {"result": "fail"}]}),
                encoding="utf-8",
            )

            suite = read_suite(root / "openqa-uefi-audit-abc-1")

        assert suite is not None
        self.assertEqual(suite.firmware, "UEFI")
        self.assertEqual(suite.modules["installer_install"], "fail")
        self.assertFalse(suite.ok)

    def test_collects_application_outcomes_by_desktop_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = write_suite(root, "applications-0", uefi=False)
            payload = {
                "applications": [
                    {"desktop_id": "a.desktop", "status": "passed"},
                    {
                        "desktop_id": "b.desktop",
                        "status": "failed",
                        "error": "no window: child_pid=7 raw_exit_code=127",
                    },
                    {
                        "desktop_id": "c.desktop",
                        "status": "passed",
                        "validation_mode": "process-alive",
                    },
                ]
            }
            with gzip.open(results / "application-metrics.json.gz", "wt") as stream:
                json.dump(payload, stream)

            suite = read_suite(root / "openqa-applications-0-audit-abc-1")

        assert suite is not None
        self.assertEqual(len(suite.applications), 3)
        # The noisy launcher dump is cut off, keeping the part that explains it.
        self.assertEqual(suite.failures, {"b.desktop": "no window"})
        self.assertEqual(suite.weak, ["c.desktop"])


@unittest.skipIf(MISSING, f"report dependencies unavailable: {MISSING}")
class ScreenshotEncodingTest(unittest.TestCase):
    def test_keeps_whichever_encoding_is_smaller(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            flat = root / "flat.png"
            Image.new("RGB", (1024, 768), "white").save(flat)
            noisy = root / "noisy.png"
            noise = Image.effect_noise((1024, 768), 96).convert("RGB")
            noise.save(noisy)

            flat_bytes = encoded_screenshot(flat)
            noisy_bytes = encoded_screenshot(noisy)

        assert flat_bytes is not None and noisy_bytes is not None
        # A blank screen compresses far better losslessly than as JPEG.
        self.assertTrue(flat_bytes.getvalue().startswith(b"\x89PNG"))
        # Noise is the opposite case, which is why neither format is hardcoded.
        self.assertTrue(noisy_bytes.getvalue().startswith(b"\xff\xd8"))

    def test_returns_nothing_for_a_file_that_is_not_an_image(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            broken = Path(directory, "broken.png")
            broken.write_bytes(b"not an image")

            self.assertIsNone(encoded_screenshot(broken))


if __name__ == "__main__":
    unittest.main()
