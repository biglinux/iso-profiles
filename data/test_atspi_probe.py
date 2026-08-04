from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from atspi_probe import (
    _is_transient_window,
    _name_matches,
    _parse_x11_window,
    launch_process_exited,
    mem_available_mib,
    process_memory,
    process_tree_pss_mib,
    wait_for_x11_window,
)


class AtspiProbeTest(unittest.TestCase):
    def test_reads_available_system_memory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            meminfo = Path(directory, "meminfo")
            meminfo.write_text(
                "MemTotal: 4096000 kB\nMemAvailable: 2048000 kB\n", encoding="utf-8"
            )
            self.assertEqual(mem_available_mib(meminfo), 2000.0)

    def test_sums_pss_for_process_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            for pid, parent, pss in (
                (100, 1, 1024),
                (101, 100, 512),
                (102, 101, 256),
                (200, 1, 4096),
            ):
                process = proc / str(pid)
                process.mkdir()
                (process / "status").write_text(
                    f"Name:\ttest\nPPid:\t{parent}\n", encoding="utf-8"
                )
                (process / "smaps_rollup").write_text(
                    f"Pss: {pss} kB\n", encoding="utf-8"
                )

            result = process_tree_pss_mib(100, proc)

        self.assertEqual(result, 1.8)

    def test_keeps_rss_when_pss_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            process = proc / "100"
            process.mkdir()
            (process / "status").write_text(
                "Name:\ttest\nPPid:\t1\nVmRSS:\t2048 kB\n", encoding="utf-8"
            )

            result = process_tree_pss_mib(100, proc)
            memory = process_memory(100, proc)

        self.assertIsNone(result)
        self.assertEqual(memory["rss_mib"], 2.0)
        self.assertIsNone(memory["pss_mib"])
        self.assertEqual(memory["process_count"], 1)

    def test_detects_exited_launch_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            (proc / "123").mkdir()
            self.assertFalse(launch_process_exited(123, proc))
            self.assertTrue(launch_process_exited(456, proc))

    def test_treats_zombie_launch_process_as_exited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            process = Path(directory, "123")
            process.mkdir()
            (process / "status").write_text("State:\tZ (zombie)\n", encoding="utf-8")

            self.assertTrue(launch_process_exited(123, Path(directory)))

    def test_matches_desktop_name_against_executable_alias(self) -> None:
        self.assertTrue(_name_matches("gimp / GIMP Startup", "GNU Image gimp-3.2"))
        self.assertTrue(
            _name_matches(
                "Big-Driver-Manager / Big-Driver-Manager", "Drivers big-driver-manager"
            )
        )

    def test_ignores_startup_splash_as_final_window(self) -> None:
        self.assertTrue(_is_transient_window({"name": "GIMP Startup"}))
        self.assertFalse(
            _is_transient_window({"name": "GNU Image Manipulation Program"})
        )

    def test_matches_expected_name_in_application_or_window(self) -> None:
        self.assertTrue(
            _name_matches(
                "soffice.bin Untitled 1 — LibreOffice Calc", "LibreOffice Calc"
            )
        )

    def test_x11_wait_open_is_available_without_atspi_window(self) -> None:
        self.assertTrue(callable(wait_for_x11_window))

    def test_parses_x11_window_pid_and_name(self) -> None:
        window = _parse_x11_window(
            "0x1400002",
            "_NET_WM_PID(CARDINAL) = 5822\n"
            '_NET_WM_NAME(UTF8_STRING) = "No file - mpv"\n',
        )
        self.assertEqual(window["pid"], 5822)
        self.assertEqual(window["name"], "No file - mpv")


if __name__ == "__main__":
    unittest.main()
