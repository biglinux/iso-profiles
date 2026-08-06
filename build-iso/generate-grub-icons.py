#!/usr/bin/env python3
"""Generate unique, low-contrast icons for every static BigLinux GRUB entry."""

from __future__ import annotations

import hashlib
import math
import re
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SOURCE_GRUB = ROOT / "sources/common/overlays/live/usr/share/grub"
SOURCE_CFG = SOURCE_GRUB / "cfg/kernels.cfg"
THEME_NAMES = ("manjaro-live", "biglinux-live")
EDITIONS = ("kde", "xivastudio")
DYNAMIC_EFI_SLOTS = 32
SIZE = 32
SCALE = 4
CANVAS = SIZE * SCALE
PRIMARY = (216, 227, 234, 180)
SECONDARY = (160, 181, 193, 125)
ACCENT = (0, 189, 227, 215)
ENTRY_RE = re.compile(r'^(\s*)(menuentry|submenu)\s+"([^"]+)"(.*--id=([^\s{]+).*)$')
UNIQUE_CLASS_RE = re.compile(r'\s+--class=icon-[^\s{]+')


def pt(x: float) -> int:
    return round(x * SCALE)


def line(draw: ImageDraw.ImageDraw, points: list[tuple[float, float]], fill=PRIMARY, width=1.15) -> None:
    draw.line([(pt(x), pt(y)) for x, y in points], fill=fill, width=max(1, pt(width)), joint="curve")


def ellipse(draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float], outline=PRIMARY, width=1.15, fill=None) -> None:
    draw.ellipse(tuple(pt(v) for v in box), outline=outline, width=max(1, pt(width)), fill=fill)


def rectangle(draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float], outline=PRIMARY, width=1.15, radius=2.0, fill=None) -> None:
    draw.rounded_rectangle(tuple(pt(v) for v in box), radius=pt(radius), outline=outline, width=max(1, pt(width)), fill=fill)


def polygon(draw: ImageDraw.ImageDraw, points: list[tuple[float, float]], outline=PRIMARY, fill=None, width=1.15) -> None:
    xy = [(pt(x), pt(y)) for x, y in points]
    draw.polygon(xy, fill=fill)
    if outline:
        draw.line(xy + [xy[0]], fill=outline, width=max(1, pt(width)), joint="curve")


def draw_monitor(draw: ImageDraw.ImageDraw) -> None:
    rectangle(draw, (6, 7, 26, 21), radius=2.0)
    line(draw, [(10, 24), (22, 24)], fill=SECONDARY)
    line(draw, [(14, 21), (13, 24), (19, 24), (18, 21)], fill=SECONDARY)


def draw_chip(draw: ImageDraw.ImageDraw) -> None:
    rectangle(draw, (8, 8, 24, 24), radius=2.0)
    for v in (11, 16, 21):
        line(draw, [(v, 5), (v, 8)], fill=SECONDARY)
        line(draw, [(v, 24), (v, 27)], fill=SECONDARY)
        line(draw, [(5, v), (8, v)], fill=SECONDARY)
        line(draw, [(24, v), (27, v)], fill=SECONDARY)
    ellipse(draw, (13, 13, 19, 19), outline=ACCENT, width=1.0)


def draw_drive(draw: ImageDraw.ImageDraw) -> None:
    rectangle(draw, (6, 9, 26, 23), radius=2.5)
    line(draw, [(8, 19), (24, 19)], fill=SECONDARY)
    ellipse(draw, (21, 12, 23, 14), outline=ACCENT, fill=ACCENT, width=0.8)


def draw_network(draw: ImageDraw.ImageDraw) -> None:
    ellipse(draw, (13, 6, 19, 12))
    ellipse(draw, (5, 20, 11, 26))
    ellipse(draw, (21, 20, 27, 26))
    line(draw, [(16, 12), (8, 20)], fill=SECONDARY)
    line(draw, [(16, 12), (24, 20)], fill=SECONDARY)
    line(draw, [(11, 23), (21, 23)], fill=SECONDARY)


