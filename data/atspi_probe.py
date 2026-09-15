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
import unicodedata
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


_ATSPI_CALL_TIMEOUT_MS = 250
_ATSPI_APP_TIMEOUT_MS = 15000
_atspi_timeout_set = False


def _atspi_import() -> tuple[Any, Any]:
    global _atspi_timeout_set
    try:
        import gi

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi, GLib
    except (ImportError, ValueError) as error:
        raise ProbeError(f"AT-SPI Python bindings are unavailable: {error}") from error
    if not _atspi_timeout_set:
        # libatspi waits 800 ms per method call by default. Every node of a
        # walk costs several calls, so one application that is on the bus but
        # not answering turns a tree walk into minutes. A quarter second is
        # still far above a healthy round trip on a loaded guest.
        try:
            Atspi.set_timeout(_ATSPI_CALL_TIMEOUT_MS, _ATSPI_APP_TIMEOUT_MS)
        except (AttributeError, TypeError):
            pass
        _atspi_timeout_set = True
    return Atspi, GLib


def _window_records(
    deadline: float | None = None, allowed_pids: set[int] | None = None
) -> Iterable[tuple[Any, dict[str, Any]]]:
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
        if deadline is not None and time.monotonic() > deadline:
            raise WalkTruncated("application enumeration exceeded its deadline")
        try:
            app = desktop.get_child_at_index(app_index)
            if app is None:
                continue
            # PID is resolved by the bus. Skip unrelated applications before
            # any widget calls: a slow shell must not consume a browser's budget.
            app_pid = app.get_process_id()
            if allowed_pids is not None and app_pid not in allowed_pids:
                continue
            app_name = app.get_name() or ""
            window_count = app.get_child_count()
        except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError):
            raise ProbeError("application enumeration was incomplete")
        for window_index in range(window_count):
            if deadline is not None and time.monotonic() > deadline:
                raise WalkTruncated("window enumeration exceeded its deadline")
            try:
                window = app.get_child_at_index(window_index)
                if window is None:
                    continue
                name = window.get_name() or ""
                role = window.get_role_name() or ""
                children = window.get_child_count()
            except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError):
                raise ProbeError("window enumeration was incomplete")
            yield (
                window,
                {
                    "key": f"{app_pid}\0{getattr(window, 'path', '') or str(window_index)}",
                    "application": app_name,
                    "name": name,
                    "role": role,
                    "children": children,
                    "pid": app_pid,
                },
            )


def accessible_snapshot(
    deadline: float | None = None, allowed_pids: set[int] | None = None
) -> dict[str, Any]:
    windows = [record for _window, record in _window_records(deadline, allowed_pids)]
    return {"windows": windows, "mem_available_mib": mem_available_mib(),
            "desktop": os.environ.get("XDG_CURRENT_DESKTOP", "unknown")}


