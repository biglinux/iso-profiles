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
from collections import deque
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

RESULT_MARKER = "__OPENQA_ATSPI__"
READY_MARKER = "__OPENQA_ATSPI_READY__"
INVENTORY_CHUNK_SIZE = 600


class ProbeError(RuntimeError):
    """AT-SPI could not provide a coherent result."""


def _read_until_ready(read: Callable[[], Any], deadline: float) -> Any:
    """Retry a read-only observation, never an action, within the caller's budget.

    A newly published application can briefly refuse a method while building
    its widgets. Discard that partial read and retry the whole scoped query.
    A persistent provider error still raises ProbeError; structural truncation
    is not retried, and no incomplete read can establish absence or success.
    """
    while True:
        try:
            return read()
        except ProbeError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(0.1, remaining))


def mem_available_mib(meminfo: Path = Path("/proc/meminfo")) -> float | None:
    try:
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return round(int(line.split()[1]) / 1024, 1)
    except (OSError, ValueError, IndexError):
        return None
    return None


def _status_fields(status: Path) -> dict[str, str]:
    return {
        line.split(":", 1)[0]: line.split(":", 1)[1].strip()
        for line in status.read_text(encoding="utf-8", errors="replace").splitlines()
        if ":" in line
    }


def _process_group_id(pid: int, proc_root: Path = Path("/proc")) -> int | None:
    """Return the process-group ID visible in the guest's PID namespace."""
    if pid <= 1:
        return None
    process = proc_root / str(pid)
    try:
        fields = _status_fields(process / "status")
        namespace_group = fields.get("NSpgid")
        if namespace_group:
            group = int(namespace_group.split()[-1])
            return group if group > 1 else None
    except (OSError, ValueError, IndexError):
        pass

    # Older kernels or synthetic fixtures may omit NSpgid. /proc/PID/stat
    # field 5 is pgrp; split only after the final ')' because comm may contain
    # spaces and parentheses.
    try:
        raw = (process / "stat").read_text(encoding="utf-8", errors="replace")
        close = raw.rfind(")")
        if close < 0:
            return None
        fields = raw[close + 2 :].split()
        group = int(fields[2])
        return group if group > 1 else None
    except (OSError, ValueError, IndexError):
        return None


def _process_group_members(
    group_ids: set[int], proc_root: Path = Path("/proc")
) -> set[int]:
    """Return live processes in the supervised POSIX process groups."""
    groups = {group for group in group_ids if group > 1}
    if not groups:
        return set()
    members: set[int] = set()
    for status in proc_root.glob("[0-9]*/status"):
        try:
            pid = int(status.parent.name)
        except ValueError:
            continue
        if _process_group_id(pid, proc_root) in groups:
            members.add(pid)
    return members


def _process_tree(root_pid: int, proc_root: Path = Path("/proc")) -> set[int]:
    if root_pid <= 0:
        return set()
    parents: dict[int, int] = {}
    for status in proc_root.glob("[0-9]*/status"):
        try:
            fields = _status_fields(status)
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


def _launch_process_scope(
    root_pid: int,
    known_pids: Iterable[int] = (),
    proc_root: Path = Path("/proc"),
) -> set[int]:
    """Follow a supervised launch after helpers fork and re-parent children.

    gui_supervisor starts each tested command in a new session/process group.
    A launcher may exit after handing the GUI to a child, at which point PPid
    traversal loses the still-owned application even though its process group
    remains stable. Combine the ordinary descendant tree, already observed
    window PIDs and members of those supervised groups. This never admits an
    unrelated desktop process merely because it has a similar name or window.
    """
    seeds = {pid for pid in (root_pid, *known_pids) if isinstance(pid, int) and pid > 1}
    if not seeds:
        return set()
    scope = _process_tree(root_pid, proc_root)
    scope.update(seeds)
    root_group = _process_group_id(root_pid, proc_root)
    root_exists = (proc_root / str(root_pid)).exists()
    # gui_supervisor records the PID returned by `setsid` as both the launch
    # PID and the process-group ID.  When that leader is still alive, verify
    # the invariant before widening: a caller that accidentally passes a
    # normal desktop process must not import every peer in its shared session
    # group.  After the verified leader exits, /proc can no longer expose its
    # group, but surviving children retain the former leader PID as their PGID.
    group_ids = {root_pid} if not root_exists or root_group == root_pid else set()
    scope.update(_process_group_members(group_ids, proc_root))
    return scope


def _owned_process_scope(
    expected_pid: int | None,
    supervised_root_pid: int | None = None,
    known_pids: Iterable[int] = (),
    proc_root: Path = Path("/proc"),
) -> set[int]:
    """Return a PID scope, widening to a process group only when explicit.

    A PID selected from an arbitrary desktop or live-session accessibility
    object is not proof that its POSIX process group belongs to this test.  The
    group-based recovery is therefore enabled only when the caller supplies the
    root PID created by ``gui_supervisor.sh``.  Ordinary PID scopes retain the
    historical descendant-only behaviour.
    """
    proven = {
        pid
        for pid in (expected_pid, *known_pids)
        if isinstance(pid, int) and pid > 1
    }
    if supervised_root_pid is not None:
        return _launch_process_scope(supervised_root_pid, proven, proc_root)
    if expected_pid is None:
        return proven
    scope = _process_tree(expected_pid, proc_root)
    scope.update(proven)
    return scope


def _process_scope_exited(
    pids: Iterable[int], proc_root: Path = Path("/proc")
) -> bool:
    """Return true only when every process in a scoped launch has ended."""
    candidates = {pid for pid in pids if isinstance(pid, int) and pid > 1}
    return bool(candidates) and all(
        launch_process_exited(pid, proc_root) for pid in candidates
    )


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


