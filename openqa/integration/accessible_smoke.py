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


def application(mode: str) -> None:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib
    window = Gtk.Window(title="Synthetic accessible smoke " + mode)
    window.set_default_size(360, 180)
    if mode != "empty":
        window.add(Gtk.Entry(text="Accessible content for smoke integration"))
    window.connect("destroy", Gtk.main_quit)
    window.show_all()
    if mode == "crash":
        import signal
        GLib.timeout_add(3000, lambda: os.kill(os.getpid(), signal.SIGSEGV))
    Gtk.main()


def probe(operation: str, state: Path, pid: int | None = None, timeout: int = 8) -> dict:
    args = [sys.executable, str(PROBE), operation, "--state", str(state), "--timeout", str(timeout)]
    if pid is not None:
        args += ["--pid", str(pid)]
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout + 20)
    lines = [line[len(MARKER):] for line in result.stdout.splitlines() if line.startswith(MARKER)]
    if len(lines) != 1:
        raise RuntimeError(f"probe {operation} returned no coherent record: {result.stderr}")
    return json.loads(bytes.fromhex(lines[0]))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def run() -> None:
    # The window manager supplies the ordinary Alt+F4 path; no forced focus,
    # coordinates, accessibility action, or screenshots are used for approval.
    manager = subprocess.Popen(["openbox"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    results = []
    try:
        time.sleep(0.5)
        with tempfile.TemporaryDirectory() as temporary:
            for mode in ("normal", "empty", "crash"):
                state = Path(temporary) / (mode + ".json")
                probe("baseline", state)
                with (Path(temporary) / (mode + ".log")).open("w") as log:
                    process = subprocess.Popen([sys.executable, __file__, "app", mode], stdout=log, stderr=log)
                    try:
                        opened = probe("wait-open", state, process.pid)
                        check(opened.get("status") == "passed", f"{mode}: own accessible window missing: {opened}")
                        if mode == "crash":
                            code = process.wait(timeout=8)
                            check(code == -11, f"expected SIGSEGV, got {code}")
                            content = probe("smoke-window", state, process.pid, 1)
                            check(content.get("status") != "passed", "crashed app passed accessibility smoke")
                            results.append({"case": mode, "status": "passed", "application_exit": 139})
                            continue
                        content = probe("smoke-window", state, process.pid, 2)
                        check((content.get("status") == "passed") == (mode == "normal"),
                              f"{mode}: unexpected content result: {content}")
                        active = probe("active-window", state, process.pid)
                        check(active.get("active") is True, f"{mode}: window did not naturally gain focus: {active}")
                        subprocess.run(["xdotool", "key", "--clearmodifiers", "alt+F4"], check=True, timeout=5)
                        code = process.wait(timeout=8)
                        check(code == 0, f"{mode}: shortcut did not close without errors: {code}")
                        results.append({"case": mode, "status": "passed", "application_exit": 0,
                                        "accessible_content": content.get("status") == "passed"})
                    finally:
                        if process.poll() is None:
                            process.kill()  # Isolation only, after an exception has failed the check.
                            process.wait(timeout=5)
    finally:
        manager.terminate()
        manager.wait(timeout=5)
    print(json.dumps({"scope": "real GTK fixture, AT-SPI and keyboard; no ISO", "cases": results}, indent=2))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "app":
        application(sys.argv[2])
    else:
        run()
