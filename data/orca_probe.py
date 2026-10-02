#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Observe Orca's real speech presenter; never manufacture expected speech.

Uses the upstream token-gated SetLogFileForTesting API after introspection.
An unsupported Orca is an inconclusive, blocking result, not an AT-SPI-only pass.
This adapter measures presenter output, NOT audible output or native activation.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import tempfile
import time
import unicodedata
import xml.etree.ElementTree as ET

SERVICE = "org.gnome.Orca1.Service"
ROOT = "/org/gnome/Orca1"
MAX_LOG_BYTES = 262144


class ObservationError(RuntimeError):
    pass


def normalized(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.findall(r"\w+", text))


def contains_phrase(text: str, phrase: str) -> bool:
    wanted = normalized(phrase)
    return bool(wanted) and f" {wanted} " in f" {normalized(text)} "


def presented_text(lines: bytes) -> str:
    """An interrupt invalidates earlier queued speech in this observation."""
    texts = []
    # A writer may still be appending the final record. Only consume full lines.
    for line in lines.split(b"\n")[:-1]:
        item = json.loads(line)
        if not isinstance(item, dict):
            raise ObservationError("Orca emitted a non-object record")
        if item.get("kind") == "interrupt":
            texts.clear()
        elif item.get("kind") == "speech":
            text = item.get("text")
            if not isinstance(text, str):
                raise ObservationError("Orca speech record has no string text")
            texts.append(text)
    return " ".join(texts)


def process_start(pid: int) -> str:
    # comm can contain spaces and parentheses; the fields follow the last ')'.
    return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]