_ATSPI_CALL_TIMEOUT_MS = 800
_ATSPI_APP_TIMEOUT_MS = -1
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
        # Readiness is polled by our bounded waits. A new probe process must
        # not give every already-running application a fresh 15-second grace
        # period: that can consume an entire eight-second smoke in one call.
        # Keep the normal upstream call timeout, with no separate startup grace.
        try:
            Atspi.set_timeout(_ATSPI_CALL_TIMEOUT_MS, _ATSPI_APP_TIMEOUT_MS)
        except (AttributeError, TypeError):
            pass
        _atspi_timeout_set = True
    return Atspi, GLib


def _window_records(
    deadline: float | None = None,
    allowed_pids: set[int] | None = None,
    preferred_application_index: int | None = None,
    stop_after_preferred_match: bool = False,
    preferred_window_identity: str | None = None,
    include_window_state: bool = False,
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

    # Newly launched applications are normally appended to the registry.
    # PID-scoped probes need no semantic data from unrelated applications, so
    # inspect recent entries first. Unscoped baselines retain registry order.
    application_indexes = list(
        range(application_count - 1, -1, -1)
        if allowed_pids is not None
        else range(application_count)
    )
    # A widget record carries the registry slot that produced it, but the slot
    # is not an identity: short-lived providers can insert or disappear between
    # probes. Try the old slot once, revalidate its PID, then resume the normal
    # newest-first order. Searching numerically around a stale slot delays the
    # newly launched target behind many unrelated providers and can consume the
    # entire caller budget in get_process_id() calls.
    if (
        preferred_application_index is not None
        and 0 <= preferred_application_index < application_count
    ):
        application_indexes = [preferred_application_index] + [
            index for index in application_indexes
            if index != preferred_application_index
        ]
    for app_index in application_indexes:
        if deadline is not None and time.monotonic() > deadline:
            raise WalkTruncated("application enumeration exceeded its deadline")
        app_pid: int | None = None
        try:
            app = desktop.get_child_at_index(app_index)
            if app is None:
                continue
            # PID is resolved by the bus. Skip unrelated applications before
            # any widget calls: a slow shell must not consume the target budget.
            app_pid = app.get_process_id()
            if allowed_pids is not None and app_pid not in allowed_pids:
                continue
            app_name = app.get_name() or ""
            window_count = app.get_child_count()
            preferred_match = (
                preferred_application_index is not None
                and app_index == preferred_application_index
                and allowed_pids is not None
                and app_pid in allowed_pids
            )
        except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError) as error:
            # The registry can retain an application proxy for a process that
            # exited between reading the desktop child and its metadata. Such a
            # process cannot own a live window that the baseline must protect.
            if allowed_pids is None and app_pid is not None and launch_process_exited(app_pid):
                continue
            raise ProbeError(
                f"application enumeration was incomplete (index {app_index}, {type(error).__name__})"
            ) from error
        window_candidates: list[tuple[int, Any, str]] = []
        for window_index in range(window_count):
            if deadline is not None and time.monotonic() > deadline:
                raise WalkTruncated("window enumeration exceeded its deadline")
            try:
                window = app.get_child_at_index(window_index)
                if window is None:
                    continue
                identity = getattr(window, "path", "") or str(window_index)
            except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError) as error:
                if allowed_pids is None and launch_process_exited(app_pid):
                    break
                raise ProbeError(
                    f"window enumeration was incomplete (PID {app_pid}, index {window_index}, "
                    f"{type(error).__name__})"
                ) from error
            candidate = (window_index, window, identity)
            if preferred_window_identity is not None and identity == preferred_window_identity:
                window_candidates.insert(0, candidate)
            else:
                window_candidates.append(candidate)

        for window_ordinal, (window_index, window, identity) in enumerate(window_candidates):
            if deadline is not None and time.monotonic() > deadline:
                raise WalkTruncated("window semantics exceeded its deadline")
            try:
                name = window.get_name() or ""
                role = window.get_role_name() or ""
                children = window.get_child_count()
                showing = True
                defunct = False
                if include_window_state:
                    states = window.get_state_set()
                    showing = states.contains(Atspi.StateType.SHOWING)
                    defunct = states.contains(Atspi.StateType.DEFUNCT)
            except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError) as error:
                if allowed_pids is None and launch_process_exited(app_pid):
                    break
                raise ProbeError(
                    f"window enumeration was incomplete (PID {app_pid}, index {window_index}, "
                    f"{type(error).__name__})"
                ) from error
            yield (
                window,
                {
                    "key": f"{app_pid}\0{identity}",
                    "identity": identity,
                    "application": app_name,
                    "application_index": app_index,
                    "name": name,
                    "role": role,
                    "children": children,
                    "application_window_count": window_count,
                    "application_candidate_window_count": len(window_candidates),
                    "application_window_ordinal": window_ordinal,
                    "pid": app_pid,
                    "showing": showing,
                    "defunct": defunct,
                },
            )
            if preferred_window_identity is not None and identity == preferred_window_identity:
                return
        # A PID-verified registry hint identifies the application object that
        # produced the prior window/widget. Once fully inspected, unrelated
        # providers cannot improve the same observation. A stale PID mismatch
        # never reaches this branch and therefore still falls back safely.
        if stop_after_preferred_match and preferred_match:
            return


def accessible_snapshot(
    deadline: float | None = None, allowed_pids: set[int] | None = None
) -> dict[str, Any]:
    windows = [
        record
        for _window, record in _window_records(
            deadline, allowed_pids, include_window_state=True
        )
    ]
    return {"windows": windows, "mem_available_mib": mem_available_mib(),
            "desktop": os.environ.get("XDG_CURRENT_DESKTOP", "unknown")}


