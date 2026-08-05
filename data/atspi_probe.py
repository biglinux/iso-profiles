"""Query AT-SPI windows, close them, and sample their memory."""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

RESULT_MARKER = "__OPENQA_ATSPI__"
INVENTORY_CHUNK_SIZE = 600


class ProbeError(RuntimeError):
    """AT-SPI could not provide a coherent result."""


def mem_available_mib(meminfo: Path = Path("/proc/meminfo")) -> float | None:
    try:
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return round(int(line.split()[1]) / 1024, 1)
    except (OSError, ValueError, IndexError):
        return None
    return None


def _process_tree(root_pid: int, proc_root: Path = Path("/proc")) -> set[int]:
    if root_pid <= 0:
        return set()
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
    return descendants


def process_memory(root_pid: int, proc_root: Path = Path("/proc")) -> dict[str, Any]:
    pids = _process_tree(root_pid, proc_root)
    rss_kib = 0
    pss_kib = 0
    rss_found = False
    pss_found = False
    live_pids = 0
    for pid in pids:
        try:
            status = (proc_root / str(pid) / "status").read_text(
                encoding="utf-8", errors="replace"
            )
        except (OSError, ValueError, IndexError):
            continue
        for line in status.splitlines():
            if line.startswith("VmRSS:"):
                try:
                    rss_kib += int(line.split()[1])
                    rss_found = True
                except (ValueError, IndexError):
                    break
                break
        live_pids += 1
        try:
            rollup = (proc_root / str(pid) / "smaps_rollup").read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            continue
        for line in rollup.splitlines():
            if line.startswith("Pss:"):
                try:
                    pss_kib += int(line.split()[1])
                    pss_found = True
                except (ValueError, IndexError):
                    break
                break
    return {
        "rss_mib": round(rss_kib / 1024, 1) if rss_found else None,
        "pss_mib": round(pss_kib / 1024, 1) if pss_found else None,
        "process_count": live_pids,
    }


def process_tree_pss_mib(
    root_pid: int, proc_root: Path = Path("/proc")
) -> float | None:
    return process_memory(root_pid, proc_root).get("pss_mib")


def _merge_peak(peak: dict[str, Any], current: dict[str, Any]) -> None:
    for field in ("rss_mib", "pss_mib"):
        value = current.get(field)
        if isinstance(value, (int, float)) and value > (peak.get(field) or 0):
            peak[field] = value
    count = current.get("process_count")
    if isinstance(count, int) and count > (peak.get("process_count") or 0):
        peak["process_count"] = count


def sample_process_memory(root_pid: int, duration: float = 2.0) -> dict[str, Any]:
    peak: dict[str, Any] = {"rss_mib": None, "pss_mib": None, "process_count": 0}
    deadline = time.monotonic() + max(0.0, duration)
    while True:
        current = process_memory(root_pid)
        _merge_peak(peak, current)
        if time.monotonic() >= deadline or current["process_count"] == 0:
            break
        time.sleep(0.25)
    return peak


def _atspi_import() -> tuple[Any, Any]:
    try:
        import gi

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi, GLib
    except (ImportError, ValueError) as error:
        raise ProbeError(f"AT-SPI Python bindings are unavailable: {error}") from error
    return Atspi, GLib


def _window_records() -> Iterable[tuple[Any, dict[str, Any]]]:
    Atspi, GLib = _atspi_import()
    try:
        desktop = Atspi.get_desktop(0)
        if desktop is None:
            raise ProbeError("AT-SPI desktop is unavailable: null desktop root")
        application_count = desktop.get_child_count()
    except ProbeError:
        raise
    except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError) as error:
        raise ProbeError(f"AT-SPI desktop is unavailable: {error}") from error

    for app_index in range(application_count):
        try:
            app = desktop.get_child_at_index(app_index)
            if app is None:
                continue
            app_name = app.get_name() or ""
            app_pid = app.get_process_id()
            window_count = app.get_child_count()
        except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError):
            continue
        for window_index in range(window_count):
            try:
                window = app.get_child_at_index(window_index)
                if window is None:
                    continue
                name = window.get_name() or ""
                role = window.get_role_name() or ""
                children = window.get_child_count()
            except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError):
                continue
            yield (
                window,
                {
                    "key": f"{app_pid}\0{app_name}\0{role}\0{name}",
                    "application": app_name,
                    "name": name,
                    "role": role,
                    "children": children,
                    "pid": app_pid,
                },
            )


