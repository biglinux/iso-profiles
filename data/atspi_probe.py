#!/usr/bin/env python3
"""Observe accessible windows and process memory for the openQA application tests."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

RESULT_MARKER = "__OPENQA_ATSPI__"


class ProbeError(RuntimeError):
    """The accessibility service could not provide a coherent snapshot."""


def mem_available_mib(meminfo: Path = Path("/proc/meminfo")) -> float | None:
    try:
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return round(int(line.split()[1]) / 1024, 1)
    except (OSError, ValueError, IndexError):
        pass
    return None


def process_tree_pss_mib(
    root_pid: int, proc_root: Path = Path("/proc")
) -> float | None:
    if root_pid <= 0:
        return None
    parents: dict[int, int] = {}
    for status in proc_root.glob("[0-9]*/status"):
        try:
            fields = {
                line.split(":", 1)[0]: line.split(":", 1)[1].strip()
                for line in status.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
                if ":" in line
            }
            parents[int(status.parent.name)] = int(fields["PPid"].split()[0])
        except (OSError, ValueError, KeyError, IndexError):
            continue

    descendants = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, parent in parents.items():
            if parent in descendants and pid not in descendants:
                descendants.add(pid)
                changed = True

    pss_kib = 0
    found = False
    for pid in descendants:
        try:
            for line in (
                (proc_root / str(pid) / "smaps_rollup")
                .read_text(encoding="utf-8", errors="replace")
                .splitlines()
            ):
                if line.startswith("Pss:"):
                    pss_kib += int(line.split()[1])
                    found = True
                    break
        except (OSError, ValueError, IndexError):
            continue
    return round(pss_kib / 1024, 1) if found else None


def accessible_snapshot() -> dict[str, Any]:
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi, GLib

    def application_windows(app: Any) -> list[dict[str, Any]]:
        try:
            app_name = app.get_name() or ""
            pid = app.get_process_id()
            window_count = app.get_child_count()
        except (GLib.Error, RuntimeError):
            return []

        result: list[dict[str, Any]] = []
        for window_index in range(window_count):
            try:
                window = app.get_child_at_index(window_index)
                name = window.get_name() or ""
                role = window.get_role_name() or ""
                children = window.get_child_count()
            except (GLib.Error, RuntimeError):
                continue
            key = f"{pid}\0{app_name}\0{role}\0{name}"
            result.append(
                {
                    "key": key,
                    "application": app_name,
                    "name": name,
                    "role": role,
                    "children": children,
                    "pid": pid,
                }
            )
        return result

    try:
        desktop = Atspi.get_desktop(0)
        application_count = desktop.get_child_count()
    except (GLib.Error, RuntimeError) as error:
        raise ProbeError(f"AT-SPI desktop is unavailable: {error}") from error
    windows: list[dict[str, Any]] = []
    for app_index in range(application_count):
        try:
            windows.extend(application_windows(desktop.get_child_at_index(app_index)))
        except (GLib.Error, RuntimeError):
            pass
    return {"windows": windows, "mem_available_mib": mem_available_mib()}


def save_baseline(state_path: Path) -> dict[str, Any]:
    snapshot = accessible_snapshot()
    state_path.write_text(
        json.dumps({"window_keys": [window["key"] for window in snapshot["windows"]]}),
        encoding="utf-8",
    )
    return snapshot


def baseline_keys(state_path: Path) -> set[str]:
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    return set(payload.get("window_keys", []))


def wait_for_window_change(
    state_path: Path, timeout: float, opening: bool
) -> dict[str, Any]:
    baseline = baseline_keys(state_path)
    deadline = time.monotonic() + timeout
    last_snapshot: dict[str, Any] = {}
    while time.monotonic() <= deadline:
        last_snapshot = accessible_snapshot()
        extra = [
            window
            for window in last_snapshot["windows"]
            if window["key"] not in baseline
        ]
        # A named top-level with children is a useful accessibility surface,
        # unlike a splash screen or an empty custom-drawn placeholder.
        usable = [
            window for window in extra if window["name"] and window["children"] > 0
        ]
        if (opening and usable) or (not opening and not extra):
            result: dict[str, Any] = {
                "status": "passed",
                "accessible_window": bool(usable) if opening else True,
                "mem_available_mib": last_snapshot["mem_available_mib"],
            }
            if opening:
                window = usable[0]
                result.update(
                    {
                        "application": window["application"],
                        "window": window["name"],
                        "role": window["role"],
                        "accessible_children": window["children"],
                        "pid": window["pid"],
                        "settled_pss_mib": process_tree_pss_mib(window["pid"]),
                    }
                )
            return result
        time.sleep(0.25)
    return {
        "status": "failed",
        "accessible_window": False if opening else None,
        "mem_available_mib": last_snapshot.get("mem_available_mib"),
        "error": "accessible application window did not open"
        if opening
        else "application window did not close",
    }


def emit(result: dict[str, Any]) -> None:
    encoded = (
        json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        .encode("utf-8")
        .hex()
    )
    print(f"{RESULT_MARKER}{encoded}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("baseline", "wait-open", "wait-close"))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()

    os.environ.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    os.environ.setdefault(
        "DBUS_SESSION_BUS_ADDRESS", f"unix:path={os.environ['XDG_RUNTIME_DIR']}/bus"
    )
    try:
        if args.operation == "baseline":
            result = save_baseline(args.state)
        else:
            result = wait_for_window_change(
                args.state, args.timeout, args.operation == "wait-open"
            )
    except (ProbeError, OSError, ValueError, json.JSONDecodeError) as error:
        emit({"status": "failed", "error": str(error)})
        return 1
    emit(result)
    return 0 if result.get("status") != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
