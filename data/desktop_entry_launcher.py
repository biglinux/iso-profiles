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
    )


def discover_desktop_entries(
    root: Path = Path("/usr/share/applications"),
) -> list[DesktopEntry]:
    entries = [parse_desktop_entry(path) for path in root.rglob("*.desktop")]
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
    executable = Path(command[0]).name.casefold()
    entry_identity = entry.path.stem.casefold()

    # GitHub-hosted runners do not promise virgl or a usable physical GPU. Keep
    # every graphical application on the same deterministic software path;
    # this also prevents Qt Quick from selecting ZINK before AT-SPI is ready.
    environment["LIBGL_ALWAYS_SOFTWARE"] = "1"
    environment["GALLIUM_DRIVER"] = "llvmpipe"
    environment["MESA_LOADER_DRIVER_OVERRIDE"] = "llvmpipe"
    environment["QT_QUICK_BACKEND"] = "software"
    environment["QT_QPA_PLATFORM"] = "xcb"
    environment["QT_ACCESSIBILITY"] = "1"
    environment["GDK_BACKEND"] = "x11"
    environment.pop("WAYLAND_DISPLAY", None)

    if entry.terminal:
        terminal = shutil.which("konsole") or shutil.which("xterm")
        if terminal:
            original_command = list(command)
            if Path(terminal).name.casefold() == "konsole":
                command[:] = [terminal, "--nofork", "-e", *original_command]
            else:
                command[:] = [terminal, "-e", *original_command]

    if executable in {"libreoffice", "soffice", "soffice.bin"}:
        # The GTK VCL backend exposes LibreOffice's accessibility tree reliably
        # in the live KDE session while isolating the test profile.
        environment.setdefault("SAL_USE_VCLPLUGIN", "gtk3")
        environment.setdefault("SAL_ACCESSIBILITY_ENABLED", "1")
        if not any(
            argument.startswith("-env:UserInstallation=") for argument in command
        ):
            command.append(
                f"-env:UserInstallation=file:///tmp/openqa-lo-profile-{os.getpid()}"
            )

    if (
        "gimp" in executable or "gimp" in entry_identity
    ) and "--no-splash" not in command:
        command.append("--no-splash")

    if executable == "gkbd-keyboard-display" and len(command) == 1:
        # The desktop entry omits the required layout argument.
        command.extend(["-l", "us"])

    if (
        "brave" in executable or "brave" in entry_identity
    ) and "--force-renderer-accessibility" not in command:
        # Chromium-based browsers otherwise expose only their top-level frame
        # to AT-SPI in a fresh live session.
        command.append("--force-renderer-accessibility")

    if executable in {"vim", "nvim"} and "-es" not in command:
        # Terminal=true entries cannot expose a stable application AT-SPI tree.
        # Run Vim's real executable through a deterministic Ex command so the
        # process-only validation can prove startup and clean exit.
        command.extend(["-Nu", "NONE", "-n", "-es", "-c", "qa!"])

    if executable == "mpv" or entry_identity == "mpv":
        # GitHub-hosted runners do not provide a stable virgl device. Keep this
        # application test independent of host GPU availability while still
        # exercising mpv's X11 window and AT-SPI lifecycle.
        for option in (
            "--no-config",
            "--hwdec=no",
            "--vo=x11",
            "--force-window=immediate",
            "--idle=yes",
        ):
            if option in command:
                continue
            separator = command.index("--") if "--" in command else len(command)
            command.insert(separator, option)

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
    environment.setdefault("QT_LINUX_ACCESSIBILITY_ALWAYS_ON", "1")
    environment.setdefault("SAL_ACCESSIBILITY_ENABLED", "1")
    os.execvpe(command[0], command, environment)


if __name__ == "__main__":
    raise SystemExit(main())