def accessible_snapshot() -> dict[str, Any]:
    windows = [record for _window, record in _window_records()]
    return {"windows": windows, "mem_available_mib": mem_available_mib()}


def save_baseline(state_path: Path) -> dict[str, Any]:
    snapshot = accessible_snapshot()
    x11_windows = _x11_window_records()
    state_path.write_text(
        json.dumps(
            {
                "window_keys": [window["key"] for window in snapshot["windows"]],
                "x11_window_ids": [window["id"] for window in x11_windows],
            }
        ),
        encoding="utf-8",
    )
    return snapshot


def baseline_keys(state_path: Path) -> set[str]:
    return set(
        json.loads(state_path.read_text(encoding="utf-8")).get("window_keys", [])
    )


def _name_matches(actual: str, expected: str | None) -> bool:
    if not expected:
        return True
    ignored_words = {"and", "for", "the", "this", "with"}
    actual_words = set(re.findall(r"[a-z0-9]+", actual.casefold()))
    expected_words = [
        word
        for word in re.findall(r"[a-z0-9]+", expected.casefold())
        if len(word) >= 3 and word not in ignored_words
    ]
    return bool(expected_words) and any(
        expected_word in actual_word or actual_word in expected_word
        for expected_word in expected_words
        for actual_word in actual_words
    )


_X11_WINDOW_ID_RE = re.compile(r"0x[0-9a-fA-F]+")
_X11_PID_RE = re.compile(r"_NET_WM_PID\([^)]*\)\s*=\s*(\d+)")
_X11_NAME_RE = re.compile(
    r"(?:_NET_WM_NAME|WM_NAME)\([^)]*\)\s*=\s*\"((?:\\.|[^\"])*)\""
)


