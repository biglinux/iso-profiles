import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "production" / "verify-archive-screenshots.sh"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class VerifyArchiveScreenshotsTest(unittest.TestCase):
    def run_validator(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(SCRIPT)],
            env=os.environ | {"BIGLINUX_OPENQA_RESULTS_DIR": str(root)},
            capture_output=True,
            text=True,
            check=False,
        )

    def test_valid_png(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "valid.png"
            path.write_bytes(PNG_SIGNATURE + b"fixture")
            result = self.run_validator(Path(directory))
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_html_with_png_extension_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forbidden.png"
            path.write_text("<html>403 Forbidden</html>", encoding="utf-8")
            result = self.run_validator(Path(directory))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("forbidden.png", result.stderr)

    def test_empty_png_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "empty.png").touch()
            result = self.run_validator(Path(directory))
            self.assertNotEqual(result.returncode, 0)

    def test_truncated_png_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "truncated.png").write_bytes(PNG_SIGNATURE[:4])
            result = self.run_validator(Path(directory))
            self.assertNotEqual(result.returncode, 0)

    def test_directory_without_screenshots_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_validator(Path(directory))
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
