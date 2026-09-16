from __future__ import annotations

import tempfile
import os
import unittest
from unittest import mock
from pathlib import Path

from desktop_entry_launcher import (
    _prepare_environment,
    command_for_entry,
    discover_desktop_entries,
    parse_desktop_entry,
    resolve_entry_path,
)


class DesktopEntryLauncherTest(unittest.TestCase):
    def test_discovers_nested_application_entries_and_expands_exec(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "nested" / "tools"
            nested.mkdir(parents=True)
            entry_path = nested / "example.desktop"
            entry_path.write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=Example Tool\n"
                "Exec=example --title %c --desktop %k %U\n",
                encoding="utf-8",
            )

            entries = discover_desktop_entries(root)
            command = command_for_entry(entries[0])

        self.assertEqual(entries[0].name, "Example Tool")
        self.assertEqual(command[0:3], ["example", "--title", "Example Tool"])
        self.assertEqual(command[3], "--desktop")
        self.assertTrue(command[4].endswith("nested/tools/example.desktop"))

    def test_records_non_application_entries_without_launching_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry_path = root / "directory.desktop"
            entry_path.write_text(
                "[Desktop Entry]\nType=Directory\nName=Not an application\n",
                encoding="utf-8",
            )

            entry = discover_desktop_entries(root)[0]

        self.assertEqual(entry.skip_reason(), "desktop entry type is 'Directory'")

    def test_launches_nodisplay_entries_when_they_are_applications(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            entry_path = Path(directory, "helper.desktop")
            entry_path.write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=Background helper\n"
                "NoDisplay=true\n"
                "Exec=helper\n",
                encoding="utf-8",
            )

            entry = parse_desktop_entry(entry_path)

        self.assertTrue(entry.no_display)
        self.assertIsNone(entry.skip_reason())

    def test_preserves_terminal_metadata_for_a_process_validation_fallback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            entry_path = Path(directory, "terminal.desktop")
            entry_path.write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=Terminal command\n"
                "Terminal=true\n"
                "Exec=terminal-command\n",
                encoding="utf-8",
            )

            entry = parse_desktop_entry(entry_path)

        self.assertTrue(entry.terminal)

    def test_prefers_direct_exec_over_dbus_activation_for_atspi_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            entry_path = Path(directory, "filelight.desktop")
            entry_path.write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=Filelight\n"
                "Exec=filelight\n"
                "DBusActivatable=true\n",
                encoding="utf-8",
            )

            entry = parse_desktop_entry(entry_path)

        self.assertEqual(command_for_entry(entry), ["filelight"])

    def test_terminal_wrapper_does_not_turn_vim_into_a_noninteractive_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            entry_path = Path(directory, "vim.desktop")
            entry_path.write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=Vim\n"
                "Terminal=true\n"
                "Exec=vim\n",
                encoding="utf-8",
            )

            entry = parse_desktop_entry(entry_path)
            command = command_for_entry(entry)
            _prepare_environment(entry, command)

        self.assertIn("vim", command)
        self.assertEqual(command[-1], "vim")
        self.assertNotIn("-es", command)

    def test_resolves_desktop_entry_symlinks_without_leaving_application_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "applications"
            target = Path(directory) / "libreoffice" / "writer.desktop"
            root.mkdir()
            target.parent.mkdir()
            target.write_text("[Desktop Entry]\nName=Writer\n", encoding="utf-8")
            link = root / "libreoffice-writer.desktop"
            link.symlink_to(target)

            resolved = resolve_entry_path(link, root)

        self.assertEqual(resolved, target)

    def test_preserves_native_environment_and_packaged_gui_arguments(self) -> None:
        original = {"WAYLAND_DISPLAY": "wayland-1", "SAL_USE_VCLPLUGIN": "kf6"}
        with tempfile.TemporaryDirectory() as directory:
            for binary in ("brave", "libreoffice", "gimp", "mpv"):
                with self.subTest(binary=binary):
                    path = Path(directory, binary + ".desktop")
                    path.write_text("[Desktop Entry]\nType=Application\nName=Test\n"
                                    f"Exec={binary} %U\n", encoding="utf-8")
                    entry = parse_desktop_entry(path)
                    command = command_for_entry(entry)
                    with mock.patch.dict(os.environ, original, clear=True):
                        environment = _prepare_environment(entry, command)
                    self.assertEqual(command, [binary])
                    self.assertEqual(environment, original)

    def test_does_not_repair_missing_desktop_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            entry_path = Path(directory, "gkbd-keyboard-display.desktop")
            entry_path.write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=Keyboard Layout\n"
                "Exec=gkbd-keyboard-display\n",
                encoding="utf-8",
            )
            entry = parse_desktop_entry(entry_path)
            command = command_for_entry(entry)

            _prepare_environment(entry, command)

        self.assertEqual(command, ["gkbd-keyboard-display"])

    def test_mpv_keeps_its_native_output_and_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            entry_path = Path(directory, "mpv.desktop")
            entry_path.write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=mpv Media Player\n"
                "Exec=mpv --player-operation-mode=pseudo-gui -- %U\n",
                encoding="utf-8",
            )
            entry = parse_desktop_entry(entry_path)
            command = command_for_entry(entry)
            environment = _prepare_environment(entry, command)

        self.assertEqual(command, ["mpv", "--player-operation-mode=pseudo-gui", "--"])
        self.assertEqual(environment, dict(os.environ))


class UnreadableEntryTest(unittest.TestCase):
    """The installed system ships a desktop file only root may read. Letting it
    abort the scan hid every other application behind it."""

    def test_an_unreadable_entry_does_not_abort_the_scan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "good.desktop").write_text(
                "[Desktop Entry]\nName=Good\nExec=/bin/true\n", encoding="utf-8"
            )
            unreadable = root / "locked.desktop"
            unreadable.write_text(
                "[Desktop Entry]\nName=Locked\nExec=/bin/true\n", encoding="utf-8"
            )
            unreadable.chmod(0o000)

            original_read = Path.read_text
            def read_checked(path, *args, **kwargs):
                if path == unreadable:
                    raise PermissionError("test fixture denies access")
                return original_read(path, *args, **kwargs)
            with mock.patch.object(Path, "read_text", read_checked):
                entries = discover_desktop_entries(root)

        self.assertEqual([entry.name for entry in entries], ["Good", "locked"])
        # Nothing to launch, so the coverage inventory classifies and explains it.
        self.assertIsNone(entries[1].exec_line)


if __name__ == "__main__":
    unittest.main()