def draw_speaker(draw: ImageDraw.ImageDraw) -> None:
    polygon(draw, [(6, 13), (11, 13), (17, 8), (17, 24), (11, 19), (6, 19)], outline=PRIMARY)
    line(draw, [(21, 12), (24, 16), (21, 20)], fill=ACCENT)


def draw_keyboard(draw: ImageDraw.ImageDraw) -> None:
    rectangle(draw, (5, 10, 27, 23), radius=2.0)
    for y in (14, 18):
        line(draw, [(8, y), (24, y)], fill=SECONDARY, width=0.8)
    for x in (10, 14, 18, 22):
        line(draw, [(x, 12), (x, 20)], fill=SECONDARY, width=0.8)


def draw_clock(draw: ImageDraw.ImageDraw) -> None:
    ellipse(draw, (6, 6, 26, 26))
    line(draw, [(16, 10), (16, 16), (21, 19)], fill=ACCENT)


def draw_shield(draw: ImageDraw.ImageDraw) -> None:
    polygon(draw, [(16, 5), (26, 9), (24, 21), (16, 27), (8, 21), (6, 9)], outline=PRIMARY)
    line(draw, [(12, 16), (15, 19), (21, 12)], fill=ACCENT)


def draw_tools(draw: ImageDraw.ImageDraw) -> None:
    line(draw, [(8, 24), (23, 9)], width=1.5)
    ellipse(draw, (18, 5, 27, 14))
    line(draw, [(7, 8), (13, 14)], fill=SECONDARY, width=1.5)
    line(draw, [(6, 6), (10, 6), (10, 10)], fill=SECONDARY, width=1.2)


def draw_info(draw: ImageDraw.ImageDraw) -> None:
    ellipse(draw, (7, 7, 25, 25))
    ellipse(draw, (15, 10, 17, 12), outline=ACCENT, fill=ACCENT, width=0.8)
    line(draw, [(16, 15), (16, 21)], fill=ACCENT, width=1.4)


def draw_memory(draw: ImageDraw.ImageDraw) -> None:
    rectangle(draw, (5, 10, 27, 22), radius=1.6)
    for x in (9, 13, 17, 21):
        rectangle(draw, (x, 13, x + 2, 18), outline=SECONDARY, radius=0.4, width=0.8)
    for x in range(8, 26, 3):
        line(draw, [(x, 22), (x, 25)], fill=ACCENT, width=0.7)


def draw_terminal(draw: ImageDraw.ImageDraw) -> None:
    rectangle(draw, (5, 7, 27, 25), radius=2.0)
    line(draw, [(9, 12), (13, 16), (9, 20)], fill=ACCENT, width=1.3)
    line(draw, [(16, 20), (23, 20)], fill=SECONDARY)


def draw_power(draw: ImageDraw.ImageDraw) -> None:
    line(draw, [(16, 5), (16, 15)], fill=ACCENT, width=1.5)
    # Arc approximated by polyline to keep line weight consistent.
    points = []
    for deg in range(-45, 226, 12):
        rad = math.radians(deg)
        points.append((16 + 10 * math.cos(rad), 16 + 10 * math.sin(rad)))
    line(draw, points, width=1.3)


def draw_back(draw: ImageDraw.ImageDraw) -> None:
    line(draw, [(25, 9), (14, 9), (14, 6), (6, 14), (14, 22), (14, 19), (25, 19)], width=1.3)


def draw_play(draw: ImageDraw.ImageDraw) -> None:
    polygon(draw, [(10, 7), (25, 16), (10, 25)], outline=PRIMARY)
    ellipse(draw, (7, 14, 9, 16), outline=ACCENT, fill=ACCENT, width=0.8)


def draw_folder(draw: ImageDraw.ImageDraw) -> None:
    polygon(draw, [(5, 10), (13, 10), (16, 7), (27, 7), (27, 24), (5, 24)], outline=PRIMARY)
    line(draw, [(8, 19), (22, 19)], fill=ACCENT)


