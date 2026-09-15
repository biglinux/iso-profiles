# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only, bounded diagnostics when the GUI/AT-SPI session cannot be reached.

Never dump the full environment or process arguments: both can contain secrets.
Collect observations only; do not start, restart or reconfigure desktop services.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time

ENVIRONMENT_KEYS = frozenset({"DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY",
    "XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE", "XDG_RUNTIME_DIR",
    "DBUS_SESSION_BUS_ADDRESS", "AT_SPI_BUS_ADDRESS", "GTK_A11Y", "NO_AT_BRIDGE"})
DESKTOP_PROCESSES = frozenset({"sddm", "sddm-greeter", "sddm-greeter-qt6", "Xorg",
    "Xwayland", "kwin_wayland", "kwin_x11", "plasmashell", "gnome-shell",
    "at-spi-bus-laun", "at-spi2-registr"})
PROPERTIES = ["-p", "ActiveState", "-p", "SubState", "-p", "Result", "-p", "ExecMainStatus"]
MAX_OUTPUT = 24000


def filtered_environment(raw: bytes) -> dict[str, str]:
    return {key: value[:2048] for field in raw.decode("utf-8", "replace").split("\0")
            for key, separator, value in [field.partition("=")]
            if separator and key in ENVIRONMENT_KEYS}


def command(argv: list[str], deadline: float) -> dict:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return {"command": argv, "error": "diagnostic deadline reached"}
    try:
        # Child output is bounded at the source by ps/--lines and property lists.
        result = subprocess.run(argv, capture_output=True, timeout=min(5, remaining), check=False)
        output = result.stdout + result.stderr
        return {"command": argv, "exit_code": result.returncode,
                "output": output[:MAX_OUTPUT].decode("utf-8", "replace"),
                "truncated": len(output) > MAX_OUTPUT}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"command": argv, "error": type(error).__name__}


def process_sessions(proc: Path = Path("/proc")) -> list[dict]:
    sessions = []
    for path in proc.glob("[0-9]*"):
        try:
            name = (path / "comm").read_text().strip()
            is_wizard = (name.startswith("python") and
                b"/usr/share/biglinux/livecd/main.py" in (path / "cmdline").read_bytes().split(b"\0"))
            if name not in DESKTOP_PROCESSES and not is_wizard:
                continue
            record = {"pid": int(path.name), "process": "live-wizard" if is_wizard else name}
            try:
                record["environment"] = filtered_environment((path / "environ").read_bytes())
            except OSError:
                record["environment_unavailable"] = True
            sessions.append(record)
            if len(sessions) >= 64:
                break
        except (OSError, ValueError):
            continue
    return sessions


def wizard_tree(deadline: float) -> dict:
    """Record only topology/roles in the wizard, never user text or text values."""
    try:
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
        Atspi.set_timeout(250, 2000)
        desktop = Atspi.get_desktop(0)
        wizard_pids = {item["pid"] for item in process_sessions() if item["process"] == "live-wizard"}
        from collections import deque
        queue = deque()
        for index in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(index)
            if app is not None and app.get_process_id() in wizard_pids:
                queue.append((app, None))
        seen = {}
        references = []
        records = []
        while queue and len(records) < 300 and time.monotonic() < deadline:
            node, parent = queue.popleft()
            identity = str(getattr(node, 'path', '')) or str(id(node))
            if identity in seen:
                records.append({"identity": identity, "parent": parent, "first_parent": seen[identity], "repeated": True})
                continue
            seen[identity] = parent
            references.append(node)
            states = node.get_state_set()
            record = {"identity": identity, "parent": parent, "role": node.get_role_name(),
                      "showing": bool(states.contains(Atspi.StateType.SHOWING)),
                      "defunct": bool(states.contains(Atspi.StateType.DEFUNCT)),
                      "child_count": node.get_child_count()}
            records.append(record)
            for index in range(max(0, min(record["child_count"], 300 - len(queue) - len(records)))):
                if time.monotonic() >= deadline:
                    break
                child = node.get_child_at_index(index)
                if child is not None:
                    queue.append((child, identity))
        return {"records": records, "diagnostic_only": True, "bounded": True}
    except Exception as error:
        # Diagnostics must not replace the original test failure.
        return {"error": type(error).__name__, "diagnostic_only": True}


def collect(timeout: float = 45) -> dict:
    deadline = time.monotonic() + timeout
    commands = [
        ["systemctl", "show", "display-manager.service", *PROPERTIES, "-p", "FragmentPath"],
        ["systemctl", "--user", "show", "graphical-session.target", "at-spi-dbus-bus.service", *PROPERTIES],
        ["loginctl", "list-sessions", "--no-legend", "--no-pager"],
        ["ps", "-eo", "pid,ppid,uid,stat,comm"],
        ["journalctl", "--user", "--boot", "--no-pager", "--lines=80", "--output=short-monotonic"],
        ["journalctl", "--boot", "--no-pager", "--lines=80", "-u", "display-manager.service"],
        ["lspci", "-nnk"],
    ]
    result = {"schema_version": 1, "kind": "read-only-session-diagnostics",
              "process_sessions": process_sessions(), "observations": []}
    environment = command(["systemctl", "--user", "show-environment"], deadline)
    result["manager_environment"] = filtered_environment(
        environment.get("output", "").replace("\n", "\0").encode())
    result["manager_environment_exit_code"] = environment.get("exit_code")
    for argv in commands:
        result["observations"].append(command(argv, deadline))
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    result["session_bus_socket_exists"] = (runtime / "bus").is_socket()
    result["accessibility_sockets"] = [str(path) for path in sorted((runtime / "at-spi").glob("*"))
                                       if path.is_socket()]
    result["wizard_tree"] = wizard_tree(min(deadline, time.monotonic() + 8))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(collect(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