def _baseline_window_records(deadline: float) -> list[dict[str, Any]]:
    """Read only the identities needed to distinguish pre-existing windows.

    A launch baseline is not a semantic accessibility audit. Calling Name,
    Role and child-count methods on every top-level window made a three-second
    baseline spend its whole budget on unrelated providers, while returning
    those fields over the serial console could also exceed openQA's capture
    buffer. The state file needs only stable window keys and their owning PIDs.

    Provider failures remain strict: only a proxy whose PID has demonstrably
    exited may disappear during the read. A live or unidentified provider
    error invalidates the complete baseline and is retried by the caller within
    the original shared deadline.
    """
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

    records: list[dict[str, Any]] = []
    for app_index in range(application_count):
        if time.monotonic() > deadline:
            raise WalkTruncated("baseline application enumeration exceeded its deadline")
        app_pid: int | None = None
        try:
            app = desktop.get_child_at_index(app_index)
            if app is None:
                continue
            app_pid = app.get_process_id()
            window_count = app.get_child_count()
        except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError) as error:
            if app_pid is not None and launch_process_exited(app_pid):
                continue
            raise ProbeError(
                f"baseline application enumeration was incomplete "
                f"(index {app_index}, {type(error).__name__})"
            ) from error

        for window_index in range(window_count):
            if time.monotonic() > deadline:
                raise WalkTruncated("baseline window enumeration exceeded its deadline")
            try:
                window = app.get_child_at_index(window_index)
                if window is None:
                    continue
                identity = getattr(window, "path", "") or str(window_index)
            except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError) as error:
                if launch_process_exited(app_pid):
                    break
                raise ProbeError(
                    f"baseline window enumeration was incomplete "
                    f"(PID {app_pid}, index {window_index}, {type(error).__name__})"
                ) from error
            records.append({"key": f"{app_pid}\0{identity}", "pid": app_pid})
    return records


def save_baseline(state_path: Path, timeout: float = 10) -> dict[str, Any]:
    # Session applications may be registering or disappearing while one test
    # hands the desktop to the next. Retry a complete read within one shared
    # deadline; never persist a partial baseline.
    deadline = time.monotonic() + timeout
    windows = _read_until_ready(lambda: _baseline_window_records(deadline), deadline)
    snapshot = {
        "windows": windows,
        "mem_available_mib": mem_available_mib(),
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP", "unknown"),
    }
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
    # Keep the serial response intentionally small. The authoritative window
    # identities are already persisted in state_path and are consumed by
    # wait-open/cleanup inside the guest; the host needs only completeness,
    # memory and desktop metadata.
    return {
        "status": "passed",
        "window_count": len(snapshot["windows"]),
        "mem_available_mib": snapshot["mem_available_mib"],
        "desktop": snapshot["desktop"],
    }


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
    supervised_root_pid: int | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_windows: list[dict[str, Any]] = []
    while time.monotonic() <= deadline:
        last_windows = _x11_window_records()
        process_pids = _owned_process_scope(expected_pid, supervised_root_pid)
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
        if expected_pid and _process_scope_exited(process_pids):
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
    expected_window_identity: str | None = None,
    supervised_root_pid: int | None = None,
) -> dict[str, Any]:
    baseline = baseline_keys(state_path)
    deadline = time.monotonic() + timeout
    last_snapshot: dict[str, Any] = {}

    def window_identity(window: dict[str, Any]) -> str:
        identity = window.get("identity")
        if identity:
            return str(identity)
        key = str(window.get("key", ""))
        return key.split("\0", 1)[1] if "\0" in key else key

    def window_is_showing(window: dict[str, Any]) -> bool:
        # Older synthetic fixtures omit state; keep their historical default.
        # Real snapshots always carry SHOWING/DEFUNCT from the top-level object.
        return bool(window.get("showing", True)) and not bool(window.get("defunct", False))

    while time.monotonic() <= deadline:
        # An application can reach its window through a wrapper or forked
        # helper, so identity is the launched process tree, recomputed per poll.
        allowed_pids = (
            _owned_process_scope(expected_pid, supervised_root_pid)
            if expected_pid is not None
            else None
        )
        last_snapshot = _read_until_ready(
            lambda: accessible_snapshot(deadline, allowed_pids), deadline
        )
        if not opening and expected_window_identity is not None:
            target_present = any(
                window_identity(window) == expected_window_identity
                and window_is_showing(window)
                for window in last_snapshot["windows"]
                if allowed_pids is None or window["pid"] in allowed_pids
            )
            if not target_present:
                return {
                    "status": "passed",
                    "accessible_window": True,
                    "process_gone": _process_scope_exited(allowed_pids or set()),
                    "mem_available_mib": last_snapshot.get("mem_available_mib"),
                }
        extra = [
            window
            for window in last_snapshot["windows"]
            if window["key"] not in baseline
            and window_is_showing(window)
            and (allowed_pids is None or window["pid"] in allowed_pids)
            and _name_matches(
                " ".join(
                    value for value in (window["application"], window["name"]) if value
                ),
                expected_name,
            )
        ]
        if opening and not extra and _process_scope_exited(allowed_pids or set()):
            return {
                "status": "failed",
                "accessible_window": False,
                "mem_available_mib": last_snapshot.get("mem_available_mib"),
                "error": "launch process exited before exposing an accessible window; "
                f"observed={_describe_windows(last_snapshot['windows'])}",
            }
        usable = [window for window in extra if not _is_transient_window(window)]
        if (
            not opening
            and expected_pid is not None
            and _process_scope_exited(allowed_pids or set())
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
                        "application_index": window.get("application_index"),
                        "window_identity": window_identity(window),
                        "memory": sample_process_memory(window["pid"])
                        if sample_memory
                        else process_memory(window["pid"]),
                    }
                )
            return result
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(0.1, remaining))
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