def draw_restart(draw: ImageDraw.ImageDraw) -> None:
    points = []
    for deg in range(-40, 255, 12):
        rad = math.radians(deg)
        points.append((16 + 10 * math.cos(rad), 16 + 10 * math.sin(rad)))
    line(draw, points, width=1.3)
    polygon(draw, [(23, 5), (27, 6), (25, 10)], outline=ACCENT, fill=ACCENT, width=0.8)


def draw_generic(draw: ImageDraw.ImageDraw) -> None:
    for x, y1, y2, knob in ((9, 8, 24, 13), (16, 6, 26, 19), (23, 9, 23, 15)):
        line(draw, [(x, y1), (x, y2)], fill=SECONDARY)
        ellipse(draw, (x - 2, knob - 2, x + 2, knob + 2), outline=PRIMARY)
    ellipse(draw, (14.8, 17.8, 17.2, 20.2), outline=ACCENT, fill=ACCENT, width=0.6)


def choose_base(title: str, kind: str):
    text = title.lower()
    if "return" in text:
        return draw_back
    if kind == "menuentry" and ("restart" in text or "reboot" in text):
        return draw_restart
    if "start biglinux" in text or "open the live desktop" in text or "installer directly" in text:
        return draw_play
    if any(word in text for word in ("computer", "boot information", "display", "screen", "video", "graphics", "xorg", "wayland", "panel", "hdmi", "monitor", "brightness", "framebuffer", "gpu", "nvidia", "amdgpu", "intel")):
        return draw_monitor
    if any(word in text for word in ("firmware", "uefi", "efi", "bios", "cpu", "processor", "microcode", "iommu", "acpi", "pci", "pcie")):
        return draw_chip
    if any(word in text for word in ("disk", "storage", "nvme", "sata", "filesystem", "root", "uuid", "usb", "sd card", "mmc", "drive")):
        return draw_drive
    if any(word in text for word in ("network", "wifi", "wi-fi", "ethernet", "bluetooth")):
        return draw_network
    if any(word in text for word in ("audio", "sound", "speaker", "microphone")):
        return draw_speaker
    if any(word in text for word in ("keyboard", "input", "mouse", "touchpad")):
        return draw_keyboard
    if any(word in text for word in ("clock", "time", "timeout", "timer")):
        return draw_clock
    if any(word in text for word in ("secure", "security", "lockdown", "tpm", "encryption", "verification")):
        return draw_shield
    if any(word in text for word in ("memory", "memtest", "ram")):
        return draw_memory
    if any(word in text for word in ("terminal", "multi-user", "console")):
        return draw_terminal
    if any(word in text for word in ("diagnostic", "debug", "trace", "detailed", "information", "vendor", "manufacturer", "product", "theme")):
        return draw_info
    if any(word in text for word in ("rescue", "recovery", "fails", "failure", "freeze", "hang", "error", "broken")):
        return draw_tools
    if kind == "submenu" or "options" in text:
        return draw_folder
    if "start" in text or "boot" in text:
        return draw_power
    return draw_generic


def add_modifiers(draw: ImageDraw.ImageDraw, title: str) -> None:
    text = title.lower()
    if any(word in text for word in ("disable", "without", "off", "no ", "fails", "failure", "black")):
        line(draw, [(7, 25), (25, 7)], fill=SECONDARY, width=0.85)
    elif any(word in text for word in ("enable", "force", "use ", "directly")):
        line(draw, [(22, 23), (25, 26), (29, 20)], fill=ACCENT, width=0.9)
    if any(word in text for word in ("freeze", "hang", "stalls")):
        line(draw, [(12, 16), (20, 16)], fill=ACCENT, width=1.1)
        line(draw, [(16, 12), (16, 20)], fill=ACCENT, width=1.1)
    if any(word in text for word in ("flicker", "artifact", "corrupt")):
        line(draw, [(6, 27), (10, 24), (14, 27), (18, 24), (22, 27), (26, 24)], fill=ACCENT, width=0.8)