def _xprop(*arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["xprop", *arguments],
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout if completed.returncode == 0 else ""


def _parse_x11_window(window_id: str, properties: str) -> dict[str, Any]:
    pid_match = _X11_PID_RE.search(properties)
    name_match = _X11_NAME_RE.search(properties)
    return {
        "id": window_id,
        "pid": int(pid_match.group(1)) if pid_match else None,
        "name": name_match.group(1).replace('\\"', '"').replace("\\\\", "\\")
        if name_match
        else "",
    }


def _x11_window_records() -> list[dict[str, Any]]:
    client_list = _xprop("-root", "_NET_CLIENT_LIST_STACKING")
    records: list[dict[str, Any]] = []
    for window_id in _X11_WINDOW_ID_RE.findall(client_list):
        properties = _xprop("-id", window_id, "_NET_WM_PID", "_NET_WM_NAME", "WM_NAME")
        records.append(_parse_x11_window(window_id, properties))
    return records


def _close_x11_window(window_id: str) -> bool:
    try:
        completed = subprocess.run(
            ["wmctrl", "-i", "-c", window_id],
            capture_output=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _force_close_x11_window(window_id: str) -> bool:
    for command in (("xkill", "-id", window_id), ("xdotool", "windowkill", window_id)):
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                check=False,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if completed.returncode == 0:
            return True
    return False


def wait_for_x11_window(
    timeout: float,
    expected_pid: int | None = None,
    expected_name: str | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_windows: list[dict[str, Any]] = []
    while time.monotonic() <= deadline:
        last_windows = _x11_window_records()
        process_pids = _process_tree(expected_pid) if expected_pid else set()
        matches = [
            window
            for window in last_windows
            if window["pid"]
            and (expected_pid is None or window["pid"] in process_pids)
            and _name_matches(window["name"], expected_name)
        ]
        if matches:
            window = matches[0]
            pid = window["pid"]
            return {
                "status": "passed",
                "accessible_window": False,
                "window": window["name"],
                "pid": pid,
                "accessible_children": 0,
                "mem_available_mib": mem_available_mib(),
                "memory": sample_process_memory(expected_pid or pid),
                "validation_mode": "x11-window",
            }
        if expected_pid and launch_process_exited(expected_pid):
            break
        time.sleep(0.25)
    descriptions = (
        "; ".join(
            f"{window['name'] or '?'} pid={window['pid']}" for window in last_windows
        )
        or "none"
    )
    return {
        "status": "failed",
        "accessible_window": False,
        "mem_available_mib": mem_available_mib(),
        "error": f"X11 application window did not open; observed={descriptions}",
    }


def launch_process_exited(
    expected_pid: int | None, proc_root: Path = Path("/proc")
) -> bool:
    """Return whether a PID-scoped launch already ended before exposing a window."""
    if expected_pid is None:
        return False
    process_dir = proc_root / str(expected_pid)
    if not process_dir.exists():
        return True
    try:
        status = (process_dir / "status").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return not process_dir.exists()
    return bool(re.search(r"^State:\s+Z(?:\s|$)", status, re.MULTILINE))


def _is_transient_window(window: dict[str, Any]) -> bool:
    name = window.get("name", "").casefold()
    return any(
        token in name for token in ("startup", "splash", "loading", "initializing")
    )


def _describe_windows(windows: list[dict[str, Any]]) -> str:
    descriptions = [
        f"{window['application'] or '?'} / {window['name'] or '?'} "
        f"pid={window['pid']} children={window['children']}"
        for window in windows[-12:]
    ]
    return "; ".join(descriptions) or "none"


def wait_for_window_change(
    state_path: Path,
    timeout: float,
    opening: bool,
    expected_pid: int | None = None,
    expected_name: str | None = None,
) -> dict[str, Any]:
    baseline = baseline_keys(state_path)
    deadline = time.monotonic() + timeout
    last_snapshot: dict[str, Any] = {}
    while time.monotonic() <= deadline:
        # An application legitimately reaches its window through a wrapper or a
        # forked helper, so identity is the launched process tree rather than a
        # single PID. Recompute it every poll: children appear over time.
        allowed_pids = _process_tree(expected_pid) if expected_pid is not None else None
        last_snapshot = accessible_snapshot()
        extra = [
            window
            for window in last_snapshot["windows"]
            if window["key"] not in baseline
            and (allowed_pids is None or window["pid"] in allowed_pids)
            and _name_matches(
                " ".join(
                    value for value in (window["application"], window["name"]) if value
                ),
                expected_name,
            )
        ]
        if opening and not extra and launch_process_exited(expected_pid):
            return {
                "status": "failed",
                "accessible_window": False,
                "mem_available_mib": last_snapshot.get("mem_available_mib"),
                "error": "launch process exited before exposing an accessible window; "
                f"observed={_describe_windows(last_snapshot['windows'])}",
            }
        # A window that belongs to the launched process is enough evidence that
        # the application started. Requiring a title or a populated
        # accessibility subtree only fails applications whose next release
        # renames a window or changes toolkit, which is not a defect.
        usable = [window for window in extra if not _is_transient_window(window)]
        if (
            not opening
            and expected_pid is not None
            and launch_process_exited(expected_pid)
        ):
            return {
                "status": "passed",
                "accessible_window": None,
                "process_gone": True,
                "mem_available_mib": last_snapshot.get("mem_available_mib"),
            }
        if (opening and usable) or (not opening and not extra):
            result: dict[str, Any] = {
                "status": "passed",
                "accessible_window": bool(usable) if opening else True,
                "mem_available_mib": last_snapshot.get("mem_available_mib"),
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
                        "memory": sample_process_memory(window["pid"]),
                    }
                )
            return result
        time.sleep(0.25)
    return {
        "status": "failed",
        "accessible_window": False if opening else None,
        "mem_available_mib": last_snapshot.get("mem_available_mib"),
        "error": "accessible application window did not open"
        + f"; observed={_describe_windows(last_snapshot.get('windows', []))}"
        if opening
        else "application window did not close",
    }


def _walk(accessible: Any, limit: int = 600) -> Iterable[Any]:
    _atspi, GLib = _atspi_import()
    queue = [accessible] if accessible is not None else []
    visited = 0
    while queue and visited < limit:
        current = queue.pop(0)
        if current is None:
            continue
        visited += 1
        yield current
        try:
            children = (
                current.get_child_at_index(index)
                for index in range(current.get_child_count())
            )
            queue.extend(child for child in children if child is not None)
        except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError):
            continue


def _window_for_pid(pid: int) -> Any | None:
    for window, record in _window_records():
        if record["pid"] == pid and record["name"]:
            return window
    return None


_INTERACTIVE_ACTIONS = (
    "click",
    "press",
    "activate",
    "toggle",
    "show-menu",
    "menu.popup",
    "open",
    "select",
    "expand",
    "collapse",
)
_INTERACTIVE_ROLES = (
    "button",
    "toggle",
    "switch",
    "combo",
    "check",
    "menu item",
    "radio",
    "list item",
    "tree item",
    "spin",
    "slider",
)
_TEXTLIKE_ROLES = ("label", "text", "paragraph", "list")
_NOISE_ACTION_PREFIXES = ("clipboard.", "selection.", "link.", "list.")
_ACTION_TREE_LIMIT = 600
_FINGERPRINT_TREE_LIMIT = 320


def _action_candidates(
    window: Any, closing: bool
) -> list[tuple[int, Any, int, str, str, str]]:
    _atspi, GLib = _atspi_import()
    close_actions = ("close", "quit", "exit")
    avoided = (
        "close",
        "quit",
        "exit",
        "delete",
        "remove",
        "cancel",
        "preview",
        "browser",
        "external",
        "launch",
        "settings",
        "print",
        "printer",
        "page",
        "export",
        "save",
    )
    candidates: list[tuple[int, Any, int, str, str, str]] = []
    for accessible in _walk(window, limit=_ACTION_TREE_LIMIT):
        try:
            actions = accessible.get_action_iface()
            count = actions.get_n_actions() if actions else 0
            role = (accessible.get_role_name() or "").casefold()
            object_name = (accessible.get_name() or "").casefold()
        except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError):
            continue
        for index in range(count):
            try:
                name = (actions.get_action_name(index) or "").casefold()
            except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError):
                continue
            if closing:
                if any(token in name for token in close_actions) or (
                    any(token in role for token in ("button", "push button"))
                    and any(
                        token in object_name
                        for token in ("close", "quit", "exit", "fechar", "sair")
                    )
                ):
                    score = 100 if any(token in name for token in close_actions) else 80
                    candidates.append((score, actions, index, name, role, object_name))
                continue

            if any(name.startswith(prefix) for prefix in _NOISE_ACTION_PREFIXES):
                continue
            if any(token in name or token in object_name for token in avoided):
                continue
            if "split view" in object_name:
                continue
            if any(
                token in object_name
                for token in ("selection editor", "search and run a command")
            ):
                continue
            if name == "menu.popup" and "combo" not in role:
                continue
            if not any(token in name for token in _INTERACTIVE_ACTIONS):
                continue
            score = 0
            if any(token in role for token in _INTERACTIVE_ROLES):
                score += 40
            if any(token in name for token in _INTERACTIVE_ACTIONS):
                score += 25
            if object_name:
                score += 10
            else:
                score -= 5
            if any(
                token in object_name
                for token in (
                    "new tab",
                    "menu",
                    "address",
                    "settings",
                    "file",
                    "edit",
                    "view",
                    "help",
                )
            ):
                score += 35
            if "menu" in object_name:
                score += 65
            if any(token in name for token in ("show-menu", "menu.popup", "open")):
                score += 15
            if any(token in role for token in _TEXTLIKE_ROLES):
                score -= 15
            candidates.append((score, actions, index, name, role, object_name))
    return sorted(candidates, key=lambda item: item[0], reverse=True)


