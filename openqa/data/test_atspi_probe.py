from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

REPOSITORY = Path(__file__).parents[2]
sys.path.insert(0, str(REPOSITORY / "data"))

from atspi_probe import launch_process_exited, mem_available_mib, process_tree_pss_mib


class ProbeOperationsTest(unittest.TestCase):
    """The guest probe accepts its operations by name and openqa/lib/atspi.pm
    validates the same names before spending a serial round trip on them. The
    two lists live in different files and languages, so nothing but this check
    notices when one of them gains an operation and the other does not."""

    def test_perl_and_python_agree_on_the_operation_names(self) -> None:
        probe = (REPOSITORY / "data" / "atspi_probe.py").read_text(encoding="utf-8")
        choices = re.search(r"choices=\((.*?)\),", probe, re.DOTALL)
        assert choices is not None, "probe no longer declares operation choices"
        python_operations = set(re.findall(r"\"([a-z][a-z0-9-]*)\"", choices.group(1)))

        library = (REPOSITORY / "openqa" / "lib" / "atspi.pm").read_text(
            encoding="utf-8"
        )
        allowed = re.search(r"\\A\(\?:([a-z0-9|-]+)\)\\z", library)
        assert allowed is not None, "atspi.pm no longer validates the operation"
        perl_operations = set(allowed.group(1).split("|"))

        self.assertEqual(python_operations, perl_operations)


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

    def test_detects_exited_launch_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            (proc / "123").mkdir()
            self.assertFalse(launch_process_exited(123, proc))
            self.assertTrue(launch_process_exited(456, proc))


if __name__ == "__main__":
    unittest.main()
