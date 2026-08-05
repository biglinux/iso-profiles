#!/usr/bin/env python3
"""Tests for copy-job-results.sh."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("copy-job-results.sh")


class CopyJobResultsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.container_root = self.root / "container"
        self.result = (
            self.container_root
            / "var/lib/openqa/testresults/00001/00000001-biglinux-test"
        )
        self.result.mkdir(parents=True)
        (self.result / "vars.json").write_text("{}\n", encoding="utf-8")
        image_basename = "0123456789abcdef0123456789.png"
        (self.result / "details-applications.json").write_text(
            json.dumps(
                {
                    "details": [
                        {
                            "screenshot": "applications-1.png",
                            "md5_dirname": "abc/def",
                            "md5_basename": image_basename,
                        },
                        {
                            "screenshot": "applications-2.png",
                            "frametime": ["11.42", "11.46"],
                        },
                    ]
                }
            )
            + "\n",
            encoding="utf-8",
        )
        image = self.container_root / "var/lib/openqa/images/abc/def" / image_basename
        image.parent.mkdir(parents=True)
        image.write_bytes(b"\x89PNG\r\n\x1a\nvalid-test-payload")
        self.fake_docker = self.root / "docker"
        self.fake_docker.write_text(
            """#!/usr/bin/env python3
import os
import shutil
import sys
from pathlib import Path

root = Path(os.environ[\"FAKE_CONTAINER_ROOT\"])
args = sys.argv[1:]
if args[0] == \"exec\":
    pattern = args[args.index("-name") + 1]
    candidates = sorted(root.glob(\"var/lib/openqa/testresults/*/\" + pattern))
    for candidate in candidates:
        print(\"/\" + str(candidate.relative_to(root)))
    raise SystemExit(0)
if args[0] == \"cp\":
    source = args[1].split(\":\", 1)[1]
    if source.endswith(\"/.\"):
        source = source[:-2]
    source_path = root / source.lstrip(\"/\")
    destination = Path(args[2])
    if source_path.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
    else:
        destination.mkdir(parents=True, exist_ok=True)
        for child in source_path.iterdir():
            target = destination / child.name
            if child.is_dir():
                shutil.copytree(child, target)
            else:
                shutil.copy2(child, target)
    raise SystemExit(0)
raise SystemExit(2)
""",
            encoding="utf-8",
        )
        self.fake_docker.chmod(0o755)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def run_script(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["DOCKER_BIN"] = str(self.fake_docker)
        environment["FAKE_CONTAINER_ROOT"] = str(self.container_root)
        return subprocess.run(
            [str(SCRIPT), *arguments],
            capture_output=True,
            check=False,
            text=True,
            env=environment,
        )

    def test_copies_complete_result_tree(self) -> None:
        destination = self.root / "output"
        result = self.run_script("openqa-test", "1", str(destination))
        self.assertEqual(result.returncode, 0, result.stderr)
        testresults = destination / "testresults"
        self.assertTrue((testresults / "vars.json").is_file())
        self.assertTrue((testresults / "details-applications.json").is_file())
        screenshot = testresults / "applications-1.png"
        self.assertTrue(screenshot.is_file())
        self.assertEqual(screenshot.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


    def test_rejects_incomplete_screenshot_metadata(self) -> None:
        (self.result / "details-applications.json").write_text(
            json.dumps({"details": [{"screenshot": "applications-1.png"}]}) + "\n",
            encoding="utf-8",
        )
        result = self.run_script("openqa-test", "1", str(self.root / "output"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("Could not parse screenshot metadata", result.stderr)

    def test_fails_when_content_addressed_image_is_missing(self) -> None:
        image = next((self.container_root / "var/lib/openqa/images").rglob("*.png"))
        image.unlink()
        result = self.run_script("openqa-test", "1", str(self.root / "output"))
        self.assertNotEqual(result.returncode, 0)

    def test_rejects_invalid_job_id(self) -> None:
        result = self.run_script("openqa-test", "0", str(self.root / "output"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("Invalid openQA job ID", result.stderr)

    def test_fails_when_result_directory_is_missing(self) -> None:
        result = self.run_script("openqa-test", "2", str(self.root / "output"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("Expected one result directory", result.stderr)

    def test_rejects_multiple_result_directories(self) -> None:
        duplicate = self.result.parent / "00000001-biglinux-duplicate"
        duplicate.mkdir()
        (duplicate / "vars.json").write_text("{}\n", encoding="utf-8")
        (duplicate / "details-applications.json").write_text(
            '{"details": []}\n', encoding="utf-8"
        )

        result = self.run_script("openqa-test", "1", str(self.root / "output"))

        self.assertEqual(result.returncode, 1)
        self.assertIn("found 2", result.stderr)


if __name__ == "__main__":
    unittest.main()