_WIDGET_TREE_LIMIT = 1200


def _widget_record(accessible: Any) -> dict[str, Any] | None:
    """Describe one widget with the screen rectangle needed to click it."""
    Atspi, GLib = _atspi_import()
    try:
        role = accessible.get_role_name() or ""
        name = accessible.get_name() or ""
        states = accessible.get_state_set()
        component = accessible.get_component_iface()
        if component is None:
            return None
        extents = component.get_extents(Atspi.CoordType.SCREEN)
    except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError):
        return None
    if extents.width <= 0 or extents.height <= 0:
        return None
    try:
        showing = states.contains(Atspi.StateType.SHOWING)
        sensitive = states.contains(Atspi.StateType.SENSITIVE)
    except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError):
        showing = sensitive = False
    return {
        "role": role,
        "name": name,
        "x": extents.x,
        "y": extents.y,
        "width": extents.width,
        "height": extents.height,
        "center_x": extents.x + extents.width // 2,
        "center_y": extents.y + extents.height // 2,
        "showing": bool(showing),
        "sensitive": bool(sensitive),
    }


def _visible_widgets(expected_pid: int | None) -> list[tuple[Any, dict[str, Any]]]:
    """Pair every visible widget with its accessible, which can act on it."""
    allowed_pids = _process_tree(expected_pid) if expected_pid is not None else None
    widgets: list[tuple[Any, dict[str, Any]]] = []
    for window, record in _window_records():
        if allowed_pids is not None and record["pid"] not in allowed_pids:
            continue
        for accessible in _walk(window, limit=_WIDGET_TREE_LIMIT):
            widget = _widget_record(accessible)
            if widget is None:
                continue
            widget["pid"] = record["pid"]
            widget["window"] = record["name"]
            widgets.append((accessible, widget))
    return widgets


