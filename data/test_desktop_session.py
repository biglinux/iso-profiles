# SPDX-License-Identifier: GPL-2.0-or-later
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest
from unittest import mock

import desktop_session as session


class DesktopSessionTests(unittest.TestCase):
    def test_environment_is_typed_data_not_shell_source(self):
        value = "text with spaces ' $() \\"
        parsed = session.manager_environment(json.dumps({"type": "as", "data": [
            "DISPLAY=:0", "XDG_CURRENT_DESKTOP=GNOME", "XAUTHORITY=" + value, "TOKEN=secret"]}))
        self.assertEqual(parsed["XAUTHORITY"], value)
        self.assertNotIn("TOKEN", parsed)

    def test_environment_wrong_type_duplicates_and_controls_fail(self):
        for record in ({"type": "s", "data": ["DISPLAY=:0"]}, {"type": "as", "data": [4]},
                       {"type": "as", "data": ["DISPLAY=:0", "DISPLAY=:1"]},
                       {"type": "as", "data": ["DISPLAY=:0\n"]}, []):
            with self.subTest(record=record), self.assertRaises(session.SessionPending):
                session.manager_environment(json.dumps(record))

    def test_old_wizard_address_is_never_exported(self):
        emitted = session.shell_environment({"DISPLAY": ":1", "AT_SPI_BUS_ADDRESS": "old"})
        self.assertIn("AT_SPI_BUS_ADDRESS", emitted.split(";")[0])
        self.assertNotIn("export AT_SPI_BUS_ADDRESS", emitted)

    def test_export_quotes_values_and_preserves_only_whitelist(self):
        with tempfile.TemporaryDirectory() as tmp:
            injected = Path(tmp) / "injected"
            value = f"'; touch {injected}; echo '"
            code = session.shell_environment({"DISPLAY": value, "TOKEN": "secret"})
            self.assertNotIn("secret", code)
            self.assertEqual(subprocess.check_output(["sh", "-c", code + '; printf %s "$DISPLAY"'], text=True), value)
            self.assertFalse(injected.exists())

    def test_missing_display_does_not_pass_on_user_bus_alone(self):
        with self.assertRaisesRegex(session.SessionPending, "display"):
            session.display_ready({"XDG_CURRENT_DESKTOP": "KDE"}, Path("/tmp"), time.monotonic() + 1)

    def test_reachable_local_wayland_socket(self):
        with tempfile.TemporaryDirectory() as tmp, socket.socket(socket.AF_UNIX) as server:
            server.bind(tmp + "/wayland-1")
            server.listen(1)
            session.display_ready({"XDG_CURRENT_DESKTOP": "GNOME", "WAYLAND_DISPLAY": "wayland-1"},
                                  Path(tmp), time.monotonic() + 1)

    def test_missing_socket_is_pending_not_repaired(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(session.SessionPending, "socket"):
                session.display_ready({"XDG_CURRENT_DESKTOP": "KDE", "WAYLAND_DISPLAY": "missing"},
                                      Path(tmp), time.monotonic() + 1)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_new_session_must_be_stable_twice(self):
        first = ({"DISPLAY": ":0"}, "old-bus")
        final = ({"DISPLAY": ":1"}, "new-bus")
        with mock.patch.object(session, "session_snapshot", side_effect=[first, final, final]) as query, \
             mock.patch.object(session.time, "sleep"):
            self.assertEqual(session.wait_session(2), final[0])
            self.assertEqual(query.call_count, 3)

    def test_transient_socket_removal_resets_stability(self):
        final = ({"DISPLAY": ":1"}, "new-bus")
        with mock.patch.object(session, "session_snapshot", side_effect=[final, session.SessionPending("transition"), final, final]) as query, \
             mock.patch.object(session.time, "sleep"):
            self.assertEqual(session.wait_session(2), final[0])
            self.assertEqual(query.call_count, 4)

    def test_persistent_failure_expires(self):
        with mock.patch.object(session, "session_snapshot", side_effect=session.SessionPending("stale bus")), \
             self.assertRaisesRegex(session.SessionPending, "stale bus"):
            session.wait_session(0.01)

    def test_snapshot_queries_actual_bus_without_restarting_it(self):
        calls = []
        def response(argv, env, deadline):
            calls.append((argv, env))
            if "get-property" in argv:
                return json.dumps({"type": "as", "data": ["DISPLAY=:0", "XDG_CURRENT_DESKTOP=KDE"]})
            if "is-active" in argv:
                return "active\n"
            if "GetAddress" in argv:
                return json.dumps({"type": "s", "data": ["unix:path=/run/user/42/at-spi/bus"]})
            return 's "existing-bus-id"'
        with mock.patch.object(session, "command", side_effect=response), \
             mock.patch.object(session, "display_ready"), mock.patch.object(session.os, "getuid", return_value=42), \
             mock.patch.dict(os.environ, {"DBUS_SESSION_BUS_ADDRESS": "wizard-private", "AT_SPI_BUS_ADDRESS": "stale"}):
            environment, bus = session.session_snapshot(time.monotonic() + 1)
        self.assertEqual(environment["DBUS_SESSION_BUS_ADDRESS"], "unix:path=/run/user/42/bus")
        self.assertEqual(len(calls), 4)
        self.assertIn("--address=unix:path=/run/user/42/at-spi/bus", calls[-1][0])
        self.assertTrue(all("AT_SPI_BUS_ADDRESS" not in env for _, env in calls))
        self.assertTrue(all("restart" not in argv and "start" not in argv for argv, _ in calls))

    def test_query_error_does_not_leak_stderr(self):
        failed = subprocess.CompletedProcess(["busctl"], 1, "", "TOKEN=secret")
        with mock.patch.object(session.subprocess, "run", return_value=failed), \
             self.assertRaisesRegex(session.SessionPending, "session query failed") as caught:
            session.command(["busctl"], {}, time.monotonic() + 1)
        self.assertNotIn("secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