def save_baseline(state_path: Path) -> dict[str, Any]:
    snapshot = accessible_snapshot()
    x11_windows = _x11_window_records()
    state_path.write_text(
        json.dumps(
            {
                "window_keys": [window["key"] for window in snapshot["windows"]],
                "protected_pids": [window["pid"] for window in snapshot["windows"]],
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
    sample_memory: bool = True,
) -> dict[str, Any]:
    baseline = baseline_keys(state_path)
    deadline = time.monotonic() + timeout
    last_snapshot: dict[str, Any] = {}
    while time.monotonic() <= deadline:
        # An application legitimately reaches its window through a wrapper or a
        # forked helper, so identity is the launched process tree rather than a
        # single PID. Recompute it every poll: children appear over time.
        allowed_pids = _process_tree(expected_pid) if expected_pid is not None else None
        last_snapshot = accessible_snapshot(deadline, allowed_pids)
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
                        "memory": sample_process_memory(window["pid"]) if sample_memory else process_memory(window["pid"]),
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


class WalkTruncated(Exception):
    """The tree was larger, or slower, than the budget allowed."""


def _walk(accessible: Any, limit: int = 600, deadline: float | None = None) -> Iterable[Any]:
    """Visit each accessible once; shared references are not ancestor cycles.

    GTK page containers can expose the same current panel through several
    children. A repeated object must not become an ambiguous selector or a
    false cycle. Iterative depth-first traversal distinguishes an active
    ancestor (cycle) from a fully visited shared subtree, with bounded storage.
    """
    _atspi, GLib = _atspi_import()
    stack = [(accessible, False)] if accessible is not None else []
    seen: set[int] = set()
    active: set[int] = set()
    references = []  # Keep proxies alive so Python cannot reuse their identities.
    pending = len(stack)
    visited = 0
    while stack:
        current, leaving = stack.pop()
        identity = id(current)
        if leaving:
            active.remove(identity)
            continue
        pending -= 1
        if deadline is not None and time.monotonic() > deadline:
            raise WalkTruncated(f"incomplete tree after {visited} nodes")
        if identity in active:
            raise WalkTruncated("cyclic accessibility tree")
        if identity in seen:
            continue
        if visited >= limit:
            raise WalkTruncated(f"incomplete tree after {visited} nodes")
        seen.add(identity)
        active.add(identity)
        references.append(current)
        visited += 1
        yield current
        try:
            count = current.get_child_count()
            if count < 0 or visited + pending + count > limit:
                raise WalkTruncated("child list exceeds the remaining node budget")
            stack.append((current, True))
            for index in reversed(range(count)):
                if deadline is not None and time.monotonic() > deadline:
                    raise WalkTruncated("child enumeration exceeded its deadline")
                child = current.get_child_at_index(index)
                if child is not None:
                    stack.append((child, False))
                    pending += 1
        except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError) as error:
            raise ProbeError(f"incomplete accessibility tree: {error}") from error


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


def _widget_record(accessible: Any) -> dict[str, Any]:
    """Read semantics, never require a screen rectangle to observe a control."""
    Atspi, GLib = _atspi_import()
    try:
        states = accessible.get_state_set()
        role = accessible.get_role_name() or ""
        name = accessible.get_name() or ""
        record = {"role": role, "name": name}
        for key in ("showing", "sensitive", "checked", "selected", "focused", "focusable", "defunct"):
            record[key] = bool(states.contains(getattr(Atspi.StateType, key.upper())))
        # Accessible IDs identify controls, but never replace a human label.
        getter = getattr(accessible, "get_accessible_id", None)
        record["accessible_id"] = getter() or "" if getter else ""
        record["identity"] = str(getattr(accessible, "path", ""))
        return record
    except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError) as error:
        raise ProbeError(f"could not read control semantics: {error}") from error


def _visible_widgets(
    expected_pid: int | None, deadline: float | None = None
) -> list[tuple[Any, dict[str, Any]]]:
    """Read a complete bounded scope. Propagate failure, including truncation."""
    allowed_pids = _process_tree(expected_pid) if expected_pid is not None else None
    widgets = []
    for window, record in _window_records(deadline, allowed_pids):
        if allowed_pids is not None and record["pid"] not in allowed_pids:
            continue
        for accessible in _walk(window, limit=_WIDGET_TREE_LIMIT, deadline=deadline):
            widget = _widget_record(accessible)
            widget["pid"] = record["pid"]
            widget["window"] = record["name"]
            if not widget["defunct"]:
                widgets.append((accessible, widget))
    return widgets


_MARKUP_TAG = re.compile(r"<[^>]*>")


def _normalize_label(value: str) -> str:
    """Reduce a label to unaccented letters and digits, ignoring markup.

    Calamares names some controls with their whole rich-text description, for
    example "<strong>Erase disk</strong><br/>This will delete all data...", so
    the tags have to go before anything can be compared. Dropping punctuation
    and spacing also means an accelerator marker or a translator's padding
    cannot decide the match.

    Diacritics are folded away as well. A test that asks for "Concluir" should
    not miss a button named "Concluído", and a caller that types the label
    without its accent should not silently match nothing.
    """
    decomposed = unicodedata.normalize("NFKD", _MARKUP_TAG.sub(" ", value))
    return "".join(
        character
        for character in decomposed.casefold()
        if character.isalnum() and not unicodedata.combining(character)
    )


def _label_is_exact(name: str, labels: list[str]) -> bool:
    actual = _normalize_label(name)
    return any(label and _normalize_label(label) == actual for label in labels)


