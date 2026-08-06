#!/usr/bin/env python3
"""Tests for copy-job-results.sh."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("copy-job-results.sh")

# The fake openqa-cli stands in for the archive client: it writes the layout the
# real one writes, so these tests pin what the script requires of the result
# rather than how it is fetched.
FAKE_DOCKER = """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
assert args[0] == "exec", args
assert "archive" in args, args
destination = Path(os.environ["FAKE_ARCHIVE_ROOT"], args[-1].rsplit("/", 1)[-1])
results = destination / "testresults"
results.mkdir(parents=True, exist_ok=True)
(results / "vars.json").write_text("{}\\n", encoding="utf-8")
(results / "details-applications.json").write_text(
    json.dumps({"details": [{"screenshot": "applications-1.png"}]}) + "\\n",
    encoding="utf-8",
)
# openQA answers 403 for step numbers that never had a screenshot, and the
# archive client stores the error page under the .png name it asked for.
ERROR_PAGE = b"<html><head><title>403 Forbidden</title></head></html>"
(results / "applications-2.png").write_bytes(ERROR_PAGE)
if os.environ.get("FAKE_WRITE_SCREENSHOT") == "1":
    (results / "applications-1.png").write_bytes(b"\\x89PNG\\r\\n\\x1a\\ncontent")
elif os.environ.get("FAKE_SCREENSHOT_IS_ERROR_PAGE") == "1":
    (results / "applications-1.png").write_bytes(ERROR_PAGE)
"""


class CopyJobResultsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.archive_root = self.root / "results"
        self.archive_root.mkdir()
        self.fake_docker = self.root / "docker"
        self.fake_docker.write_text(FAKE_DOCKER, encoding="utf-8")
        self.fake_docker.chmod(0o755)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def run_script(
        self, *arguments: str, screenshot: bool = True, error_page: bool = False
    ):
        environment = os.environ.copy()
        environment["DOCKER_BIN"] = str(self.fake_docker)
        environment["FAKE_ARCHIVE_ROOT"] = str(self.archive_root)
        environment["FAKE_WRITE_SCREENSHOT"] = "1" if screenshot else "0"
        environment["FAKE_SCREENSHOT_IS_ERROR_PAGE"] = "1" if error_page else "0"
        return subprocess.run(
            [str(SCRIPT), *arguments],
            capture_output=True,
            check=False,
            text=True,
            env=environment,
        )

    def test_archives_the_job_with_its_screenshots(self) -> None:
        result = self.run_script("openqa-test", "1", str(self.archive_root / "1"))

        self.assertEqual(result.returncode, 0, result.stderr)
        screenshot = self.archive_root / "1" / "testresults" / "applications-1.png"
        self.assertEqual(screenshot.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertIn("1 screenshots", result.stdout)
        # The unreferenced error page is dropped rather than shipped as evidence.
        self.assertFalse(screenshot.with_name("applications-2.png").exists())
        self.assertIn("1 error pages discarded", result.stdout)

    def test_fails_when_a_named_screenshot_arrived_as_an_error_page(self) -> None:
        result = self.run_script(
            "openqa-test",
            "1",
            str(self.archive_root / "1"),
            screenshot=False,
            error_page=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Screenshot named by the details is missing", result.stderr)

    def test_fails_when_a_named_screenshot_was_not_fetched(self) -> None:
        result = self.run_script(
            "openqa-test", "1", str(self.archive_root / "1"), screenshot=False
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Screenshot named by the details is missing", result.stderr)

    def test_rejects_invalid_job_id(self) -> None:
        result = self.run_script("openqa-test", "0", str(self.archive_root / "0"))

        self.assertEqual(result.returncode, 2)
        self.assertIn("Invalid openQA job ID", result.stderr)

    def test_rejects_a_destination_outside_the_mount(self) -> None:
        result = self.run_script("openqa-test", "1", str(self.archive_root / "other"))

        self.assertEqual(result.returncode, 2)
        self.assertIn("must end in the job ID", result.stderr)


if __name__ == "__main__":
    unittest.main()