def _showing_widgets_in_window(
    window: Any,
    pid: int,
    window_name: str,
    deadline: float | None,
    limit: int = _WIDGET_TREE_LIMIT,
    application_index: int | None = None,
) -> Iterable[tuple[Any, dict[str, Any]]]:
    """Yield SHOWING controls fairly while retaining strict finite bounds."""
    _atspi, GLib = _atspi_import()
    exhausted = object()
    work = deque([(iter([window]), frozenset())])
    seen: set[int] = set()
    references: list[Any] = []
    visited = examined = 0
    while work:
        if deadline is not None and time.monotonic() > deadline:
            raise WalkTruncated(f"incomplete tree after {visited} nodes")
        iterator, ancestors = work.popleft()
        node = next(iterator, exhausted)
        if node is exhausted:
            continue
        # Visit remaining siblings before descending into this node. This keeps
        # a giant first menu or web subtree from hiding a shallow control.
        work.append((iterator, ancestors))
        if examined >= limit * 4:
            raise WalkTruncated("widget reference budget exhausted")
        examined += 1
        if node is None:
            raise ProbeError("widget query encountered a missing child")
        identity = id(node)
        if identity in ancestors:
            raise WalkTruncated("cyclic accessibility tree")
        if identity in seen:
            continue
        if visited >= limit:
            raise WalkTruncated(f"incomplete tree after {visited} nodes")
        seen.add(identity)
        references.append(node)
        visited += 1
        record = _widget_record(node)
        record["pid"] = pid
        record["window"] = window_name
        if application_index is not None:
            record["application_index"] = application_index
        if record["defunct"] or not record["showing"]:
            continue
        yield node, record
        try:
            count = node.get_child_count()
            if count < 0:
                raise ProbeError("invalid child count in widget query")
            work.append(
                (map(node.get_child_at_index, range(count)), ancestors | {identity})
            )
        except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError) as error:
            raise ProbeError(f"incomplete accessibility tree: {error}") from error


def _visible_widgets(
    expected_pid: int | None,
    deadline: float | None = None,
    supervised_root_pid: int | None = None,
) -> list[tuple[Any, dict[str, Any]]]:
    allowed_pids = (
        _owned_process_scope(expected_pid, supervised_root_pid)
        if expected_pid is not None or supervised_root_pid is not None
        else None
    )
    widgets: list[tuple[Any, dict[str, Any]]] = []
    for window, record in _window_records(deadline, allowed_pids):
        if allowed_pids is not None and record["pid"] not in allowed_pids:
            continue
        widgets.extend(
            _showing_widgets_in_window(
                window,
                record["pid"],
                record["name"],
                deadline,
                application_index=record.get("application_index"),
            )
        )
    return widgets


_MARKUP_TAG = re.compile(r"<[^>]*>")


