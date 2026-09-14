#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Enforce the nonvisual test policy without requiring a guest or GI bindings."""
from pathlib import Path
import re
import sys

FORBIDDEN = re.compile(
    r"\b(?:assert_screen|check_screen|assert_and_click|assert_and_dclick|"
    r"wait_still_screen|wait_screen_change|mouse_set|mouse_click|mouse_dclick)\b"
)


def violations(root: Path) -> list[str]:
    errors = []
    for directory in ("openqa/tests", "openqa/lib"):
        for path in sorted((root / directory).rglob("*.pm")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                if FORBIDDEN.search(line):
                    errors.append(f"{path.relative_to(root)}:{number}: visual/pointer test API")
                if re.match(r"\s*atspi->wait_widget(?:_until)?\(", line):
                    errors.append(f"{path.relative_to(root)}:{number}: unchecked required wait")
    for path in (root / "openqa/needles").glob("*.json"):
        errors.append(f"{path.relative_to(root)}: image reference is not a nonvisual contract")
    return errors


if __name__ == "__main__":
    problems = violations(Path(__file__).resolve().parents[2])
    print("\n".join(problems) if problems else "nonvisual source policy: passed")
    sys.exit(bool(problems))
