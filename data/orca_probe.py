#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Observe what Orca says, through the speech-dispatcher protocol.

Orca speaks through speech-dispatcher over SSIP, a line-based text protocol,
and has no test hook of its own. A proxy between the two records every SPEAK,
CHAR and KEY Orca sends and every error speech-dispatcher answers. That proves
Orca produced speech and speech-dispatcher accepted it; audible output and
braille are not observed.

Operations: start (proxy, then Orca pointed at it), offset (mark before an
action), check (speech since a mark), stop.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import threading
import time
import unicodedata

RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
DIRECTORY = RUNTIME / "openqa-orca"
PROXY_SOCKET = DIRECTORY / "proxy.sock"
SPEECH_LOG = DIRECTORY / "speech.jsonl"
SPEECHD_SOCKET = RUNTIME / "speech-dispatcher" / "speechd.sock"
UNITS = ("openqa-orca", "openqa-speech-proxy")
MAX_LOG_BYTES = 1 << 20
# The marker openqa/lib/atspi.pm reads a probe's JSON answer from.
RESULT_MARKER = "__OPENQA_ATSPI__"
# Orca sends SSML; only the words matter here.
SSML_TAG = re.compile(r"<[^>]*>")
# SSIP replies: 2xx success, 3xx server error, 4xx client error, 5xx syntax.
ERROR_REPLY = re.compile(rb"^([345][0-9][0-9])[ -](.*)$")


class ObservationError(RuntimeError):
    pass


def normalized(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.findall(r"\w+", text))


def contains_phrase(text: str, phrase: str) -> bool:
    wanted = normalized(phrase)
    return bool(wanted) and f" {wanted} " in f" {normalized(text)} "


class ClientStream:
    """Turn the client side of an SSIP connection into speech records."""

    def __init__(self) -> None:
        self.pending = b""
        self.text: list[str] | None = None

    def feed(self, data: bytes) -> list[dict[str, str]]:
        self.pending += data
        records = []
        while b"\r\n" in self.pending:
            line, self.pending = self.pending.split(b"\r\n", 1)
            decoded = line.decode("utf-8", "replace")
            if self.text is not None:
                if decoded == ".":
                    text = SSML_TAG.sub("", "\n".join(self.text))
                    records.append({"kind": "speech", "text": text})
                    self.text = None
                else:
                    # A data line starting with a dot is sent with it doubled.
                    self.text.append(decoded[1:] if decoded.startswith("..") else decoded)
                continue
            command, _, argument = decoded.partition(" ")
            if command.upper() == "SPEAK":
                self.text = []
            elif command.upper() in {"CHAR", "KEY"}:
                records.append({"kind": "speech", "text": argument})
        return records


class ServerStream:
    """Turn the server side of an SSIP connection into error records."""

    def __init__(self) -> None:
        self.pending = b""

    def feed(self, data: bytes) -> list[dict[str, str]]:
        self.pending += data
        records = []
        while b"\r\n" in self.pending:
            line, self.pending = self.pending.split(b"\r\n", 1)
            match = ERROR_REPLY.match(line)
            if match:
                records.append({"kind": "error", "reply": line.decode("utf-8", "replace")})
        return records


def records_since(offset: int) -> list[dict[str, str]]:
    with SPEECH_LOG.open("rb") as stream:
        stream.seek(offset)
        raw = stream.read(MAX_LOG_BYTES)
    # The proxy may still be writing the last line.
    return [json.loads(line) for line in raw.split(b"\n")[:-1] if line]


def _connect_upstream() -> socket.socket:
    for attempt in range(2):
        upstream = socket.socket(socket.AF_UNIX)
        try:
            upstream.connect(str(SPEECHD_SOCKET))
            return upstream
        except OSError:
            upstream.close()
            if attempt:
                raise
            # What the speech-dispatcher client library does when no server runs.
            subprocess.run(["speech-dispatcher", "--spawn"], check=False, timeout=10,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    raise AssertionError("unreachable")


def proxy() -> None:
    lock = threading.Lock()
    log = SPEECH_LOG.open("a", encoding="utf-8")

    def write(records: list[dict[str, str]]) -> None:
        with lock:
            for record in records:
                log.write(json.dumps(record, ensure_ascii=False) + "\n")
            log.flush()

    def pump(source: socket.socket, target: socket.socket, stream: ClientStream | ServerStream) -> None:
        try:
            while data := source.recv(65536):
                target.sendall(data)
                write(stream.feed(data))
        except OSError:
            pass
        finally:
            for side in (source, target):
                try:
                    side.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    PROXY_SOCKET.unlink(missing_ok=True)
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(PROXY_SOCKET))
    os.chmod(PROXY_SOCKET, 0o600)
    listener.listen(8)
    while True:
        client, _address = listener.accept()
        try:
            upstream = _connect_upstream()
        except OSError as error:
            write([{"kind": "error", "reply": f"speech-dispatcher unreachable: {error}"}])
            client.close()
            continue
        write([{"kind": "client"}])
        threading.Thread(target=pump, args=(client, upstream, ClientStream()), daemon=True).start()
        threading.Thread(target=pump, args=(upstream, client, ServerStream()), daemon=True).start()


