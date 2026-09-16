# SPDX-License-Identifier: GPL-2.0-or-later
"""Wait for the delivered desktop after the private live-wizard session ends.

Observe the user manager, display socket and normal AT-SPI GetAddress path.
Never restart a service, unlink a socket, or change accessibility settings.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
import time

KEYS = ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_CURRENT_DESKTOP",
        "XDG_SESSION_TYPE", "QT_QPA_PLATFORM", "GDK_BACKEND",
        "KDE_FULL_SESSION", "KDE_SESSION_VERSION")
CLEAR = (*KEYS, "AT_SPI_BUS_ADDRESS", "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR")


class SessionPending(RuntimeError):
    """The new graphical session has not yet provided coherent endpoints."""


def command(argv: list[str], environment: dict[str, str], deadline: float) -> str:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SessionPending("session readiness deadline expired")
    try:
        result = subprocess.run(argv, env=environment, capture_output=True,
                                text=True, timeout=min(3, remaining), check=False)
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as error:
        raise SessionPending("session query could not complete") from error
    if result.returncode != 0 or len(result.stdout) > 262144:
        # Do not echo arbitrary service output or environment values into logs.
        raise SessionPending("session query failed")
    return result.stdout


def manager_environment(raw: str) -> dict[str, str]:
    try:
        record = json.loads(raw)
        if not isinstance(record, dict) or record.get("type") != "as":
            raise ValueError("expected string array")
        values = record.get("data")
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise ValueError("invalid string array")
        environment = {}
        for field in values:
            key, separator, value = field.partition("=")
            if key not in KEYS:
                continue
            if not separator or key in environment or len(value) > 4096 or any(ord(c) < 32 for c in value):
                raise ValueError("invalid session variable")
            environment[key] = value
        return environment
    except (ValueError, TypeError) as error:
        raise SessionPending("invalid user-manager environment") from error


def display_ready(environment: dict[str, str], runtime: Path, deadline: float) -> None:
    if not environment.get("XDG_CURRENT_DESKTOP"):
        raise SessionPending("desktop identity has not been published")
    wayland = environment.get("WAYLAND_DISPLAY")
    if wayland:
        endpoint = Path(wayland)
        if not endpoint.is_absolute():
            endpoint = runtime / endpoint
    else:
        match = re.fullmatch(r":([0-9]+)(?:\.[0-9]+)?", environment.get("DISPLAY", ""))
        if not match:
            raise SessionPending("desktop display has not been published")
        endpoint = Path("/tmp/.X11-unix") / ("X" + match[1])
    authority = environment.get("XAUTHORITY")
    if authority and not os.access(authority, os.R_OK):
        raise SessionPending("desktop authentication is not ready")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SessionPending("session readiness deadline expired")
    try:
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(min(0.5, remaining))
            connection.connect(str(endpoint))
    except OSError as error:
        raise SessionPending("desktop display socket is not ready") from error


def session_snapshot(deadline: float) -> tuple[dict[str, str], str]:
    runtime = Path(f"/run/user/{os.getuid()}")
    base = {key: value for key, value in os.environ.items() if key not in CLEAR}
    base.update(XDG_RUNTIME_DIR=str(runtime), DBUS_SESSION_BUS_ADDRESS=f"unix:path={runtime}/bus")
    raw = command(["busctl", "--user", "--json=short", "--timeout=2", "get-property",
                   "org.freedesktop.systemd1", "/org/freedesktop/systemd1",
                   "org.freedesktop.systemd1.Manager", "Environment"], base, deadline)
    environment = manager_environment(raw)
    # The user manager outlives both sessions. Its availability alone does not
    # mean Plasma/GNOME has finished importing its display environment.
    if command(["systemctl", "--user", "is-active", "graphical-session.target"], base, deadline).strip() != "active":
        raise SessionPending("graphical session is not active")
    display_ready(environment, runtime, deadline)
    raw = command(["busctl", "--user", "--json=short", "--timeout=2", "call",
                   "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Bus", "GetAddress"], base, deadline)
    try:
        reply = json.loads(raw)
        values = reply.get("data") if isinstance(reply, dict) else None
        if reply.get("type") != "s" or not isinstance(values, list) or len(values) != 1:
            raise ValueError("unexpected address reply")
        address = values[0]
        if (not isinstance(address, str) or not address.startswith("unix:")
                or ";" in address or len(address) > 4096 or any(ord(c) < 32 for c in address)):
            raise ValueError("not a local bus")
    except (ValueError, TypeError, AttributeError) as error:
        raise SessionPending("accessibility bus address is not ready") from error
    # GetAddress can still advertise the old wizard's deleted socket. Connect
    # and query the bus itself; never repair it and never accept its path alone.
    bus_id = command(["busctl", "--address=" + address, "--timeout=2", "call",
                      "org.freedesktop.DBus", "/org/freedesktop/DBus",
                      "org.freedesktop.DBus", "GetId"], base, deadline).strip()
    if not bus_id:
        raise SessionPending("accessibility bus did not identify itself")
    environment.update(XDG_RUNTIME_DIR=str(runtime), DBUS_SESSION_BUS_ADDRESS=base["DBUS_SESSION_BUS_ADDRESS"])
    return environment, bus_id


def wait_session(timeout: float) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    previous = None
    reason = "desktop session was not ready"
    while time.monotonic() < deadline:
        try:
            current = session_snapshot(deadline)
            if current == previous:
                return current[0]
            previous = current
            reason = "desktop session endpoints have not stabilized"
        except SessionPending as error:
            previous = None
            reason = str(error)
        time.sleep(min(0.25, max(0, deadline - time.monotonic())))
    raise SessionPending(reason)


def shell_environment(environment: dict[str, str]) -> str:
    return "; ".join(["unset " + " ".join(CLEAR)] +
        [f"export {key}={shlex.quote(environment[key])}" for key in CLEAR
         if key != "AT_SPI_BUS_ADDRESS" and key in environment])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= 180:
        parser.error("timeout must be greater than 0 and at most 180 seconds")
    try:
        print(shell_environment(wait_session(args.timeout)))
        return 0
    except SessionPending as error:
        print(f"desktop session unavailable: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