def _label_matches(name: str, labels: list[str]) -> bool:
    if not labels:
        return True
    # Only an explicitly marked heading may stand in for a rich description.
    # A plain "Install" must not accidentally select "Install something else".
    heading = re.match(r"\s*<(?:strong|b)>(.*?)</(?:strong|b)>", name, re.I | re.S)
    candidates = [name] + ([heading.group(1)] if heading else [])
    return any(_label_is_exact(candidate, labels) for candidate in candidates)


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
    role: str,
    labels: list[str],
    expected_pid: int | None,
    budget: float | None = None,
    accessible_id: str | None = None,
    window_name: str | None = None,
    require_sensitive: bool = True,
) -> tuple[list[tuple[Any, dict[str, Any]]], list[tuple[Any, dict[str, Any]]]]:
    roles_wanted = {part.casefold() for part in role.split("|") if part}
    observed = _visible_widgets(
        expected_pid, time.monotonic() + budget if budget is not None else None
    )
    matches = [pair for pair in observed
               if (not roles_wanted or pair[1]["role"].casefold() in roles_wanted)
               and pair[1]["showing"]
               and (not require_sensitive or pair[1]["sensitive"])
               and (not accessible_id or pair[1].get("accessible_id") == accessible_id)
               and (window_name is None or pair[1].get("window") == window_name)
               and _label_matches(pair[1]["name"], labels)]
    return matches, observed


def wait_for_widget(
    timeout: float, role: str, labels: list[str], expected_pid: int | None = None,
    *, accessible_id: str | None = None, window_name: str | None = None,
    absent: bool = False, checked: bool | None = None,
) -> dict[str, Any]:
    """A unique match, or confirmed absence; errors are never disappearance."""
    deadline = time.monotonic() + timeout
    while True:
        matches, observed = _widget_matches(
            role, labels, expected_pid, max(0.01, deadline - time.monotonic()),
            accessible_id, window_name, require_sensitive=not absent,
        )
        if len(matches) > 1:
            return {"status": "failed", "reason": "ambiguous", "complete": True,
                    "matches": len(matches), "error": "selector matches multiple controls"}
        if absent and not matches:
            return {"status": "passed", "reason": "absent", "complete": True}
        if not absent and len(matches) == 1:
            record = matches[0][1]
            if checked is None or record.get("checked") is checked:
                return {"status": "passed", "widget": record, "matches": 1, "complete": True}
        if time.monotonic() >= deadline:
            result = _failure(role, labels, observed, "required control state not reached")
            result.update(reason="state-not-reached" if matches else "not-found", complete=True)
            return result
        time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))


def activate_widget(
    timeout: float, role: str, labels: list[str], expected_pid: int | None = None,
    *, accessible_id: str | None = None, window_name: str | None = None,
) -> dict[str, Any]:
    """Explicit AT action, not a proof of keyboard reachability.

    No focus teleportation fallback. The host's keyboard helper traverses
    normal focus and sends a key instead when testing keyboard operation.
    """
    found = wait_for_widget(timeout, role, labels, expected_pid,
                            accessible_id=accessible_id, window_name=window_name)
    if found["status"] != "passed":
        return found
    matches, _observed = _widget_matches(role, labels, expected_pid, 3,
                                        accessible_id, window_name)
    if len(matches) != 1:
        return {"status": "failed", "error": "selector changed before activation"}
    accessible, record = matches[0]
    _atspi, GLib = _atspi_import()
    try:
        actions = accessible.get_action_iface()
        for index in range(actions.get_n_actions() if actions else 0):
            name = actions.get_action_name(index) or ""
            if name.casefold() in _ACTIVATE_ACTIONS and actions.do_action(index):
                return {"status": "passed", "widget": record, "action": name,
                        "activation": "atspi-action", "matches": 1}
    except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError) as error:
        raise ProbeError(f"accessibility action failed: {error}") from error
    return {"status": "failed", "error": "control has no usable accessibility action"}


def focused_widget(timeout: float, expected_pid: int | None = None) -> dict[str, Any]:
    """Observe focus without moving it; never return password contents."""
    deadline = time.monotonic() + timeout
    pairs = _visible_widgets(expected_pid, deadline)
    focused = [record for _, record in pairs if record.get("focused") and record["showing"]]
    if len(focused) != 1:
        return {"status": "failed", "reason": "ambiguous" if focused else "not-found",
                "complete": True, "matches": len(focused),
                "error": "expected exactly one focused control in the requested scope"}
    return {"status": "passed", "widget": focused[0], "complete": True}