def _label_matches(name: str, labels: list[str]) -> bool:
    if not labels:
        return True

    # Compare on letters and digits only so an accelerator marker, trailing
    # punctuation or padding in a translated label does not decide the match.
    def normalize(value: str) -> str:
        return "".join(
            character for character in value.casefold() if character.isalnum()
        )

    actual = normalize(name)
    return any(label and normalize(label) == actual for label in labels)


_ACTIVATE_ACTIONS = ("click", "press", "activate", "toggle", "jump")


def _failure(
    role: str,
    labels: list[str],
    observed: list[tuple[Any, dict[str, Any]]],
    reason: str,
) -> dict[str, Any]:
    roles_wanted = {part.casefold() for part in role.split("|") if part}
    wanted = "; ".join(
        f"{widget['role']}/{widget['name'] or '?'}"
        f"{'' if widget['sensitive'] else ' (insensitive)'}"
        for _accessible, widget in observed
        if widget["role"].casefold() in roles_wanted
    )
    # Without a census of what the application did expose, a renamed control and
    # a toolkit that publishes no accessible controls at all look identical.
    census: dict[str, int] = {}
    for _accessible, widget in observed:
        census[widget["role"]] = census.get(widget["role"], 0) + 1
    roles_seen = ", ".join(
        f"{seen_role}={count}"
        for seen_role, count in sorted(census.items(), key=lambda item: -item[1])[:12]
    )
    return {
        "status": "failed",
        "error": f"{reason} for {role} matching {labels or 'any label'}"
        f"; matching roles observed: {wanted or 'none'}"
        f"; all roles observed: {roles_seen or 'none'}",
    }


