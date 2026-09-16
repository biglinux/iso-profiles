#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real GTK/AT-SPI/keyboard integration in an isolated Xvfb session, not an ISO."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "data/atspi_probe.py"
MARKER = "__OPENQA_ATSPI__"


def application(mode: str, trigger: str = "") -> None:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib
    window = Gtk.Window(title="Synthetic accessible smoke " + mode)
    window.set_default_size(360, 180)
    if mode not in {"empty", "delayed"}:
        window.add(Gtk.Entry(text="Accessible content for smoke integration"))
    window.connect("destroy", Gtk.main_quit)
    window.show_all()
    if mode == "delayed":
        def publish_content():
            window.add(Gtk.Entry(text="Content published after the probe started waiting"))
            window.show_all()
            return False

        def await_request():
            if not Path(trigger).exists():
                return True
            GLib.timeout_add(2000, publish_content)
            return False

        GLib.timeout_add(50, await_request)
    if mode == "crash":
        import signal
        GLib.timeout_add(3000, lambda: os.kill(os.getpid(), signal.SIGSEGV))
    Gtk.main()


def probe(
    operation: str,
    state: Path,
    pid: int | None = None,
    timeout: int = 8,
    extra: tuple[str, ...] = (),
) -> dict:
    args = [
        sys.executable,
        str(PROBE),
        operation,
        "--state",
        str(state),
        "--timeout",
        str(timeout),
    ]
    if pid is not None:
        args += ["--pid", str(pid)]
    args += list(extra)
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout + 20)
    lines = [line[len(MARKER):] for line in result.stdout.splitlines() if line.startswith(MARKER)]
    if len(lines) != 1:
        raise RuntimeError(f"probe {operation} returned no coherent record: {result.stderr}")
    return json.loads(bytes.fromhex(lines[0]))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def detached_launcher(pid_file: str) -> None:
    """Spawn the GTK fixture in this new session, then let it be re-parented."""
    child = subprocess.Popen(
        [sys.executable, __file__, "app", "normal"],
        close_fds=True,
    )
    Path(pid_file).write_text(str(child.pid), encoding="ascii")


