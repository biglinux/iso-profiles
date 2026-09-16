#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Resolve one newly launched process across a deliberate privilege handoff.

The caller supplies an exact executable, UID and unique environment token.  The
script only observes /proc and emits one bounded machine-readable record.  It
never signals, attaches to, or otherwise modifies a process.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time
from typing import Iterable

MARKER = "__OPENQA_PROCESS__"
ENVIRONMENT_NAME = re.compile(r"[A-Z_][A-Z0-9_]{0,63}\Z")
MAX_ENVIRONMENT = 1024 * 1024


class ProcessReadError(RuntimeError):
    """The process disappeared or could not be read coherently."""


def _status_fields(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        key, separator, value = line.partition(":")
        if separator:
            fields[key] = value.strip()
    return fields


def _start_time(path: Path) -> int:
    raw = path.read_text(encoding="utf-8", errors="replace")
    close = raw.rfind(")")
    if close < 0:
        raise ProcessReadError("invalid process stat record")
    # proc_pid_stat(5): fields after ')' begin with state (field 3); starttime
    # is field 22, therefore index 19 in this suffix.
    fields = raw[close + 2 :].split()
    try:
        value = int(fields[19])
    except (ValueError, IndexError) as error:
        raise ProcessReadError("invalid process start time") from error
    if value < 0:
        raise ProcessReadError("invalid process start time")
    return value


def _environment(path: Path) -> set[bytes]:
    raw = path.read_bytes()
    if len(raw) > MAX_ENVIRONMENT:
        raise ProcessReadError("process environment exceeds observation limit")
    return {entry for entry in raw.split(b"\0") if entry}


def process_identity(
    process: Path,
    executable: Path,
    uid: int,
    environment_name: str,
    environment_value: str,
) -> tuple[int, int] | None:
    """Return (pid, starttime) only for one exact, live process identity."""
    try:
        pid = int(process.name)
        if pid <= 1:
            return None
        before = _start_time(process / "stat")
        fields = _status_fields(process / "status")
        state = fields.get("State", "").split()
        if state and state[0] == "Z":
            return None
        uids = fields.get("Uid", "").split()
        if len(uids) < 2 or int(uids[0]) != uid or int(uids[1]) != uid:
            return None
        actual = Path(os.path.realpath(process / "exe"))
        if actual != executable:
            return None
        wanted = f"{environment_name}={environment_value}".encode("utf-8")
        if wanted not in _environment(process / "environ"):
            return None
        after = _start_time(process / "stat")
        if before != after:
            raise ProcessReadError("process identity changed while being read")
        return pid, before
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError,
            ValueError, IndexError, ProcessReadError):
        return None


def matching_processes(
    proc_root: Path,
    executable: Path,
    uid: int,
    environment_name: str,
    environment_value: str,
) -> list[tuple[int, int]]:
    matches = []
    for process in proc_root.glob("[0-9]*"):
        identity = process_identity(
            process, executable, uid, environment_name, environment_value
        )
        if identity is not None:
            matches.append(identity)
    return sorted(set(matches))


def wait_for_process(
    timeout: float,
    executable: Path,
    uid: int,
    environment_name: str,
    environment_value: str,
    proc_root: Path = Path("/proc"),
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    previous: tuple[int, int] | None = None
    while True:
        matches = matching_processes(
            proc_root, executable, uid, environment_name, environment_value
        )
        if len(matches) > 1:
            return {
                "status": "failed",
                "reason": "ambiguous",
                "matches": len(matches),
                "error": "multiple exact processes carry the launch token",
            }
        current = matches[0] if matches else None
        if current is not None and current == previous:
            return {
                "status": "passed",
                "pid": current[0],
                "start_time": current[1],
                "uid": uid,
                "executable": str(executable),
                "identity": "exact-executable+uid+environment-token",
            }
        previous = current
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {
                "status": "failed",
                "reason": "not-found",
                "matches": 0,
                "error": "no stable exact process carried the launch token before the deadline",
            }
        time.sleep(min(0.1, remaining))


def _validate_environment_value(value: str) -> str:
    if not value or len(value) > 4096 or any(ord(character) < 32 for character in value):
        raise argparse.ArgumentTypeError("environment value is invalid")
    return value


def _validate_executable(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("executable must be an absolute path")
    try:
        resolved = path.resolve(strict=True)
        mode = resolved.stat().st_mode
    except OSError as error:
        raise argparse.ArgumentTypeError("executable is unavailable") from error
    if not stat.S_ISREG(mode) or not os.access(resolved, os.X_OK):
        raise argparse.ArgumentTypeError("executable is not a regular executable file")
    return resolved


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", required=True, type=float)
    parser.add_argument("--executable", required=True, type=_validate_executable)
    parser.add_argument("--uid", required=True, type=int)
    parser.add_argument("--environment-name", required=True)
    parser.add_argument("--environment-value", required=True, type=_validate_environment_value)
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= 180:
        parser.error("timeout must be greater than 0 and at most 180 seconds")
    if args.uid < 0:
        parser.error("uid must not be negative")
    if not ENVIRONMENT_NAME.fullmatch(args.environment_name):
        parser.error("environment name is invalid")

    result = wait_for_process(
        args.timeout,
        args.executable,
        args.uid,
        args.environment_name,
        args.environment_value,
    )
    payload = json.dumps(result, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    print(MARKER + payload.hex())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