def _systemd_run(unit: str, *command: str) -> None:
    subprocess.run(["systemd-run", "--user", "--quiet", "--collect", f"--unit={unit}", *command],
                   check=True, timeout=15)


def stop() -> dict:
    subprocess.run(["systemctl", "--user", "stop", *UNITS], check=False, timeout=15,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"status": "passed"}


def start(timeout: float) -> dict:
    stop()
    DIRECTORY.mkdir(mode=0o700, exist_ok=True)
    SPEECH_LOG.unlink(missing_ok=True)
    SPEECH_LOG.touch(mode=0o600)
    _systemd_run(UNITS[1], "python3", str(Path(__file__).resolve()), "proxy")
    deadline = time.monotonic() + timeout
    while not PROXY_SOCKET.exists():
        if time.monotonic() > deadline:
            raise ObservationError("the speech proxy did not start")
        time.sleep(0.1)
    # The user manager's environment is the session's: Orca reaches the same
    # display and accessibility bus the desktop applications use.
    _systemd_run(UNITS[0], f"--setenv=SPEECHD_ADDRESS=unix_socket:{PROXY_SOCKET}",
                 "orca", "--replace")
    while time.monotonic() < deadline:
        records = records_since(0)
        errors = [record["reply"] for record in records if record["kind"] == "error"]
        if errors:
            raise ObservationError(f"speech-dispatcher refused Orca: {errors[0]}")
        if any(record["kind"] == "client" for record in records):
            return {"status": "passed", "offset": SPEECH_LOG.stat().st_size}
        time.sleep(0.2)
    raise ObservationError("Orca did not connect to speech-dispatcher")


# Orca announces in bursts. A mark taken while it still speaks about the
# previous window would count that speech for the next one.
QUIET_SECONDS = 0.7


def offset(timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    size = SPEECH_LOG.stat().st_size
    quiet_since = time.monotonic()
    while time.monotonic() - quiet_since < QUIET_SECONDS:
        if time.monotonic() > deadline:
            raise ObservationError("Orca did not fall silent before the next action")
        time.sleep(0.1)
        current = SPEECH_LOG.stat().st_size
        if current != size:
            size, quiet_since = current, time.monotonic()
    return {"status": "passed", "offset": size}


def check(since: int, phrase: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        records = records_since(since)
        errors = [record["reply"] for record in records if record["kind"] == "error"]
        if errors:
            return {"status": "failed", "error": f"speech-dispatcher refused Orca's speech: {errors[0]}"}
        spoken = " ".join(record["text"] for record in records if record["kind"] == "speech")
        if spoken.strip() and (not phrase or contains_phrase(spoken, phrase)):
            return {"status": "passed", "coverage": "speech-dispatcher",
                    "audible_output": "not-tested"}
        if time.monotonic() >= deadline:
            return {"status": "failed",
                    "error": "Orca said nothing" if not spoken.strip()
                    else "Orca did not say the expected information"}
        time.sleep(0.1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("start", "offset", "check", "stop", "proxy"))
    parser.add_argument("--since", type=int, default=0)
    parser.add_argument("--phrase", default="")
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args()
    if args.operation == "proxy":
        proxy()
        return 0
    try:
        if not 0 <= args.timeout <= 120 or args.since < 0:
            raise ObservationError("invalid timeout or offset")
        if args.operation == "start":
            result = start(args.timeout)
        elif args.operation == "check":
            result = check(args.since, args.phrase, args.timeout)
        else:
            result = offset(args.timeout) if args.operation == "offset" else stop()
    except (ObservationError, OSError, ValueError, subprocess.SubprocessError) as error:
        result = {"status": "inconclusive", "error": str(error)}
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode().hex()
    print(f"{RESULT_MARKER}{encoded}", flush=True)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
