# SPDX-License-Identifier: GPL-2.0-or-later
"""Join the live wizard's existing session before making any AT-SPI request.

The BigLinux wizard runs under dbus-run-session, not the systemd user bus.
This helper observes that process; it never starts or repairs a D-Bus service.
"""
from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import shlex
import sys
import time

WIZARD = b"/usr/share/biglinux/livecd/main.py"
KEYS = ("DBUS_SESSION_BUS_ADDRESS", "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY",
        "XDG_RUNTIME_DIR", "XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE")
LIMIT = 65536


def read_limited(path: Path) -> bytes:
    with path.open("rb") as stream:
        value = stream.read(LIMIT + 1)
    if len(value) > LIMIT:
        raise ValueError("process metadata exceeds the allowed size")
    return value


def wizard_environment(proc: Path = Path("/proc"), uid: int | None = None) -> dict[str, str] | None:
    uid = os.getuid() if uid is None else uid
    matches = []
    for process in proc.glob("[0-9]*"):
        try:
            if process.stat().st_uid != uid:
                continue
            if not read_limited(process / "comm").startswith(b"python"):
                continue
            identity = read_limited(process / "stat")
            if WIZARD not in read_limited(process / "cmdline").split(b"\0"):
                continue
            raw = read_limited(process / "environ")
            # PID reuse/exit is not evidence of this launch's session.
            if identity.rsplit(b")", 1)[-1].split()[19] != read_limited(process / "stat").rsplit(b")", 1)[-1].split()[19]:
                continue
        except (OSError, ValueError, IndexError):
            continue
        fields = dict(field.split(b"=", 1) for field in raw.split(b"\0") if b"=" in field)
        environment = {key: fields[key.encode()].decode("utf-8", "strict") for key in KEYS if key.encode() in fields}
        if environment.get("XDG_RUNTIME_DIR") != f"/run/user/{uid}":
            raise ValueError("wizard runtime directory does not belong to the current user")
        if not environment.get("DBUS_SESSION_BUS_ADDRESS", "").startswith("unix:"):
            raise ValueError("wizard did not expose a local session bus")
        if not (environment.get("WAYLAND_DISPLAY") or environment.get("DISPLAY")):
            continue  # The graphical session has not finished setting up yet.
        if any(any(ord(character) < 32 for character in value) for value in environment.values()):
            raise ValueError("invalid control character in session metadata")
        matches.append(environment)
    if len(matches) > 1:
        raise ValueError("more than one live wizard is running for the user")
    return matches[0] if matches else None


def shell_environment(environment: dict[str, str]) -> str:
    # Only whitelisted keys are emitted and every value is shell-quoted. Remove
    # a stale accessibility address so libatspi asks the correct session bus.
    lines = ["unset AT_SPI_BUS_ADDRESS " + " ".join(KEYS)]
    lines += [f"export {key}={shlex.quote(environment[key])}" for key in KEYS if key in environment]
    return "; ".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or not 0 <= args.timeout <= 180:
        parser.error("timeout must be between 0 and 180 seconds")
    deadline = time.monotonic() + args.timeout
    try:
        while True:
            environment = wizard_environment()
            if environment is not None:
                print(shell_environment(environment))
                return 0
            if time.monotonic() >= deadline:
                print("live wizard session was not available before the deadline", file=sys.stderr)
                return 1
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))
    except (ValueError, UnicodeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
