from __future__ import annotations

import tempfile
import unittest
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

    def test_makes_terminal_vim_exit_cleanly_for_process_validation(self) -> None:
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
        self.assertEqual(command[-6:], ["-Nu", "NONE", "-n", "-es", "-c", "qa!"])

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

    def test_prepares_accessible_environment_for_heavy_gui_apps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            brave_path = root / "brave-browser.desktop"
            brave_path.write_text(
                "[Desktop Entry]\nType=Application\nName=Brave\nExec=brave %U\n",
                encoding="utf-8",
            )
            libreoffice_path = root / "libreoffice-writer.desktop"
            libreoffice_path.write_text(
                "[Desktop Entry]\nType=Application\nName=Writer\nExec=libreoffice --writer %U\n",
                encoding="utf-8",
            )
            gimp_path = root / "gimp.desktop"
            gimp_path.write_text(
                "[Desktop Entry]\nType=Application\nName=GIMP\nExec=gimp-3.2 %U\n",
                encoding="utf-8",
            )

            brave = parse_desktop_entry(brave_path)
            libreoffice = parse_desktop_entry(libreoffice_path)
            brave_command = command_for_entry(brave)
            libreoffice_command = command_for_entry(libreoffice)
            gimp = parse_desktop_entry(gimp_path)
            gimp_command = command_for_entry(gimp)
            _prepare_environment(brave, brave_command)
            libreoffice_environment = _prepare_environment(
                libreoffice, libreoffice_command
            )
            _prepare_environment(gimp, gimp_command)

        self.assertIn("--force-renderer-accessibility", brave_command)
        self.assertIn("--no-splash", gimp_command)
        self.assertTrue(
            any(
                argument.startswith("-env:UserInstallation=")
                for argument in libreoffice_command
            )
        )
        self.assertEqual(libreoffice_environment["SAL_USE_VCLPLUGIN"], "gtk3")
        self.assertEqual(libreoffice_environment["SAL_ACCESSIBILITY_ENABLED"], "1")
        self.assertEqual(libreoffice_environment["LIBGL_ALWAYS_SOFTWARE"], "1")
        self.assertEqual(libreoffice_environment["GALLIUM_DRIVER"], "llvmpipe")
        self.assertEqual(
            libreoffice_environment["MESA_LOADER_DRIVER_OVERRIDE"], "llvmpipe"
        )
        self.assertEqual(libreoffice_environment["QT_QUICK_BACKEND"], "software")
        self.assertEqual(libreoffice_environment["QT_QPA_PLATFORM"], "xcb")
        self.assertEqual(libreoffice_environment["QT_ACCESSIBILITY"], "1")
        self.assertEqual(libreoffice_environment["GDK_BACKEND"], "x11")

    def test_supplies_layout_to_keyboard_display(self) -> None:
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

        self.assertEqual(command, ["gkbd-keyboard-display", "-l", "us"])

    def test_forces_software_rendering_for_mpv_before_file_separator(self) -> None:
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

        separator = command.index("--")
        self.assertLess(command.index("--no-config"), separator)
        self.assertLess(command.index("--hwdec=no"), separator)
        self.assertLess(command.index("--vo=x11"), separator)
        self.assertLess(command.index("--force-window=immediate"), separator)
        self.assertLess(command.index("--idle=yes"), separator)
        self.assertEqual(environment["LIBGL_ALWAYS_SOFTWARE"], "1")
        self.assertEqual(environment["GALLIUM_DRIVER"], "llvmpipe")
        self.assertEqual(environment["MESA_LOADER_DRIVER_OVERRIDE"], "llvmpipe")


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

            entries = discover_desktop_entries(root)

        self.assertEqual([entry.name for entry in entries], ["Good", "locked"])
        # Nothing to launch, so the coverage inventory classifies and explains it.
        self.assertIsNone(entries[1].exec_line)


if __name__ == "__main__":
    unittest.main()
