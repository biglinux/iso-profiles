# SPDX-License-Identifier: GPL-2.0-or-later
from pathlib import Path
import os
import tempfile
import unittest
from unittest import mock

import process_handoff as handoff


def stat_record(pid: int, start: int, name: str = "calamares (root)") -> str:
    # pid, comm, state, ppid, pgrp, session, tty_nr, tpgid, flags,
    # minflt, cminflt, majflt, cmajflt, utime, stime, cutime, cstime,
    # priority, nice, num_threads, itrealvalue, starttime
    return f"{pid} ({name}) S 1 {pid} {pid} 0 -1 0 0 0 0 0 0 0 0 0 20 0 1 0 {start} 0\n"


class ProcessHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.proc = self.root / "proc"
        self.proc.mkdir()
        self.executable = self.root / "usr/bin/calamares"
        self.executable.parent.mkdir(parents=True)
        self.executable.write_text("#!/bin/sh\n", encoding="ascii")
        self.executable.chmod(0o755)

    def tearDown(self):
        self.temporary.cleanup()

    def add_process(
        self,
        pid: int,
        *,
        uid: int = 0,
        token: str = "openqa-calamares-1",
        executable: Path | None = None,
        state: str = "S",
        start: int = 1234,
    ) -> Path:
        process = self.proc / str(pid)
        process.mkdir()
        (process / "exe").symlink_to(executable or self.executable)
        (process / "status").write_text(
            f"State:\t{state} (state)\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n",
            encoding="ascii",
        )
        (process / "stat").write_text(stat_record(pid, start), encoding="ascii")
        (process / "environ").write_bytes(
            b"LANG=C\0DESKTOP_STARTUP_ID=" + token.encode("ascii") + b"\0"
        )
        return process

    def matches_exact_executable_uid_and_token(self):
        self.add_process(101)
        self.assertEqual(
            handoff.matching_processes(
                self.proc,
                self.executable.resolve(),
                0,
                "DESKTOP_STARTUP_ID",
                "openqa-calamares-1",
            ),
            [(101, 1234)],
        )

    def test_matches_exact_executable_uid_and_token(self):
        self.matches_exact_executable_uid_and_token()

    def test_rejects_wrong_uid_executable_token_and_zombie(self):
        other = self.root / "usr/bin/other"
        other.write_text("#!/bin/sh\n", encoding="ascii")
        other.chmod(0o755)
        self.add_process(101, uid=1000)
        self.add_process(102, executable=other)
        self.add_process(103, token="other")
        self.add_process(104, state="Z")
        self.assertEqual(
            handoff.matching_processes(
                self.proc, self.executable.resolve(), 0,
                "DESKTOP_STARTUP_ID", "openqa-calamares-1"
            ),
            [],
        )

    def test_stat_parser_handles_spaces_and_parentheses(self):
        process = self.add_process(105, start=9988)
        self.assertEqual(handoff._start_time(process / "stat"), 9988)

    def test_wait_requires_same_process_identity_twice(self):
        identity = [(201, 100)]
        with mock.patch.object(
            handoff, "matching_processes", side_effect=[identity, identity]
        ), mock.patch.object(handoff.time, "sleep") as sleep:
            result = handoff.wait_for_process(
                1, self.executable.resolve(), 0,
                "DESKTOP_STARTUP_ID", "openqa-calamares-1", self.proc
            )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["pid"], 201)
        sleep.assert_called_once()

    def test_pid_reuse_resets_stability(self):
        with mock.patch.object(
            handoff,
            "matching_processes",
            side_effect=[[(201, 100)], [(201, 101)], [(201, 101)]],
        ), mock.patch.object(handoff.time, "sleep"):
            result = handoff.wait_for_process(
                1, self.executable.resolve(), 0,
                "DESKTOP_STARTUP_ID", "openqa-calamares-1", self.proc
            )
        self.assertEqual(result["start_time"], 101)

    def test_ambiguous_exact_processes_fail(self):
        with mock.patch.object(
            handoff, "matching_processes", return_value=[(201, 1), (202, 2)]
        ):
            result = handoff.wait_for_process(
                1, self.executable.resolve(), 0,
                "DESKTOP_STARTUP_ID", "openqa-calamares-1", self.proc
            )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "ambiguous")

    def test_timeout_does_not_invent_a_process(self):
        clock = iter([0.0, 0.0, 0.1, 0.1])
        with mock.patch.object(handoff, "matching_processes", return_value=[]), \
             mock.patch.object(handoff.time, "monotonic", side_effect=lambda: next(clock)), \
             mock.patch.object(handoff.time, "sleep"):
            result = handoff.wait_for_process(
                0.1, self.executable.resolve(), 0,
                "DESKTOP_STARTUP_ID", "openqa-calamares-1", self.proc
            )
        self.assertEqual(result["reason"], "not-found")

    def test_environment_observation_is_bounded(self):
        process = self.add_process(106)
        (process / "environ").write_bytes(b"x" * (handoff.MAX_ENVIRONMENT + 1))
        self.assertIsNone(
            handoff.process_identity(
                process, self.executable.resolve(), 0,
                "DESKTOP_STARTUP_ID", "openqa-calamares-1"
            )
        )


if __name__ == "__main__":
    unittest.main()