def _normalize_label(value: str) -> str:
    """Reduce a label to unaccented letters and digits, ignoring markup.

    Calamares names some controls with their whole rich-text description, for
    example "<strong>Erase disk</strong><br/>This will delete all data...", so
    the tags have to go before anything can be compared. Dropping punctuation
    and spacing also means an accelerator marker or a translator's padding
    cannot decide the match.

    Diacritics are folded away as well. A caller that types "Concluido" should
    not miss a button named "Concluído". Different words such as "Concluir"
    still require their own explicit label.
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
    application_index: int | None = None,
    stop_after_matching_application: bool = False,
    supervised_root_pid: int | None = None,
) -> tuple[list[tuple[Any, dict[str, Any]]], list[tuple[Any, dict[str, Any]]]]:
    roles_wanted = {part.casefold() for part in role.split("|") if part}

    def matches_selector(pair: tuple[Any, dict[str, Any]]) -> bool:
        widget = pair[1]
        return (not roles_wanted or widget["role"].casefold() in roles_wanted) \
            and widget["showing"] \
            and (not require_sensitive or widget["sensitive"]) \
            and (not accessible_id or widget.get("accessible_id") == accessible_id) \
            and (window_name is None or widget.get("window") == window_name) \
            and _label_matches(widget["name"], labels)

    deadline = time.monotonic() + budget if budget is not None else None
    if application_index is None:
        observed = _visible_widgets(expected_pid, deadline, supervised_root_pid)
        return [pair for pair in observed if matches_selector(pair)], observed

    # A page transition can replace the launcher's GTK application with a Qt
    # application while both remain descendants of the same supervised launch.
    # Start near the last PID-verified registry slot and finish one candidate
    # application at a time. Once that application exposes one unique selector,
    # unrelated desktop providers cannot make the page more correct. This keeps
    # the query bounded without accepting a title, coordinate, or stale slot.
    allowed_pids = (
        _owned_process_scope(expected_pid, supervised_root_pid)
        if expected_pid is not None or supervised_root_pid is not None
        else None
    )
    observed: list[tuple[Any, dict[str, Any]]] = []
    application_matches: list[tuple[Any, dict[str, Any]]] = []
    current_application: int | None = None
    for window, record in _window_records(
        deadline,
        allowed_pids,
        preferred_application_index=application_index,
    ):
        if allowed_pids is not None and record["pid"] not in allowed_pids:
            continue
        record_application = record.get("application_index")
        if current_application is not None and record_application != current_application:
            if stop_after_matching_application and application_matches:
                return application_matches, observed
            application_matches = []
        current_application = record_application
        pairs = list(
            _showing_widgets_in_window(
                window,
                record["pid"],
                record["name"],
                deadline,
                application_index=record_application,
            )
        )
        observed.extend(pairs)
        application_matches.extend(pair for pair in pairs if matches_selector(pair))
        last_window = (
            record.get("application_window_ordinal", 0) + 1
            >= record.get("application_candidate_window_count", 1)
        )
        if stop_after_matching_application and last_window and application_matches:
            return application_matches, observed
    return application_matches if stop_after_matching_application else [
        pair for pair in observed if matches_selector(pair)
    ], observed


def wait_for_widget(
    timeout: float, role: str, labels: list[str], expected_pid: int | None = None,
    *, accessible_id: str | None = None, window_name: str | None = None,
    absent: bool = False, checked: bool | None = None,
    application_index: int | None = None,
    supervised_root_pid: int | None = None,
) -> dict[str, Any]:
    """A unique match, or confirmed absence; errors are never disappearance."""
    deadline = time.monotonic() + timeout
    while True:
        matches, observed = _read_until_ready(
            lambda: _widget_matches(
                role, labels, expected_pid, max(0.01, deadline - time.monotonic()),
                accessible_id, window_name, require_sensitive=not absent,
                application_index=application_index,
                stop_after_matching_application=(application_index is not None and not absent),
                supervised_root_pid=supervised_root_pid,
            ), deadline,
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
    application_index: int | None = None,
    supervised_root_pid: int | None = None,
) -> dict[str, Any]:
    """Explicit AT action, not a proof of keyboard reachability.

    No focus teleportation fallback. The host's keyboard helper traverses
    normal focus and sends a key instead when testing keyboard operation.
    """
    found = wait_for_widget(
        timeout, role, labels, expected_pid,
        accessible_id=accessible_id, window_name=window_name,
        application_index=application_index,
        supervised_root_pid=supervised_root_pid,
    )
    if found["status"] != "passed":
        return found
    found_index = found.get("widget", {}).get("application_index", application_index)
    matches, _observed = _widget_matches(
        role, labels, expected_pid, 3, accessible_id, window_name,
        application_index=found_index, stop_after_matching_application=found_index is not None,
        supervised_root_pid=supervised_root_pid,
    )
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


def _widget_by_identity(
    window: Any,
    pid: int,
    window_name: str,
    target_identity: str,
    deadline: float,
    application_index: int | None = None,
    limit: int = _WIDGET_TREE_LIMIT,
) -> dict[str, Any] | None:
    """Locate one known control without reading semantics from every sibling."""
    _atspi, GLib = _atspi_import()
    queue = deque([window])
    seen: set[int] = set()
    references: list[Any] = []
    visited = 0
    while queue:
        if time.monotonic() > deadline:
            raise WalkTruncated(f"target identity search incomplete after {visited} nodes")
        node = queue.popleft()
        if node is None:
            raise ProbeError("target identity search encountered a missing child")
        identity = id(node)
        if identity in seen:
            continue
        if visited >= limit:
            raise WalkTruncated(f"target identity search incomplete after {visited} nodes")
        seen.add(identity)
        references.append(node)
        visited += 1
        runtime_identity = str(getattr(node, "path", ""))
        if runtime_identity == target_identity:
            record = _widget_record(node)
            record["pid"] = pid
            record["window"] = window_name
            if application_index is not None:
                record["application_index"] = application_index
            return record
        try:
            count = node.get_child_count()
            if count < 0:
                raise ProbeError("invalid child count in target identity search")
            for index in range(count):
                queue.append(node.get_child_at_index(index))
        except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError) as error:
            raise ProbeError(f"target identity search could not enumerate children: {error}") from error
    return None


def focused_widget(
    timeout: float,
    expected_pid: int | None = None,
    target_identity: str | None = None,
    application_index: int | None = None,
    supervised_root_pid: int | None = None,
) -> dict[str, Any]:
    """Observe keyboard focus without moving it or reading field values.

    Generic diagnostics preserve the strict exactly-one contract. When the
    caller already knows the target identity, scan the SHOWING tree lazily and
    return that target as soon as it is focused; otherwise return one observed
    fallback after a bounded look-ahead so keyboard traversal can continue.
    """
    deadline = time.monotonic() + timeout

    if target_identity is None:
        last_focused: list[dict[str, Any]] = []
        while True:
            pairs = _read_until_ready(
                lambda: _visible_widgets(
                    expected_pid, deadline, supervised_root_pid
                ),
                deadline,
            )
            focused = [
                record
                for _node, record in pairs
                if record.get("focused")
                and record.get("showing")
                and not record.get("defunct")
            ]
            last_focused = focused
            if len(focused) == 1:
                return {"status": "passed", "widget": focused[0], "complete": True}
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                candidates = [
                    {
                        "pid": record.get("pid"),
                        "role": str(record.get("role", ""))[:64],
                        "identity": str(record.get("identity", ""))[:256],
                    }
                    for record in last_focused[:8]
                ]
                roles = ", ".join(item["role"] for item in candidates) or "none"
                return {
                    "status": "failed",
                    "reason": "ambiguous" if last_focused else "not-found",
                    "complete": True,
                    "matches": len(last_focused),
                    "candidates": candidates,
                    "error": "expected exactly one focused control in the requested scope; "
                    f"observed roles: {roles}",
                }
            time.sleep(min(0.1, remaining))

    last_error: ProbeError | None = None
    while True:
        fallback: dict[str, Any] | None = None
        lookahead = 0
        target_seen = False
        try:
            allowed_pids = (
                _owned_process_scope(expected_pid, supervised_root_pid)
                if expected_pid is not None or supervised_root_pid is not None
                else None
            )
            preferred_observed = False
            for window, window_record in _window_records(
                deadline,
                allowed_pids,
                preferred_application_index=application_index,
                stop_after_preferred_match=application_index is not None,
            ):
                target = _widget_by_identity(
                    window,
                    window_record["pid"],
                    window_record["name"],
                    target_identity,
                    deadline,
                    application_index=window_record.get("application_index"),
                )
                if target is not None:
                    target_seen = True
                    if target.get("focused") and target.get("showing") and not target.get("defunct"):
                        return {"status": "passed", "widget": target, "complete": True}
                is_preferred = (
                    application_index is not None
                    and window_record.get("application_index") == application_index
                )
                # Once a PID-verified hinted application has been inspected,
                # unrelated providers cannot improve this focus observation.
                # Return its fallback (or retry until the shared deadline)
                # without walking the rest of the desktop registry.
                if preferred_observed and not is_preferred:
                    break
                if is_preferred:
                    preferred_observed = True
                for _node, record in _showing_widgets_in_window(
                    window,
                    window_record["pid"],
                    window_record["name"],
                    deadline,
                    application_index=window_record.get("application_index"),
                ):
                    if not record.get("focused") or record.get("defunct"):
                        continue
                    if record.get("identity") == target_identity:
                        return {"status": "passed", "widget": record, "complete": True}
                    if fallback is None:
                        fallback = record
                        lookahead = 24
                    else:
                        lookahead -= 1
                        if lookahead <= 0:
                            return {
                                "status": "passed",
                                "widget": fallback,
                                "complete": True,
                            }
            if fallback is not None:
                return {"status": "passed", "widget": fallback, "complete": True}
            if target_seen:
                return {
                    "status": "failed",
                    "reason": "target-not-focused",
                    "complete": True,
                    "matches": 0,
                    "error": "requested control is present but does not have keyboard focus",
                }
        except WalkTruncated:
            if target_seen:
                return {
                    "status": "failed",
                    "reason": "target-not-focused",
                    "complete": True,
                    "matches": 0,
                    "error": "requested control is present but does not have keyboard focus",
                }
            raise
        except ProbeError as error:
            last_error = error
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if last_error is not None:
                raise last_error
            return {
                "status": "failed",
                "reason": "not-found",
                "complete": True,
                "matches": 0,
                "candidates": [],
                "error": "focus was not published before the deadline",
            }
        time.sleep(min(0.1, remaining))


def _smoke_content(window: Any, deadline: float, limit: int = 256) -> dict[str, Any] | None:
    """Return the first useful visible semantic witness, without full audit."""
    Atspi, GLib = _atspi_import()
    exhausted = object()
    work = deque([(iter([window]), frozenset())])
    seen: set[int] = set()
    references: list[Any] = []
    visited = examined = 0
    missing_child = False
    while work:
        if time.monotonic() > deadline:
            # A caller may finish one complete empty scan and enter the next
            # polling iteration exactly as the shared deadline expires.  No
            # node was left unread in that new iteration, so this is confirmed
            # absence, not an incomplete tree.  Expiry after traversal starts
            # remains inconclusive and blocking.
            if visited == 0 and examined == 0:
                return None
            raise WalkTruncated("no accessible content found within the smoke deadline")
        iterator, ancestors = work.popleft()
        node = next(iterator, exhausted)
        if node is exhausted:
            continue
        work.append((iterator, ancestors))
        if examined >= limit * 4:
            raise WalkTruncated("smoke reference budget exhausted")
        examined += 1
        if node is None:
            missing_child = True
            continue
        identity = id(node)
        if identity in ancestors:
            raise WalkTruncated("cyclic accessibility tree")
        if identity in seen:
            continue
        if visited >= limit:
            raise WalkTruncated("no accessible content found within the smoke node budget")
        seen.add(identity)
        references.append(node)
        visited += 1
        if node is not window:
            try:
                state = node.get_state_set()
                showing = state.contains(Atspi.StateType.SHOWING)
                defunct = state.contains(Atspi.StateType.DEFUNCT)
            except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError) as error:
                raise ProbeError(f"could not read accessible content state: {error}") from error
            if not showing or defunct:
                continue
            try:
                role = node.get_role_name() or ""
                name = node.get_name() or ""
                text = node.get_text_iface()
                action = node.get_action_iface()
                value = node.get_value_iface()
                action_count = action.get_n_actions() if action is not None else 0
            except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError) as error:
                raise ProbeError(f"could not read accessible content semantics: {error}") from error
            useful = bool(text is not None or value is not None or action_count > 0 or name.strip())
            if useful and role.casefold() not in {"application", "frame", "window", "dialog", "panel", "filler"}:
                return {
                    "role": role,
                    "has_name": bool(name.strip()),
                    "text_interface": text is not None,
                    "action_interface": action_count > 0,
                    "value_interface": value is not None,
                    "nodes_visited": visited,
                }
        try:
            count = node.get_child_count()
        except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError) as error:
            raise ProbeError(f"could not enumerate accessible content: {error}") from error
        if count < 0:
            raise ProbeError("invalid child count in smoke query")
        work.append((map(node.get_child_at_index, range(count)), ancestors | {identity}))
    if missing_child:
        raise ProbeError("no content witness in an incomplete smoke tree")
    return None


def smoke_window(
    timeout: float,
    expected_pid: int,
    active_only: bool = False,
    application_index: int | None = None,
    window_identity: str | None = None,
    root_pid: int | None = None,
) -> dict[str, Any]:
    """Observe the launched application's window/content without moving focus."""
    Atspi, GLib = _atspi_import()
    deadline = time.monotonic() + timeout
    reason = "no accessible window/content for the launched application"
    last_scope: set[int] = set()

    def observe() -> dict[str, Any] | None:
        nonlocal reason, last_scope
        try:
            allowed_pids = _owned_process_scope(
                expected_pid, root_pid, (expected_pid,)
            )
            last_scope = allowed_pids
            for window, record in _window_records(
                deadline,
                allowed_pids,
                preferred_application_index=application_index,
                stop_after_preferred_match=application_index is not None,
                preferred_window_identity=window_identity,
            ):
                if record["pid"] not in allowed_pids:
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
                        return {
                            "status": "passed",
                            "pid": record["pid"],
                            "active": True,
                            "window_identity": record.get("identity", ""),
                            "window_role": record.get("role", ""),
                            "window_name": record.get("name", ""),
                            "application_window_count": record.get(
                                "application_window_count", 1
                            ),
                            "application_index": record.get("application_index"),
                        }
                    reason = "target window is not active; close shortcut was not sent"
                    continue
                evidence = _smoke_content(window, deadline)
                if evidence is not None:
                    return {
                        "status": "passed",
                        "pid": record["pid"],
                        "application_index": record.get("application_index"),
                        "window_identity": record.get("identity", ""),
                        "coverage": "accessible-content-present",
                        "evidence": evidence,
                    }
        except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError) as error:
            raise ProbeError(f"smoke query could not read the application: {error}") from error
        return None

    while True:
        result = _read_until_ready(observe, deadline)
        if result is not None:
            return result
        if _process_scope_exited(last_scope):
            return {"status": "failed", "error": "application exited before the smoke check"}
        if time.monotonic() >= deadline:
            return {"status": "failed", "error": reason}
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))