def wait_process_gone(pid: int, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    status = Path(f"/proc/{pid}/status")
    while time.monotonic() < deadline:
        try:
            text = status.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return True
        except OSError:
            text = ""
        for line in text.splitlines():
            if line.startswith("State:"):
                fields = line.split()
                if len(fields) > 1 and fields[1] == "Z":
                    return True
        time.sleep(0.05)
    return not status.exists()


def run() -> None:
    # The window manager supplies the ordinary Alt+F4 path; no forced focus,
    # coordinates, accessibility action, or screenshots are used for approval.
    manager = subprocess.Popen(["openbox"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    results = []
    try:
        time.sleep(0.5)
        with tempfile.TemporaryDirectory() as temporary:
            for mode in ("normal", "empty", "delayed", "crash"):
                state = Path(temporary) / (mode + ".json")
                probe("baseline", state)
                with (Path(temporary) / (mode + ".log")).open("w") as log:
                    trigger = Path(temporary) / (mode + "-publish")
                    process = subprocess.Popen(
                        [sys.executable, __file__, "app", mode, str(trigger)],
                        stdout=log,
                        stderr=log,
                    )
                    try:
                        opened = probe("wait-open", state, process.pid)
                        check(
                            opened.get("status") == "passed",
                            f"{mode}: own accessible window missing: {opened}",
                        )
                        if mode == "crash":
                            code = process.wait(timeout=8)
                            check(code == -11, f"expected SIGSEGV, got {code}")
                            content = probe("smoke-window", state, process.pid, 1)
                            check(
                                content.get("status") != "passed",
                                "crashed app passed accessibility smoke",
                            )
                            results.append(
                                {"case": mode, "status": "passed", "application_exit": 139}
                            )
                            continue
                        if mode == "delayed":
                            before = probe("smoke-window", state, process.pid, 1)
                            check(before.get("status") != "passed", "empty initial window passed")
                            trigger.touch()
                        content = probe(
                            "smoke-window",
                            state,
                            process.pid,
                            8 if mode == "delayed" else 2,
                        )
                        check(
                            (content.get("status") == "passed")
                            == (mode in {"normal", "delayed"}),
                            f"{mode}: unexpected content result: {content}",
                        )
                        active = probe("active-window", state, process.pid)
                        check(
                            active.get("active") is True,
                            f"{mode}: window did not naturally gain focus: {active}",
                        )
                        subprocess.run(
                            ["xdotool", "key", "--clearmodifiers", "alt+F4"],
                            check=True,
                            timeout=5,
                        )
                        code = process.wait(timeout=8)
                        check(code == 0, f"{mode}: shortcut did not close without errors: {code}")
                        results.append({"case": mode, "status": "passed", "application_exit": 0,
                                        "accessible_content": content.get("status") == "passed"})
                    finally:
                        if process.poll() is None:
                            # Isolation only, after an exception has failed the check.
                            process.kill()
                            process.wait(timeout=5)

            # Real ownership regression: the supervised group leader exits after
            # spawning the GUI. Parent traversal can no longer find the window,
            # but the application remains in the launcher's process group.
            state = Path(temporary) / "reparented.json"
            pid_file = Path(temporary) / "reparented.pid"
            probe("baseline", state)
            with (Path(temporary) / "reparented.log").open("w") as log:
                launcher = subprocess.Popen(
                    [sys.executable, __file__, "launcher", str(pid_file)],
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
                root_pid = launcher.pid
                child_pid = 0
                try:
                    check(
                        launcher.wait(timeout=5) == 0,
                        "reparented: launcher did not exit cleanly",
                    )
                    deadline = time.monotonic() + 5
                    while not pid_file.exists() and time.monotonic() < deadline:
                        time.sleep(0.05)
                    check(pid_file.exists(), "reparented: launcher did not publish the child PID")
                    child_pid = int(pid_file.read_text(encoding="ascii"))
                    check(os.getpgid(child_pid) == root_pid,
                          "reparented: GTK child left the supervised process group")
                    opened = probe(
                        "wait-open",
                        state,
                        root_pid,
                        8,
                        ("--root-pid", str(root_pid)),
                    )
                    check(opened.get("status") == "passed",
                          f"reparented: process-group window missing: {opened}")
                    check(opened.get("pid") == child_pid,
                          f"reparented: wrong window owner: {opened}")
                    extra = ["--root-pid", str(root_pid)]
                    if opened.get("application_index") is not None:
                        extra += ["--application-index", str(opened["application_index"])]
                    if opened.get("window_identity"):
                        extra += ["--window-identity", str(opened["window_identity"])]
                    content = probe("smoke-window", state, child_pid, 4, tuple(extra))
                    check(content.get("status") == "passed",
                          f"reparented: accessible content not retained: {content}")
                    active = probe("active-window", state, child_pid, 4, tuple(extra))
                    check(active.get("active") is True,
                          f"reparented: target window was not active: {active}")
                    subprocess.run(
                        ["xdotool", "key", "--clearmodifiers", "alt+F4"],
                        check=True,
                        timeout=5,
                    )
                    check(wait_process_gone(child_pid),
                          "reparented: normal close did not end the GTK child")
                    closed = probe(
                        "wait-close",
                        state,
                        child_pid,
                        4,
                        (
                            "--root-pid",
                            str(root_pid),
                            "--window-identity",
                            str(opened["window_identity"]),
                        ),
                    )
                    check(closed.get("status") == "passed",
                          f"reparented: exact window close was not observed: {closed}")
                    results.append({
                        "case": "reparented-process-group",
                        "status": "passed",
                        "application_exit": 0,
                        "accessible_content": True,
                    })
                finally:
                    if child_pid and not wait_process_gone(child_pid, 0.1):
                        try:
                            os.kill(child_pid, 9)
                        except ProcessLookupError:
                            pass
    finally:
        manager.terminate()
        manager.wait(timeout=5)
    print(
        json.dumps(
            {
                "scope": "real GTK fixture, AT-SPI and keyboard; no ISO",
                "cases": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    if len(sys.argv) in {3, 4} and sys.argv[1] == "app":
        application(sys.argv[2], sys.argv[3] if len(sys.argv) == 4 else "")
    elif len(sys.argv) == 3 and sys.argv[1] == "launcher":
        detached_launcher(sys.argv[2])
    else:
        run()