def _widget_matches(
    role: str, labels: list[str], expected_pid: int | None
) -> tuple[list[tuple[Any, dict[str, Any]]], list[tuple[Any, dict[str, Any]]]]:
    roles_wanted = {part.casefold() for part in role.split("|") if part}
    observed = _visible_widgets(expected_pid)
    matches = [
        pair
        for pair in observed
        if pair[1]["role"].casefold() in roles_wanted
        and pair[1]["showing"]
        and pair[1]["sensitive"]
        and _label_matches(pair[1]["name"], labels)
    ]
    return matches, observed


def wait_for_widget(
    timeout: float,
    role: str,
    labels: list[str],
    expected_pid: int | None = None,
) -> dict[str, Any]:
    """Report whether a control with this role and label is on screen.

    Several roles may be accepted, separated by "|": widget toolkits disagree
    on whether a button is a "push button" or a "button".
    """
    deadline = time.monotonic() + timeout
    while True:
        matches, observed = _widget_matches(role, labels, expected_pid)
        if matches:
            return {
                "status": "passed",
                "widget": matches[0][1],
                "matches": len(matches),
            }
        if time.monotonic() > deadline:
            return _failure(role, labels, observed, "no showing and sensitive control")
        time.sleep(0.25)


def activate_widget(
    timeout: float,
    role: str,
    labels: list[str],
    expected_pid: int | None = None,
) -> dict[str, Any]:
    """Activate a control through its own accessibility action.

    Deliberately not a pointer click: AT-SPI reports widget extents relative to
    the window rather than to the screen, so clicking the reported rectangle
    lands on whatever sits one title bar higher. Asking the control to act on
    itself removes the coordinate system from the problem entirely.
    """
    # No AT-SPI import here: GLib.Error is a RuntimeError, so the calls below
    # are already covered, and importing would make this function unusable
    # wherever the bindings are absent, including the repository test run.
    deadline = time.monotonic() + timeout
    observed: list[tuple[Any, dict[str, Any]]] = []
    while True:
        matches, observed = _widget_matches(role, labels, expected_pid)
        for accessible, record in matches:
            try:
                actions = accessible.get_action_iface()
                count = actions.get_n_actions() if actions else 0
                names = [actions.get_action_name(index) or "" for index in range(count)]
            except (RuntimeError, AttributeError, TypeError, OSError):
                continue
            for index, name in enumerate(names):
                if name.casefold() not in _ACTIVATE_ACTIONS:
                    continue
                try:
                    performed = actions.do_action(index)
                except (RuntimeError, AttributeError, TypeError, OSError):
                    continue
                if performed:
                    return {
                        "status": "passed",
                        "widget": record,
                        "action": name,
                        "matches": len(matches),
                    }
            record["actions"] = names
        if matches:
            described = "; ".join(
                f"{record['name'] or '?'} actions={record.get('actions', [])}"
                for _accessible, record in matches
            )
            return {
                "status": "failed",
                "error": f"no usable accessibility action on {role} "
                f"matching {labels or 'any label'}: {described}",
            }
        if time.monotonic() > deadline:
            return _failure(role, labels, observed, "no showing and sensitive control")
        time.sleep(0.25)


def dump_widget_tree(expected_pid: int | None) -> dict[str, Any]:
    """Report every visible widget so a failed navigation can be diagnosed."""
    return {
        "status": "passed",
        "widgets": [record for _accessible, record in _visible_widgets(expected_pid)],
    }


def do_close(pid: int) -> dict[str, Any]:
    _atspi, GLib = _atspi_import()
    window = _window_for_pid(pid)
    if window is None:
        return {"status": "failed", "error": f"AT-SPI window for PID {pid} disappeared"}
    candidates = _action_candidates(window, closing=True)
    if not candidates:
        return {
            "status": "failed",
            "error": "application exposes no AT-SPI close action",
        }
    _score, actions, index, action_name, _role, _object_name = candidates[0]
    try:
        result = actions.do_action(index)
    except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError) as error:
        return {"status": "failed", "error": f"AT-SPI close action failed: {error}"}
    return {
        "status": "passed" if result is not False else "failed",
        "action": action_name,
        "action_result": bool(result),
    }


