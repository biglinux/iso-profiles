#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real GTK/AT-SPI/keyboard integration in an isolated Xvfb session, not an ISO."""
from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "data/atspi_probe.py"
PROCESS_HANDOFF = ROOT / "data/process_handoff.py"
MARKER = "__OPENQA_ATSPI__"
READY_MARKER = "__OPENQA_ATSPI_READY__"
PROCESS_MARKER = "__OPENQA_PROCESS__"


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


def _decode_marker(line: str, marker: str) -> dict | None:
    if not line.startswith(marker):
        return None
    payload = line[len(marker):].strip()
    try:
        decoded = json.loads(bytes.fromhex(payload))
    except (ValueError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"invalid {marker} record: {error}") from error
    if not isinstance(decoded, dict):
        raise RuntimeError(f"invalid {marker} record type")
    return decoded


def persistent_smoke(
    state: Path,
    pid: int,
    root_pid: int,
    *,
    close_mode: str = "process-exit",
    open_timeout: float = 8.0,
    settle: float = 0.2,
    content_timeout: float = 6.0,
    close_timeout: float = 8.0,
    close_key: str = "alt+F4",
    after_start=None,
) -> tuple[dict | None, dict]:
    """Run the two-phase persistent probe and send one key only after READY."""
    command = [
        sys.executable,
        str(PROBE),
        "smoke-session",
        "--state",
        str(state),
        "--timeout",
        str(open_timeout),
        "--pid",
        str(pid),
        "--root-pid",
        str(root_pid),
        "--settle",
        str(settle),
        "--content-timeout",
        str(content_timeout),
        "--close-timeout",
        str(close_timeout),
        "--close-mode",
        close_mode,
    ]
    session = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    if after_start is not None:
        after_start()
    ready: dict | None = None
    final: dict | None = None
    output: list[str] = []
    deadline = time.monotonic() + open_timeout + settle + content_timeout + close_timeout + 15
    selector = selectors.DefaultSelector()
    assert session.stdout is not None
    selector.register(session.stdout, selectors.EVENT_READ)
    try:
        while time.monotonic() < deadline:
            events = selector.select(timeout=min(0.2, max(0.0, deadline - time.monotonic())))
            if not events:
                if session.poll() is not None:
                    break
                continue
            line = session.stdout.readline()
            if line == "":
                if session.poll() is not None:
                    break
                continue
            output.append(line.rstrip("\n"))
            candidate_ready = _decode_marker(line, READY_MARKER)
            if candidate_ready is not None:
                check(ready is None, "persistent smoke emitted readiness more than once")
                ready = candidate_ready
                subprocess.run(
                    ["xdotool", "key", "--clearmodifiers", close_key],
                    check=True,
                    timeout=5,
                )
                continue
            candidate_final = _decode_marker(line, MARKER)
            if candidate_final is not None:
                check(final is None, "persistent smoke emitted a final result more than once")
                final = candidate_final
                break
        try:
            return_code = session.wait(timeout=5)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("persistent smoke probe did not terminate") from error
        stderr = session.stderr.read() if session.stderr is not None else ""
        check(final is not None, f"persistent smoke returned no final record: {output}; {stderr}")
        expected_code = 0 if final.get("status") in {None, "passed"} else 1
        check(
            return_code == expected_code,
            f"persistent smoke probe exited {return_code}, expected {expected_code}: "
            f"output={output}; stderr={stderr}",
        )
        return ready, final
    finally:
        selector.close()
        if session.poll() is None:
            session.kill()
            session.wait(timeout=5)


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