def _smoke_content(window: Any, deadline: float, limit: int = 256) -> dict[str, Any] | None:
    """Find one usable descendant, not audit or snapshot the entire tree.

    Iterators fetch children lazily, so a wide view does not require allocating
    thousands of proxies. Success proves existence only, never completeness.
    No text values (potentially sensitive) are included in the evidence.
    """
    # An iterator owns one active ancestor. A shared, already exhausted panel
    # is not a cycle; keep references alive so proxy IDs cannot be recycled.
    exhausted = object()
    stack = [(iter([window]), None)]
    seen = set()
    active = set()
    references = []
    visited = examined = 0
    missing_child = False
    while stack:
        if time.monotonic() > deadline:
            raise WalkTruncated("no accessible content found within the smoke deadline")
        iterator, parent = stack[-1]
        node = next(iterator, exhausted)
        if node is exhausted:
            stack.pop()
            if parent is not None:
                active.remove(parent)
            continue
        if examined >= limit * 4:
            raise WalkTruncated("smoke reference budget exhausted")
        examined += 1
        if node is None:
            missing_child = True
            continue
        identity = id(node)
        if identity in active:
            raise WalkTruncated("cyclic accessibility tree")
        if identity in seen:
            continue
        if visited >= limit:
            raise WalkTruncated("no accessible content found within the smoke node budget")
        seen.add(identity)
        active.add(identity)
        references.append(node)
        visited += 1
        if node is not window:
            record = _widget_record(node)
            if record["showing"] and not record["defunct"]:
                text = node.get_text_iface()
                action = node.get_action_iface()
                value = node.get_value_iface()
                text_available = text is not None and text.get_character_count() >= 0
                action_available = action is not None and action.get_n_actions() > 0
                named = bool(record["name"].strip())
                informational = record["role"] in {
                    "label", "static", "heading", "list item", "tree item", "table cell", "link"
                }
                if text_available or (named and (action_available or value is not None
                                                or record.get("focusable") or informational)):
                    return {"role": record["role"], "has_name": named,
                            "text_interface": text_available, "action_interface": action_available,
                            "value_interface": value is not None, "nodes_visited": visited}
        count = node.get_child_count()
        if count < 0:
            raise ProbeError("invalid child count in smoke query")
        # Bind node now: a generator expression otherwise follows the next node.
        stack.append((map(node.get_child_at_index, range(count)), identity))
    if missing_child:
        raise ProbeError("no content witness in an incomplete smoke tree")
    return None


def smoke_window(timeout: float, expected_pid: int, active_only: bool = False) -> dict[str, Any]:
    """Observe the launched application's window/content without moving focus."""
    Atspi, GLib = _atspi_import()
    deadline = time.monotonic() + timeout
    reason = "no accessible window/content for the launched application"
    while True:
        try:
            for window, record in _window_records(deadline, {expected_pid}):
                if record["pid"] != expected_pid:
                    continue
                states = window.get_state_set()
                if not states.contains(Atspi.StateType.SHOWING):
                    continue
                if states.contains(Atspi.StateType.DEFUNCT):
                    continue
                if record["role"] not in {"frame", "window", "dialog"}:
                    continue
                if active_only:
                    if states.contains(Atspi.StateType.ACTIVE):
                        return {"status": "passed", "pid": expected_pid, "active": True}
                    reason = "target window is not active; close shortcut was not sent"
                    continue
                evidence = _smoke_content(window, deadline)
                if evidence is not None:
                    return {"status": "passed", "pid": expected_pid,
                            "coverage": "accessible-content-present", "evidence": evidence}
        except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError) as error:
            raise ProbeError(f"smoke query could not read the application: {error}") from error
        if launch_process_exited(expected_pid):
            return {"status": "failed", "error": "application exited before the smoke check"}
        if time.monotonic() >= deadline:
            return {"status": "failed", "error": reason}
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))


def audit_window(timeout: float, expected_pid: int) -> dict[str, Any]:
    """Minimum semantics check, deliberately not a functional certification."""
    pairs = _visible_widgets(expected_pid, time.monotonic() + timeout)
    controls = [record for _, record in pairs
                if record["showing"] and record.get("focusable") and record["sensitive"]]
    unnamed = [record for record in controls
               if not record["name"].strip() and record["role"] not in
               {"text", "entry", "terminal", "document text", "document web"}]
    # Text editors can expose their document text without naming the document
    # control. A form-specific test must still check its label and relationships.
    return {"status": "failed" if not controls or unnamed else "passed",
            "complete": True, "controls": len(controls),
            "unnamed_controls": len(unnamed),
            "error": "no operable accessible controls or unnamed non-text controls"
            if not controls or unnamed else "", "coverage": "semantics-only"}