def add_unique_signature(draw: ImageDraw.ImageDraw, entry_id: str) -> None:
    digest = hashlib.sha256(entry_id.encode("utf-8")).digest()
    positions = [
        (5 + i * 2.2, 4) for i in range(11)
    ] + [
        (27, 7 + i * 2.2) for i in range(9)
    ] + [
        (25 - i * 2.2, 28) for i in range(4)
    ]
    bits = int.from_bytes(digest[:3], "big")
    selected = [positions[i] for i in range(24) if bits & (1 << i)]
    # Keep the signature discreet while preserving enough entropy for uniqueness.
    if len(selected) < 4:
        selected.extend(positions[(digest[3] + i * 5) % len(positions)] for i in range(4 - len(selected)))
    for x, y in selected[:8]:
        ellipse(draw, (x - 0.45, y - 0.45, x + 0.45, y + 0.45), outline=ACCENT, fill=ACCENT, width=0.4)


def render_icon(title: str, kind: str, entry_id: str, output: Path) -> None:
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    choose_base(title, kind)(draw)
    add_modifiers(draw, title)
    add_unique_signature(draw, entry_id)
    image = image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, optimize=True)


def rewrite_cfg(text: str) -> tuple[str, list[tuple[str, str, str]]]:
    entries: list[tuple[str, str, str]] = []
    output: list[str] = []
    for line_text in text.splitlines():
        match = ENTRY_RE.match(line_text)
        if not match:
            if 'menuentry --class=efi "${efi}"' in line_text:
                line_text = line_text.replace('menuentry --class=efi "${efi}"', 'menuentry --class=void "${efi}"')
            output.append(line_text)
            continue
        indent, kind, title, tail, entry_id = match.groups()
        tail = UNIQUE_CLASS_RE.sub("", tail)
        unique_class = f"icon-{entry_id}"
        output.append(f'{indent}{kind} "{title}" --class={unique_class}{tail}')
        entries.append((kind, title, entry_id))
    return "\n".join(output) + "\n", entries


def sync_cfg(source: Path) -> None:
    for edition in EDITIONS:
        target = ROOT / f"biglinux/{edition}/live-overlay/usr/share/grub/cfg/kernels.cfg"
        shutil.copy2(source, target)


def sync_icons(source_icons: Path) -> None:
    destinations = []
    for theme in THEME_NAMES:
        destinations.append(SOURCE_GRUB / f"themes/{theme}/icons")
        for edition in EDITIONS:
            destinations.append(ROOT / f"biglinux/{edition}/live-overlay/usr/share/grub/themes/{theme}/icons")
    unique_icons = list(source_icons.glob("icon-*.png"))
    for destination in destinations:
        destination.mkdir(parents=True, exist_ok=True)
        if destination.resolve() == source_icons.resolve():
            continue
        for stale in destination.glob("icon-biglinux-*.png"):
            stale.unlink()
        for icon in unique_icons:
            shutil.copy2(icon, destination / icon.name)


def main() -> None:
    rewritten, entries = rewrite_cfg(SOURCE_CFG.read_text(encoding="utf-8"))
    SOURCE_CFG.write_text(rewritten, encoding="utf-8")
    icon_dir = SOURCE_GRUB / "themes/manjaro-live/icons"
    for stale in icon_dir.glob("icon-biglinux-*.png"):
        stale.unlink()
    for kind, title, entry_id in entries:
        render_icon(title, kind, entry_id, icon_dir / f"icon-{entry_id}.png")
    for slot in range(1, DYNAMIC_EFI_SLOTS + 1):
        entry_id = f"biglinux-efi-detected-{slot:02d}"
        render_icon(
            f"Detected EFI bootloader {slot:02d}",
            "menuentry",
            entry_id,
            icon_dir / f"icon-{entry_id}.png",
        )
    sync_cfg(SOURCE_CFG)
    sync_icons(icon_dir)
    total = len(entries) + DYNAMIC_EFI_SLOTS
    print(f"Generated {total} unique GRUB icons ({len(entries)} static, {DYNAMIC_EFI_SLOTS} dynamic EFI).")


if __name__ == "__main__":
    main()