def save_state(path: Path, value: dict) -> None:
    # Private and atomic; never follow a pre-existing final-path symlink.
    fd, temporary = tempfile.mkstemp(prefix=".orca-state-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_state(path: Path) -> dict:
    if path.is_symlink() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise ObservationError("Orca state must be private and owned by the test user")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ObservationError("invalid Orca state")
    return value


def find_recorder(introspect) -> tuple[str, str]:
    queue = [ROOT]
    visited = set()
    while queue and len(visited) < 80:
        path = queue.pop(0)
        if path in visited:
            continue
        visited.add(path)
        node = ET.fromstring(introspect(path))
        for interface in node.findall("interface"):
            name = interface.get("name", "")
            if name.rsplit(".", 1)[-1].replace("_", "").casefold() != "speechpresenter":
                continue
            method = interface.find("method[@name='SetLogFileForTesting']")
            if method is not None:
                incoming = [a.get("type") for a in method.findall("arg") if a.get("direction", "in") == "in"]
                outgoing = [a.get("type") for a in method.findall("arg") if a.get("direction") == "out"]
                if incoming != ["s", "s"] or outgoing != ["b"]:
                    raise ObservationError("unsupported Orca recorder signature")
                return path, name
        for child in node.findall("node"):
            name = child.get("name", "")
            if not re.fullmatch(r"[A-Za-z0-9_]+", name):
                raise ObservationError("invalid introspection child path")
            queue.append(path + "/" + name)
    raise ObservationError("Orca lacks token-gated speech recording; upgrade/validate its adapter")


def start(path: Path) -> dict:
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    if path.exists():
        raise ObservationError("an Orca observation session already exists; stop it first")
    runtime = Path(os.environ["XDG_RUNTIME_DIR"])
    private = Path(tempfile.mkdtemp(prefix="openqa-orca-", dir=runtime))
    speech = private / "speech.jsonl"
    token = secrets.token_hex(32)
    environment = dict(os.environ, ORCA_TEST_RPC_SECRET=token)
    with (private / "stderr.log").open("wb") as log:
        process = subprocess.Popen(["orca", "--replace"], env=environment,
                                   stdout=log, stderr=log, start_new_session=True)
    state = {"pid": process.pid, "start": process_start(process.pid),
             "speech": str(speech), "instrumented": True}
    save_state(path, state)  # Ensure stop can clean up even after a failed attach.
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def call(obj, interface, method, arguments=None):
        return bus.call_sync(SERVICE, obj, interface, method, arguments, None,
                             Gio.DBusCallFlags.NONE, 2000, None).unpack()

    deadline = time.monotonic() + 20
    last_error = "Orca did not publish its recorder"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise ObservationError("Orca exited before exposing its recorder")
        try:
            obj, interface = find_recorder(lambda p: call(p, "org.freedesktop.DBus.Introspectable", "Introspect")[0])
            accepted = call(obj, interface, "SetLogFileForTesting", GLib.Variant("(ss)", (token, str(speech))))
            if accepted != (True,):
                raise ObservationError("Orca rejected presenter recording")
            info = speech.stat()
            state.update(inode=info.st_ino, device=info.st_dev, offset=info.st_size)
            save_state(path, state)
            return {"status": "passed", "coverage": "presenter-capture-ready", "instrumented": True}
        except (GLib.Error, ObservationError, OSError) as error:
            last_error = str(error)
            time.sleep(0.25)
    raise ObservationError(last_error)


def mark(path: Path) -> dict:
    state = read_state(path)
    speech = Path(state["speech"])
    info = speech.stat()
    if process_start(state["pid"]) != state["start"]:
        raise ObservationError("Orca process identity changed")
    if (info.st_dev, info.st_ino) != (state["device"], state["inode"]):
        raise ObservationError("Orca speech stream was replaced")
    state["offset"] = info.st_size
    with speech.open("rb") as stream:
        if info.st_size:
            stream.seek(info.st_size - 1)
        state["skip_partial"] = bool(info.st_size and stream.read(1) != b"\n")
    save_state(path, state)
    return {"status": "passed", "offset": info.st_size}


def check(path: Path, phrase: str, timeout: float) -> dict:
    if not normalized(phrase):
        raise ObservationError("a nonempty expected phrase is required")
    state = read_state(path)
    deadline = time.monotonic() + timeout
    speech = Path(state["speech"])
    last_size = -1
    changed = time.monotonic()
    while True:
        if process_start(state["pid"]) != state["start"]:
            raise ObservationError("Orca process identity changed")
        with speech.open("rb") as stream:
            info = os.fstat(stream.fileno())
            if (info.st_dev, info.st_ino) != (state["device"], state["inode"]) or info.st_size < state["offset"]:
                raise ObservationError("Orca speech stream was replaced or truncated")
            stream.seek(state["offset"])
            raw = stream.read(MAX_LOG_BYTES + 1)
        if len(raw) > MAX_LOG_BYTES:
            raise ObservationError("Orca speech observation exceeded its byte budget")
        if len(raw) != last_size:
            last_size, changed = len(raw), time.monotonic()
        if state.get("skip_partial"):
            raw = raw.partition(b"\n")[2]
        if contains_phrase(presented_text(raw), phrase) and time.monotonic() - changed >= 0.3:
            return {"status": "passed", "coverage": "speech-presenter", "expected": phrase,
                    "audible_output": "not-tested", "native_activation": "not-tested"}
        if time.monotonic() >= deadline:
            return {"status": "failed", "error": "expected information was not presented by Orca"}
        time.sleep(0.1)


def stop(path: Path) -> dict:
    if not path.exists():
        return {"status": "passed"}
    state = read_state(path)
    try:
        if process_start(state["pid"]) == state["start"]:
            os.kill(state["pid"], signal.SIGTERM)
    except FileNotFoundError:
        pass
    # Keep logs inside the disposable guest, not in uploaded password artifacts.
    path.unlink()
    return {"status": "passed"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("start", "mark", "check", "stop"))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--phrase", default="")
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args()
    try:
        if not 0 <= args.timeout <= 120:
            raise ObservationError("invalid timeout")
        result = check(args.state, args.phrase, args.timeout) if args.operation == "check" else globals()[args.operation](args.state)
    except (ObservationError, OSError, ValueError, KeyError, ImportError) as error:
        result = {"status": "inconclusive", "error": str(error)}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
