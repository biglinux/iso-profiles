#!/usr/bin/env python3
"""Canonical form of the application policy.

The scheduler hashes this form, the tests verify the checkout against that
hash, and the aggregator recomputes it. One implementation, so the three
cannot disagree.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_policy(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: aggregate_policy.py <application-policy.yaml>", file=sys.stderr)
        return 2
    print(canonical_json(read_policy(Path(argv[1]))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
