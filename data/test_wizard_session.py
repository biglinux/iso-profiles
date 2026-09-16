# SPDX-License-Identifier: GPL-2.0-or-later
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import wizard_session as session


class WizardSessionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/tmp/private-wizard-bus",
                            "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}", "WAYLAND_DISPLAY": "wayland-0"}

    def process(self, pid=42, environment=None):
        process = self.root / str(pid)
        process.mkdir()
        (process / 'comm').write_bytes(b'python\n')
        (process / 'stat').write_bytes(b'42 (python) ' + b' '.join([b'1'] * 50))
        (process / 'cmdline').write_bytes(b'python\0' + session.WIZARD + b'\0')
        environment = self.environment if environment is None else environment
        (process / 'environ').write_bytes(b'\0'.join(k.encode()+b'='+v.encode() for k,v in environment.items()))
        return process

    def test_private_bus_is_selected_without_touching_user_bus(self):
        self.process()
        self.assertEqual(session.wizard_environment(self.root), self.environment)

    def test_missing_wizard_never_falls_back_to_user_bus(self):
        self.assertIsNone(session.wizard_environment(self.root))

    def test_other_users_process_is_rejected(self):
        self.process()
        self.assertIsNone(session.wizard_environment(self.root, uid=os.getuid()+1))

    def test_two_wizards_are_ambiguous(self):
        self.process(42)
        self.process(43)
        with self.assertRaisesRegex(ValueError, 'more than one'):
            session.wizard_environment(self.root)

    def test_wrong_runtime_owner_is_rejected(self):
        self.process(environment=dict(self.environment, XDG_RUNTIME_DIR='/run/user/987654'))
        with self.assertRaisesRegex(ValueError, 'runtime directory'):
            session.wizard_environment(self.root)

    def test_secret_and_toolkit_overrides_are_not_copied(self):
        self.process(environment=dict(self.environment, TOKEN='secret', GTK_A11Y='none'))
        result = session.wizard_environment(self.root)
        self.assertNotIn('TOKEN', result)
        self.assertNotIn('GTK_A11Y', result)

    def test_shell_values_are_data_not_commands(self):
        path = self.root / 'injected'
        value = f"'; touch {path}; echo '"
        command = session.shell_environment(dict(self.environment, DISPLAY=value))
        output = subprocess.check_output(['bash', '-c', command + '; printf %s "$DISPLAY"'], text=True)
        self.assertEqual(output, value)
        self.assertFalse(path.exists())

    def test_control_characters_are_rejected(self):
        self.process(environment=dict(self.environment, DISPLAY=':0\nwrong'))
        with self.assertRaisesRegex(ValueError, 'control character'):
            session.wizard_environment(self.root)

    def test_pid_reuse_is_not_a_session_match(self):
        self.process()
        read = session.read_limited
        calls = 0
        def changing_stat(path):
            nonlocal calls
            if path.name == 'stat':
                calls += 1
                return b'42 (python) ' + b' '.join([str(calls).encode()] * 50)
            return read(path)
        with mock.patch.object(session, 'read_limited', side_effect=changing_stat):
            self.assertIsNone(session.wizard_environment(self.root))

    def test_search_command_mentioning_wizard_is_not_the_wizard(self):
        process = self.process()
        (process / 'comm').write_bytes(b'grep\n')
        self.assertIsNone(session.wizard_environment(self.root))

    def test_explicit_accessibility_bus_is_preserved(self):
        environment = dict(self.environment, AT_SPI_BUS_ADDRESS="unix:path=/run/user/1000/at-spi/bus")
        self.process(environment=environment)
        result = session.wizard_environment(self.root)
        command = session.shell_environment(result)
        output = subprocess.check_output(['bash', '-c', command + '; printf %s "$AT_SPI_BUS_ADDRESS"'], text=True)
        self.assertEqual(output, environment['AT_SPI_BUS_ADDRESS'])

    def test_remote_accessibility_bus_is_rejected(self):
        self.process(environment=dict(self.environment, AT_SPI_BUS_ADDRESS="tcp:host=remote,port=1"))
        with self.assertRaisesRegex(ValueError, 'local bus'):
            session.wizard_environment(self.root)
