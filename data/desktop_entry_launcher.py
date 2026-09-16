"""Parse and launch one installed Desktop Entry without a shell."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DesktopEntry:
    path: Path
    name: str
    entry_type: str
    exec_line: str | None
    try_exec: str | None
    hidden: bool
    no_display: bool
    terminal: bool
    dbus_activatable: bool
    only_show_in: tuple[str, ...] = ()
    not_show_in: tuple[str, ...] = ()

    @property
    def launchable(self) -> bool:
        if self.hidden:
            return False
        if self.try_exec and shutil.which(self.try_exec) is None:
            return False
        return bool(self.exec_line) or self.dbus_activatable

    def skip_reason(self) -> str | None:
        if self.entry_type != "Application":
            return f"desktop entry type is {self.entry_type!r}"
        if self.hidden:
            return "desktop entry is hidden"
        if self.try_exec and shutil.which(self.try_exec) is None:
            return f"TryExec is not installed: {self.try_exec}"
        if not self.exec_line and not self.dbus_activatable:
            return "desktop entry has neither Exec nor DBusActivatable"
        if self.dbus_activatable and not self.exec_line and shutil.which("gio") is None:
            return "DBusActivatable entry requires gio, which is not installed"
        return None

    def not_applicable_reason(self) -> str | None:
        """Applicability is not a package-installation requirement for this ISO."""
        if self.hidden:
            return "desktop entry is hidden"
        if self.entry_type in {"Link", "Directory"}:
            return f"desktop entry type is {self.entry_type!r}"
        # XDG_CURRENT_DESKTOP is ordered; the first matching name decides.
        shown = not self.only_show_in
        for desktop in os.environ.get("XDG_CURRENT_DESKTOP", "").split(":"):
            if desktop and desktop in self.only_show_in:
                shown = True
                break
            if desktop and desktop in self.not_show_in:
                shown = False
                break
        if not shown:
            return "desktop entry does not apply to the current desktop"
        if self.try_exec and shutil.which(self.try_exec) is None:
            return f"not installed (TryExec): {self.try_exec}"
        if self.terminal:
            return "terminal command is outside the graphical application smoke test"
        return None

    def as_dict(self, root: Path) -> dict[str, object]:
        launch_binary = None
        if self.skip_reason() is None:
            try:
                launch_binary = Path(command_for_entry(self)[0]).name
            except (OSError, ValueError):
                launch_binary = None
        return {
            "path": str(self.path),
            "relative_path": str(self.path.relative_to(root)),
            "name": self.name,
            "type": self.entry_type,
            "exec": self.exec_line,
            "launch_binary": launch_binary,
            "try_exec": self.try_exec,
            "hidden": self.hidden,
            "no_display": self.no_display,
            "terminal": self.terminal,
            "dbus_activatable": self.dbus_activatable,
            "skip_reason": self.skip_reason(),
            "not_applicable_reason": self.not_applicable_reason(),
        }


def _unescape(value: str) -> str:
    replacements = {"\\s": " ", "\\n": "\n", "\\t": "\t", "\\r": "\r", "\\\\": "\\"}
    for source, target in replacements.items():
        value = value.replace(source, target)
    return value


def _parse_boolean(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def _read_group(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    in_desktop_entry = False
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        # A single entry that cannot be read must not cost the whole inventory.
        # The installed system ships one that only root may read, and letting
        # that abort the scan hid every other application behind it.
        return {"__unreadable__": str(error)}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_desktop_entry = line == "[Desktop Entry]"
            continue
        if not in_desktop_entry or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = _unescape(value.strip())
    return values


def parse_desktop_entry(path: Path) -> DesktopEntry:
    values = _read_group(path)
    unreadable = values.pop("__unreadable__", None)
    if unreadable is not None:
        # Reported as an entry with nothing launchable, which the coverage
        # inventory already classifies and explains.
        return DesktopEntry(
            path=path,
            name=path.stem,
            entry_type="",
            exec_line=None,
            try_exec=None,
            hidden=False,
            no_display=False,
            terminal=False,
            dbus_activatable=False,
        )
    return DesktopEntry(
        path=path,
        name=values.get("Name", path.stem),
        entry_type=values.get("Type", ""),
        exec_line=values.get("Exec") or None,
        try_exec=values.get("TryExec") or None,
        hidden=_parse_boolean(values.get("Hidden")),
        no_display=_parse_boolean(values.get("NoDisplay")),
        terminal=_parse_boolean(values.get("Terminal")),
        dbus_activatable=_parse_boolean(values.get("DBusActivatable")),
        only_show_in=tuple(filter(None, values.get("OnlyShowIn", "").split(";"))),
        not_show_in=tuple(filter(None, values.get("NotShowIn", "").split(";"))),
    )


def discover_desktop_entries(
    root: Path = Path("/usr/share/applications"),
) -> list[DesktopEntry]:
    """Return a complete inventory, or raise when a directory cannot be read.

    Path.rglob can suppress filesystem errors. An unreadable application tree
    must not be mistaken for an ISO without applications. Do not follow directory
    symlinks (which can cycle); individual packaged launcher symlinks stay valid.
    """
    entries: list[DesktopEntry] = []
    pending = [root]
    while pending:
        with os.scandir(pending.pop()) as children:
            for child in children:
                if child.is_dir(follow_symlinks=False):
                    pending.append(Path(child.path))
                elif child.name.endswith(".desktop"):
                    entries.append(parse_desktop_entry(Path(child.path)))
    return sorted(entries, key=lambda entry: str(entry.path))


def _expand_exec(entry: DesktopEntry) -> list[str]:
    if not entry.exec_line:
        return []
    argv = shlex.split(entry.exec_line, posix=True)
    expanded: list[str] = []
    for argument in argv:
        if argument in {"%f", "%F", "%u", "%U", "%i"}:
            continue
        argument = argument.replace("%c", entry.name).replace("%k", str(entry.path))
        argument = argument.replace("%%", "%")
        if "%" in argument:
            argument = argument.replace("%d", "").replace("%D", "")
            argument = argument.replace("%n", "").replace("%N", "")
            argument = argument.replace("%v", "")
        if argument:
            expanded.append(argument)
    return expanded


def command_for_entry(entry: DesktopEntry) -> list[str]:
    if entry.exec_line:
        return _expand_exec(entry)
    if entry.dbus_activatable:
        return ["gio", "launch", str(entry.path)]
    raise ValueError(f"{entry.path} has no launchable Exec command")


def resolve_entry_path(
    path: Path, root: Path = Path("/usr/share/applications")
) -> Path:
    """Validate a desktop-entry path lexically, then resolve package symlinks."""
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError(f"desktop entry is outside {root}")
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError(f"desktop entry is outside {root}") from error
    return path.resolve()


def _prepare_environment(entry: DesktopEntry, command: list[str]) -> dict[str, str]:
    environment = os.environ.copy()
    # Test the session and packaged command users actually receive. Do not force
    # an alternate toolkit, display server, renderer or accessibility bridge.
    if entry.terminal:
        terminal = shutil.which("konsole") or shutil.which("xterm")
        if terminal:
            original_command = list(command)
            if Path(terminal).name.casefold() == "konsole":
                command[:] = [terminal, "--nofork", "-e", *original_command]
            else:
                command[:] = [terminal, "-e", *original_command]

    return environment


def _inventory(root: Path) -> list[dict[str, object]]:
    return [entry.as_dict(root) for entry in discover_desktop_entries(root)]


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entry", type=Path)
    parser.add_argument("--inventory", action="store_true")
    parser.add_argument("--root", type=Path, default=Path("/usr/share/applications"))
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.inventory:
        print(
            json.dumps(_inventory(args.root), ensure_ascii=False, separators=(",", ":"))
        )
        return 0
    if args.entry is None:
        parser.error("--entry is required unless --inventory is used")

    root = Path("/usr/share/applications")
    entry_path = args.entry
    try:
        entry_path = resolve_entry_path(entry_path, root)
    except ValueError as error:
        parser.error(str(error))
    entry = parse_desktop_entry(entry_path)
    reason = entry.skip_reason()
    if reason:
        print(reason, file=sys.stderr)
        return 2
    command = command_for_entry(entry)
    environment = _prepare_environment(entry, command)
    os.execvpe(command[0], command, environment)


if __name__ == "__main__":
    raise SystemExit(main())
