# SPDX-License-Identifier: GPL-2.0-or-later
"""Empty optional-app inventories are valid; incomplete filesystem reads are not."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from desktop_entry_launcher import discover_desktop_entries


class InventoryIntegrityTests(unittest.TestCase):
    def test_empty_readable_inventory_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(discover_desktop_entries(Path(directory)), [])

    def test_missing_inventory_root_is_not_an_empty_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                discover_desktop_entries(Path(directory) / "missing")

    def test_unreadable_subdirectory_does_not_return_partial_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blocked = root / "blocked"
            blocked.mkdir()
            (root / "present.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=Present\nExec=true\n")
            scan = os.scandir

            def fail_subdirectory(path):
                if Path(path) == blocked:
                    raise PermissionError("injected directory scan failure")
                return scan(path)

            with mock.patch("desktop_entry_launcher.os.scandir", side_effect=fail_subdirectory):
                with self.assertRaises(PermissionError):
                    discover_desktop_entries(root)

    def test_inventory_keeps_launcher_symlinks_without_following_directory_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "applications"
            root.mkdir()
            target = Path(directory) / "packaged.desktop"
            target.write_text("[Desktop Entry]\nType=Application\nName=Packaged\nExec=true\n")
            launcher = root / "packaged.desktop"
            launcher.symlink_to(target)
            (root / "cycle").symlink_to(root, target_is_directory=True)
            entries = discover_desktop_entries(root)
            self.assertEqual([entry.path for entry in entries], [launcher])
            self.assertEqual(entries[0].name, "Packaged")