def dump_widget_tree(expected_pid: int | None, timeout: float = 30) -> dict[str, Any]:
    """Report every visible widget so a failed navigation can be diagnosed.

    Bounded like every other operation: this runs when something has already
    gone wrong, which is exactly when the tree is most likely to be slow.
    """
    deadline = time.monotonic() + timeout
    # Only widgets a test could have named. An anonymous container is never the
    # answer to "which control should I have asked for", and there are hundreds
    # of them: a full dump of one GTK4 page did not fit through the serial
    # console before the caller gave up, which made the diagnostic useless
    # exactly when it was needed.
    widgets = [
        record
        for _accessible, record in _visible_widgets(expected_pid, deadline)
        if record.get("name")
    ]
    return {
        "status": "passed",
        "widgets": widgets,
        "truncated": False,
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
    protected = set(baseline_data.get("protected_pids", []))
    closed = 0
    for window, record in list(_window_records()):
        if record["key"] in baseline or record["pid"] in protected:
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
            if record["key"] not in baseline and record["pid"] not in protected
        ]
        x11 = [
            {
                "key": f"x11:{record['id']}",
                "pid": record["pid"],
                "name": record["name"],
                "x11": True,
            }
            for record in _x11_window_records()
            if record["id"] not in baseline_x11 and record["pid"] not in protected
        ]
        return accessible + x11

    def close_new_x11_windows() -> None:
        nonlocal closed
        for record in _x11_window_records():
            if record["id"] in baseline_x11 or record["pid"] in protected:
                continue
            if _close_x11_window(record["id"]):
                closed += 1

    def force_close_new_x11_windows() -> None:
        nonlocal closed
        for record in _x11_window_records():
            if record["id"] in baseline_x11 or record["pid"] in protected:
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
            "wait-gone",
            "focused-widget",
            "audit-window",
            "smoke-window",
            "active-window",
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
    parser.add_argument("--accessible-id")
    parser.add_argument("--window")
    parser.add_argument("--checked", choices=("true", "false"))
    parser.add_argument("--no-memory-sample", action="store_true")
    args = parser.parse_args()
    os.environ.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    os.environ.setdefault(
        "DBUS_SESSION_BUS_ADDRESS", f"unix:path={os.environ['XDG_RUNTIME_DIR']}/bus"
    )
    try:
        if not math.isfinite(args.timeout) or args.timeout < 0:
            raise ProbeError("timeout must be finite and nonnegative")
        if args.pid is not None and args.pid <= 1:
            raise ProbeError("pid must be greater than one")
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
                sample_memory=not args.no_memory_sample,
            )
        elif args.operation == "focused-widget":
            result = focused_widget(args.timeout, args.pid)
        elif args.operation in {"smoke-window", "active-window"}:
            if args.pid is None:
                raise ProbeError("--pid is required for window smoke checks")
            result = smoke_window(args.timeout, args.pid, args.operation == "active-window")
        elif args.operation == "audit-window":
            if args.pid is None:
                raise ProbeError("--pid is required for audit-window")
            result = audit_window(args.timeout, args.pid)
        elif args.operation in {"wait-widget", "wait-gone"}:
            if not args.role:
                raise ProbeError("--role is required to locate a widget")
            result = wait_for_widget(
                args.timeout,
                args.role,
                [label for label in args.labels.split("|") if label],
                args.pid,
                accessible_id=args.accessible_id, window_name=args.window,
                absent=args.operation == "wait-gone",
                checked=None if args.checked is None else args.checked == "true",
            )
        elif args.operation == "activate-widget":
            if not args.role:
                raise ProbeError("--role is required to activate a widget")
            result = activate_widget(
                args.timeout,
                args.role,
                [label for label in args.labels.split("|") if label],
                args.pid,
                accessible_id=args.accessible_id, window_name=args.window,
            )
        elif args.operation == "dump-widgets":
            result = dump_widget_tree(
                args.pid if args.pid and args.pid > 1 else None, args.timeout
            )
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
    except (ProbeError, WalkTruncated, OSError, ValueError, json.JSONDecodeError) as error:
        emit({"status": "inconclusive", "complete": False, "error": str(error)})
        return 1
    emit(result)
    return 0 if result.get("status") in {None, "passed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