def cleanup_new_windows(state_path: Path, timeout: float) -> dict[str, Any]:
    """Close windows created after the current AT-SPI and X11 baselines."""
    _atspi, GLib = _atspi_import()
    deadline = time.monotonic() + max(0.1, timeout)
    session_state_path = state_path.with_name("openqa-atspi-session-baseline.json")
    baseline_path = session_state_path if session_state_path.exists() else state_path
    baseline_data = json.loads(baseline_path.read_text(encoding="utf-8"))
    baseline = set(baseline_data.get("window_keys", []))
    baseline_x11 = set(baseline_data.get("x11_window_ids", []))
    closed = 0
    for window, record in list(_window_records()):
        if record["key"] in baseline:
            continue
        candidates = _action_candidates(window, closing=True)
        if not candidates:
            continue
        _score, actions, index, _action_name, _role, _name = candidates[0]
        try:
            if actions.do_action(index) is not False:
                closed += 1
        except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError):
            continue

    def remaining_records() -> list[dict[str, Any]]:
        accessible = [
            record
            for _window, record in _window_records()
            if record["key"] not in baseline
        ]
        x11 = [
            {
                "key": f"x11:{record['id']}",
                "pid": record["pid"],
                "name": record["name"],
                "x11": True,
            }
            for record in _x11_window_records()
            if record["id"] not in baseline_x11
        ]
        return accessible + x11

    def close_new_x11_windows() -> None:
        nonlocal closed
        for record in _x11_window_records():
            if record["id"] in baseline_x11:
                continue
            if _close_x11_window(record["id"]):
                closed += 1

    def force_close_new_x11_windows() -> None:
        nonlocal closed
        for record in _x11_window_records():
            if record["id"] in baseline_x11:
                continue
            if _force_close_x11_window(record["id"]):
                closed += 1

    close_new_x11_windows()

    def wait_for_remaining() -> list[dict[str, Any]]:
        remaining = remaining_records()
        while remaining and time.monotonic() < deadline:
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
            remaining = remaining_records()
        return remaining

    remaining = wait_for_remaining()
    if not remaining:
        return {"status": "passed", "closed": closed, "remaining": []}

    force_close_new_x11_windows()
    remaining = wait_for_remaining()
    if not remaining:
        return {"status": "passed", "closed": closed, "remaining": []}

    # Some launchers daemonize or do not expose a close action. They are still
    # owned by this test session because they were absent from its baseline.
    # Terminate their process trees so one bad Desktop Entry cannot poison the
    # AT-SPI registry for every later entry.
    killed = 0
    candidate_pids = {
        record["pid"]
        for record in remaining
        if isinstance(record.get("pid"), int) and record["pid"] > 1
    }
    process_pids: set[int] = set()
    for pid in candidate_pids:
        process_pids.update(_process_tree(pid))
    for pid in sorted(process_pids, reverse=True):
        try:
            os.kill(pid, signal.SIGTERM)
            killed += 1
        except (ProcessLookupError, PermissionError, OSError):
            continue
    while time.monotonic() < deadline:
        force_close_new_x11_windows()
        close_new_x11_windows()
        remaining = remaining_records()
        if not remaining:
            return {
                "status": "passed",
                "closed": closed,
                "killed": killed,
                "remaining": [],
            }
        time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
    process_pids.clear()
    for record in remaining:
        pid = record.get("pid")
        if isinstance(pid, int) and pid > 1:
            process_pids.update(_process_tree(pid))
    for pid in sorted(process_pids, reverse=True):
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            continue
    force_close_new_x11_windows()
    close_new_x11_windows()
    remaining = remaining_records()
    return {
        "status": "failed" if remaining else "passed",
        "closed": closed,
        "killed": killed,
        "remaining": remaining,
        "error": "windows remained after cleanup",
    }