def privileged_handoff(temporary: Path) -> dict:
    """Prove exact root process discovery without relying on ancestry or title."""
    token = f"openqa-integration-{os.getpid()}-{time.time_ns()}"
    trigger = temporary / "privileged-handoff.done"
    code = (
        "from pathlib import Path\n"
        "import sys,time\n"
        "p=Path(sys.argv[1])\n"
        "while not p.exists():\n"
        "    time.sleep(0.05)\n"
    )
    target = subprocess.Popen(
        [
            "sudo", "-n", "--", "env", f"DESKTOP_STARTUP_ID={token}",
            sys.executable, "-c", code, str(trigger),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        completed = subprocess.run(
            [
                "sudo", "-n", "--", sys.executable, str(PROCESS_HANDOFF),
                "--timeout", "8",
                "--executable", sys.executable,
                "--uid", "0",
                "--environment-name", "DESKTOP_STARTUP_ID",
                "--environment-value", token,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        records = [
            line[len(PROCESS_MARKER):]
            for line in completed.stdout.splitlines()
            if line.startswith(PROCESS_MARKER)
        ]
        check(completed.returncode == 0 and len(records) == 1,
              f"privileged handoff returned no coherent record: {completed.stderr}")
        result = json.loads(bytes.fromhex(records[0]))
        check(result.get("status") == "passed",
              f"privileged handoff did not find the exact process: {result}")
        check(result.get("uid") == 0 and result.get("pid", 0) > 1,
              f"privileged handoff returned an invalid identity: {result}")
        trigger.touch()
        check(target.wait(timeout=8) == 0,
              "privileged handoff fixture did not exit cleanly")
        return {
            "case": "privileged-executable-token-handoff",
            "status": "passed",
            "application_exit": 0,
            "resolved_pid": result["pid"],
        }
    finally:
        trigger.touch(exist_ok=True)
        if target.poll() is None:
            target.terminate()
            try:
                target.wait(timeout=3)
            except subprocess.TimeoutExpired:
                target.kill()
                target.wait(timeout=3)

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

            # Exercise the production two-phase protocol with one long-lived
            # AT-SPI client. The exact provider/window object discovered before
            # READY must be the one observed after the keyboard close request.
            for mode in ("normal", "empty", "delayed", "crash"):
                state = Path(temporary) / ("persistent-" + mode + ".json")
                trigger = Path(temporary) / ("persistent-" + mode + "-publish")
                probe("baseline", state)
                with (Path(temporary) / ("persistent-" + mode + ".log")).open("w") as log:
                    process = subprocess.Popen(
                        [sys.executable, __file__, "app", mode, str(trigger)],
                        stdout=log,
                        stderr=log,
                    )
                    try:
                        ready, final = persistent_smoke(
                            state,
                            process.pid,
                            process.pid,
                            settle=4.0 if mode == "crash" else 0.2,
                            content_timeout=8 if mode == "delayed" else 3,
                            after_start=trigger.touch if mode == "delayed" else None,
                        )
                        if mode in {"normal", "delayed"}:
                            check(ready is not None, f"persistent {mode}: no readiness record")
                            check(final.get("status") == "passed",
                                  f"persistent {mode}: close failed: {final}")
                            check(final.get("process_gone") is True,
                                  f"persistent {mode}: process exit not observed: {final}")
                            code = process.wait(timeout=8)
                            check(code == 0, f"persistent {mode}: application exit was {code}")
                        elif mode == "empty":
                            check(ready is None, "persistent empty window requested a close key")
                            check(final.get("status") == "failed"
                                  and final.get("phase") == "content",
                                  f"persistent empty window was not rejected: {final}")
                        else:
                            check(ready is None, "persistent crash requested a close key")
                            code = process.wait(timeout=8)
                            check(code == -11, f"persistent crash exit was {code}")
                            check(final.get("status") != "passed",
                                  f"persistent crash passed: {final}")
                        results.append({
                            "case": "persistent-" + mode,
                            "status": "passed",
                            "application_exit": 139 if mode == "crash" else 0,
                            "ready": ready is not None,
                        })
                    finally:
                        if process.poll() is None:
                            process.kill()
                            process.wait(timeout=5)

            # Persistent ownership after reparenting: the leader is gone, but
            # the GTK process remains in the explicitly supervised process group.
            state = Path(temporary) / "persistent-reparented.json"
            pid_file = Path(temporary) / "persistent-reparented.pid"
            probe("baseline", state)
            with (Path(temporary) / "persistent-reparented.log").open("w") as log:
                launcher = subprocess.Popen(
                    [sys.executable, __file__, "launcher", str(pid_file)],
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
                root_pid = launcher.pid
                child_pid = 0
                try:
                    check(launcher.wait(timeout=5) == 0,
                          "persistent reparented launcher did not exit cleanly")
                    deadline = time.monotonic() + 5
                    while not pid_file.exists() and time.monotonic() < deadline:
                        time.sleep(0.05)
                    check(pid_file.exists(), "persistent reparented child PID was not published")
                    child_pid = int(pid_file.read_text(encoding="ascii"))
                    ready, final = persistent_smoke(state, root_pid, root_pid)
                    check(ready is not None and ready.get("pid") == child_pid,
                          f"persistent reparented window owner was wrong: {ready}")
                    check(final.get("status") == "passed"
                          and final.get("process_gone") is True,
                          f"persistent reparented close failed: {final}")
                    check(wait_process_gone(child_pid),
                          "persistent reparented GTK process remained alive")
                    results.append({
                        "case": "persistent-reparented-process-group",
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

            results.append(privileged_handoff(Path(temporary)))
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