def _emit_ready(result: dict[str, Any]) -> None:
    encoded = (
        json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode().hex()
    )
    print(f"{READY_MARKER}{encoded}", flush=True)


def application_smoke_session(
    state_path: Path,
    open_timeout: float,
    expected_pid: int,
    root_pid: int,
    settle: float,
    content_timeout: float,
    close_timeout: float,
    close_mode: str,
) -> dict[str, Any]:
    """Run one bounded nonvisual smoke while retaining the provider proxy.

    Separate short-lived AT-SPI clients must rediscover the provider for every
    phase.  On a busy desktop, querying unrelated providers can exhaust the
    whole deadline even after the target window was already proven.  This
    operation discovers the PID-scoped window once, retains that exact object,
    confirms useful content and natural focus after the settle interval, then
    emits a readiness marker.  The host sends one normal keyboard shortcut and
    this same client observes the exact window/process outcome.
    """
    Atspi, GLib = _atspi_import()
    baseline = baseline_keys(state_path)
    started = time.monotonic()
    open_deadline = started + open_timeout
    target_window: Any | None = None
    target_record: dict[str, Any] | None = None
    last_scope: set[int] = set()

    def discover() -> tuple[Any, dict[str, Any]] | None:
        nonlocal last_scope
        last_scope = _owned_process_scope(expected_pid, root_pid)
        for window, record in _window_records(
            open_deadline, last_scope, include_window_state=True
        ):
            if record["pid"] not in last_scope:
                continue
            if record["key"] in baseline:
                continue
            if not record.get("showing", True) or record.get("defunct", False):
                continue
            if record.get("role") not in {"frame", "window", "dialog"}:
                continue
            if _is_transient_window(record):
                continue
            return window, record
        return None

    while time.monotonic() <= open_deadline:
        found = _read_until_ready(discover, open_deadline)
        if found is not None:
            target_window, target_record = found
            break
        if _process_scope_exited(last_scope):
            return {
                "status": "failed",
                "phase": "open",
                "error": "launch process exited before exposing an accessible window",
            }
        time.sleep(min(0.1, max(0.0, open_deadline - time.monotonic())))
    if target_window is None or target_record is None:
        return {
            "status": "failed",
            "phase": "open",
            "error": "accessible application window did not open before the deadline",
        }

    pid = int(target_record["pid"])
    identity = str(target_record.get("identity", ""))
    open_seconds = time.monotonic() - started

    # The settle interval is part of the requested smoke contract: a process
    # which publishes a window and immediately crashes must not pass.
    settle_deadline = time.monotonic() + settle
    while time.monotonic() < settle_deadline:
        scope = _owned_process_scope(expected_pid, root_pid, (pid,))
        if _process_scope_exited(scope):
            return {
                "status": "failed",
                "phase": "settle",
                "pid": pid,
                "window_identity": identity,
                "error": "application exited during the settle interval",
            }
        time.sleep(min(0.1, max(0.0, settle_deadline - time.monotonic())))

    content_deadline = time.monotonic() + content_timeout
    evidence: dict[str, Any] | None = None
    active = False
    while time.monotonic() <= content_deadline:
        scope = _owned_process_scope(expected_pid, root_pid, (pid,))
        if _process_scope_exited(scope):
            return {
                "status": "failed",
                "phase": "content",
                "pid": pid,
                "window_identity": identity,
                "error": "application exited before exposing accessible content",
            }
        try:
            states = target_window.get_state_set()
            showing = states.contains(Atspi.StateType.SHOWING)
            defunct = states.contains(Atspi.StateType.DEFUNCT)
            active = states.contains(Atspi.StateType.ACTIVE)
            if not showing or defunct:
                return {
                    "status": "failed",
                    "phase": "content",
                    "pid": pid,
                    "window_identity": identity,
                    "error": "application window disappeared before the smoke check",
                }
            evidence = _smoke_content(target_window, content_deadline)
        except WalkTruncated:
            raise
        except (ProbeError, GLib.Error, RuntimeError, AttributeError, TypeError, OSError):
            evidence = None
        if evidence is not None and active:
            break
        remaining = content_deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(0.1, remaining))

    if evidence is None:
        return {
            "status": "failed",
            "phase": "content",
            "pid": pid,
            "window_identity": identity,
            "error": "window did not expose useful accessible content before the deadline",
        }
    if not active:
        return {
            "status": "failed",
            "phase": "focus",
            "pid": pid,
            "window_identity": identity,
            "error": "target window was not naturally active before the close shortcut",
        }

    ready = {
        "status": "passed",
        "phase": "ready",
        "pid": pid,
        "application": target_record.get("application", ""),
        "window": target_record.get("name", ""),
        "role": target_record.get("role", ""),
        "accessible_children": target_record.get("children", 0),
        "application_index": target_record.get("application_index"),
        "window_identity": identity,
        "application_window_count": target_record.get("application_window_count", 1),
        "coverage": "accessible-content-present",
        "evidence": evidence,
        "active": True,
        "open_seconds": round(open_seconds, 2),
        "mem_available_mib": mem_available_mib(),
        "memory": process_memory(pid),
    }
    _emit_ready(ready)

    close_deadline = time.monotonic() + close_timeout
    last_error = ""
    while time.monotonic() <= close_deadline:
        scope = _owned_process_scope(expected_pid, root_pid, (pid,))
        process_gone = _process_scope_exited(scope)
        window_closed = process_gone
        if not window_closed:
            try:
                states = target_window.get_state_set()
                window_closed = (
                    not states.contains(Atspi.StateType.SHOWING)
                    or states.contains(Atspi.StateType.DEFUNCT)
                )
                last_error = ""
            except (GLib.Error, RuntimeError, AttributeError, TypeError, OSError) as error:
                # A transient provider error is not proof that the window
                # disappeared.  Keep observing until the original deadline.
                last_error = f"{type(error).__name__}: {error}"
        satisfied = process_gone if close_mode == "process-exit" else window_closed
        if satisfied:
            return {
                **ready,
                "phase": "closed",
                "process_gone": process_gone,
                "window_closed": window_closed,
                "graceful_exit": process_gone,
            }
        time.sleep(min(0.1, max(0.0, close_deadline - time.monotonic())))
    expectation = (
        "application process did not exit after its close shortcut"
        if close_mode == "process-exit"
        else "application window did not disappear after its close shortcut"
    )
    if last_error:
        expectation += f"; last provider error: {last_error}"
    return {
        **ready,
        "status": "failed",
        "phase": "close",
        "process_gone": False,
        "window_closed": False,
        "graceful_exit": False,
        "error": expectation,
    }


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
    for window, record in list(_window_records(deadline)):
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
            for _window, record in _window_records(deadline)
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
        # These PIDs come from arbitrary residual windows, not the supervised
        # launch root. Do not widen cleanup to their process groups: a desktop
        # service can share such a group with windows the test does not own.
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
            "smoke-session",
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
    parser.add_argument("--root-pid", type=int)
    parser.add_argument("--name")
    parser.add_argument("--index", type=int)
    parser.add_argument("--role")
    parser.add_argument("--labels", default="")
    parser.add_argument("--accessible-id")
    parser.add_argument("--window")
    parser.add_argument("--window-identity")
    parser.add_argument("--target-identity")
    parser.add_argument("--application-index", type=int)
    parser.add_argument("--checked", choices=("true", "false"))
    parser.add_argument("--no-memory-sample", action="store_true")
    parser.add_argument("--settle", type=float, default=2.0)
    parser.add_argument("--content-timeout", type=float, default=10.0)
    parser.add_argument("--close-timeout", type=float, default=15.0)
    parser.add_argument("--close-mode", choices=("process-exit", "window-close"), default="process-exit")
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
        if args.root_pid is not None and args.root_pid <= 1:
            raise ProbeError("root pid must be greater than one")
        if args.application_index is not None and args.application_index < 0:
            raise ProbeError("application index must be nonnegative")
        for field, value, maximum in (("settle", args.settle, 10), ("content timeout", args.content_timeout, 120), ("close timeout", args.close_timeout, 120)):
            if not math.isfinite(value) or value < 0 or value > maximum:
                raise ProbeError(f"{field} must be finite, nonnegative and at most {maximum} seconds")
        if args.operation == "baseline":
            result = save_baseline(args.state, args.timeout)
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
                expected_window_identity=args.window_identity,
                supervised_root_pid=args.root_pid,
            )
        elif args.operation == "focused-widget":
            result = focused_widget(
                args.timeout,
                args.pid,
                args.target_identity,
                args.application_index,
                args.root_pid,
            )
        elif args.operation == "smoke-session":
            if args.pid is None or args.root_pid is None:
                raise ProbeError("--pid and --root-pid are required for a smoke session")
            result = application_smoke_session(
                args.state,
                args.timeout,
                args.pid,
                args.root_pid,
                args.settle,
                args.content_timeout,
                args.close_timeout,
                args.close_mode,
            )
        elif args.operation in {"smoke-window", "active-window"}:
            if args.pid is None:
                raise ProbeError("--pid is required for window smoke checks")
            result = smoke_window(
                args.timeout,
                args.pid,
                args.operation == "active-window",
                args.application_index,
                args.window_identity,
                args.root_pid,
            )
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
                application_index=args.application_index,
                supervised_root_pid=args.root_pid,
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
                application_index=args.application_index,
                supervised_root_pid=args.root_pid,
            )
        elif args.operation == "dump-widgets":
            result = dump_widget_tree(
                args.pid if args.pid and args.pid > 1 else None, args.timeout
            )
        elif args.operation == "x11-wait-open":
            result = wait_for_x11_window(
                args.timeout, args.pid, args.name, args.root_pid
            )
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
