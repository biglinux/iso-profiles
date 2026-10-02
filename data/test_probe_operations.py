# SPDX-License-Identifier: GPL-2.0-or-later
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]


class ProbeOperationsTest(unittest.TestCase):
    """The guest probe accepts its operations by name and openqa/lib/atspi.pm
    validates the same names before spending a serial round trip on them. The
    two lists live in different files and languages, so nothing but this check
    notices when one of them gains an operation and the other does not."""

    # Operations deliberately kept outside atspi->result(). A whole widget
    # tree is operator diagnostics; smoke-session is a two-phase protocol
    # owned by launch_smoke_desktop_entry(), which must interleave one host
    # keyboard shortcut between READY and the final record.
    OPERATOR_ONLY = {"dump-widgets", "smoke-session"}

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

        self.assertEqual(python_operations - self.OPERATOR_ONLY, perl_operations)
        # An operator-only name still has to exist in the probe, or the
        # exemption is hiding a rename rather than describing one.
        self.assertLessEqual(self.OPERATOR_ONLY, python_operations)


if __name__ == "__main__":
    unittest.main()
