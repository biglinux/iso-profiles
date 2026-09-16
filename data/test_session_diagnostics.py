# SPDX-License-Identifier: GPL-2.0-or-later
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest import mock
import session_diagnostics as diagnostics


class SessionDiagnosticsTest(unittest.TestCase):
    def test_environment_never_contains_unlisted_secrets(self):
        result = diagnostics.filtered_environment(b'DISPLAY=:1\0TOKEN=secret\0PASSWORD=secret\0GTK_A11Y=none\0')
        self.assertEqual(result, {'DISPLAY': ':1', 'GTK_A11Y': 'none'})

    def test_process_arguments_are_not_in_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory) / '12'
            proc.mkdir()
            (proc / 'comm').write_text('python3\n')
            (proc / 'cmdline').write_bytes(b'python3\0/usr/share/biglinux/livecd/main.py\0secret\0')
            (proc / 'environ').write_bytes(b'TOKEN=secret\0DISPLAY=:0\0')
            result = diagnostics.process_sessions(Path(directory))
        self.assertEqual(result[0]['process'], 'live-wizard')
        self.assertNotIn('secret', str(result))

    def test_deadline_does_not_start_a_command(self):
        with mock.patch.object(diagnostics.subprocess, 'run') as run:
            self.assertIn('error', diagnostics.command(['unused'], time.monotonic() - 1))
            run.assert_not_called()

    def test_timeout_does_not_include_command_output(self):
        with mock.patch.object(diagnostics.subprocess, 'run', side_effect=
                               subprocess.TimeoutExpired(['cmd'], 1, output=b'secret')):
            result = diagnostics.command(['cmd'], time.monotonic() + 5)
        self.assertEqual(result['error'], 'TimeoutExpired')
        self.assertNotIn('secret', str(result))