def emit(result: dict[str, Any]) -> None:
    encoded = (
        json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode().hex()
    )
    print(f"{RESULT_MARKER}{encoded}", flush=True)


def _inventory_path(state_path: Path) -> Path:
    return state_path.with_name("openqa-desktop-inventory.json")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "operation",
        choices=(
            "baseline",
            "wait-open",
            "x11-wait-open",
            "wait-close",
            "wait-widget",
            "activate-widget",
            "dump-widgets",
            "close",
            "cleanup",
            "memory",
            "inventory",
            "inventory-chunk",
        ),
    )
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--name")
    parser.add_argument("--index", type=int)
    parser.add_argument("--role")
    parser.add_argument("--labels", default="")
    args = parser.parse_args()
    os.environ.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    os.environ.setdefault(
        "DBUS_SESSION_BUS_ADDRESS", f"unix:path={os.environ['XDG_RUNTIME_DIR']}/bus"
    )
    try:
        if args.operation == "baseline":
            result = save_baseline(args.state)
        elif args.operation == "inventory":
            sys.path.insert(0, str(Path(__file__).parent))
            from desktop_entry_launcher import discover_desktop_entries

            root = Path("/usr/share/applications")
            entries = [entry.as_dict(root) for entry in discover_desktop_entries(root)]
            payload = json.dumps(
                entries, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            _inventory_path(args.state).write_bytes(payload)
            result = {
                "status": "passed",
                "entry_count": len(entries),
                "chunks": max(1, math.ceil(len(payload) / INVENTORY_CHUNK_SIZE)),
            }
        elif args.operation == "inventory-chunk":
            if args.index is None or args.index < 0:
                raise ProbeError("--index is required for inventory-chunk")
            payload = _inventory_path(args.state).read_bytes()
            start = args.index * INVENTORY_CHUNK_SIZE
            chunk = payload[start : start + INVENTORY_CHUNK_SIZE]
            if not chunk:
                raise ProbeError(f"inventory chunk {args.index} is empty")
            result = {
                "status": "passed",
                "index": args.index,
                "data": base64.b64encode(chunk).decode("ascii"),
            }
        elif args.operation in {"wait-open", "wait-close"}:
            result = wait_for_window_change(
                args.state,
                args.timeout,
                args.operation == "wait-open",
                args.pid,
                args.name,
            )
        elif args.operation == "wait-widget":
            if not args.role:
                raise ProbeError("--role is required to locate a widget")
            result = wait_for_widget(
                args.timeout,
                args.role,
                [label for label in args.labels.split("|") if label],
                args.pid if args.pid and args.pid > 1 else None,
            )
        elif args.operation == "activate-widget":
            if not args.role:
                raise ProbeError("--role is required to activate a widget")
            result = activate_widget(
                args.timeout,
                args.role,
                [label for label in args.labels.split("|") if label],
                args.pid if args.pid and args.pid > 1 else None,
            )
        elif args.operation == "dump-widgets":
            result = dump_widget_tree(args.pid if args.pid and args.pid > 1 else None)
        elif args.operation == "x11-wait-open":
            result = wait_for_x11_window(args.timeout, args.pid, args.name)
        elif args.operation == "cleanup":
            result = cleanup_new_windows(args.state, args.timeout)
        elif args.operation == "memory":
            if not args.pid or args.pid <= 1:
                raise ProbeError("--pid is required for memory sampling")
            result = {
                "status": "passed",
                "memory": sample_process_memory(args.pid, args.timeout),
            }
        else:
            if not args.pid or args.pid <= 1:
                raise ProbeError("--pid is required for close")
            result = do_close(args.pid)
    except (ProbeError, OSError, ValueError, json.JSONDecodeError) as error:
        emit({"status": "failed", "error": str(error)})
        return 1
    emit(result)
    return 0 if result.get("status") != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
