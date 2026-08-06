"""Regression tests for the BigLinux live GRUB menu and its generated profiles."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "sources/common/overlays/live/usr/share/grub"
CFG = SOURCE / "cfg"
KERNELS = (CFG / "kernels.cfg").read_text(encoding="utf-8")
GRUB = (CFG / "grub.cfg").read_text(encoding="utf-8")
VARIABLES = (CFG / "variable.cfg").read_text(encoding="utf-8")
SUPPORT = (ROOT / "docs/grub-live/SUPPORT-CODES.md").read_text(encoding="utf-8")

EDITIONS = ("kde", "xivastudio")
EXPECTED_CATEGORY_LAST_CODE = {
    2: 38,
    3: 20,
    4: 14,
    5: 20,
    6: 29,
    7: 22,
    8: 26,
    9: 11,
}


def _ids(text: str) -> list[str]:
    return re.findall(r"--id=([^\s{]+)", text)


def _support_codes(text: str) -> list[str]:
    return re.findall(r"^\| \*\*(\d+\.\d+)\*\* \|", text, re.MULTILINE)


def test_normal_entries_are_small_and_safe():
    assert (
        'set live_common="misobasedir=manjaro misolabel=BIGLINUXLIVE rw '
        'nmi_watchdog=0"'
    ) in KERNELS
    assert 'set live_nonfree="driver=nonfree nouveau.modeset=0"' in KERNELS
    assert 'set live_free="driver=free"' in KERNELS
    assert (
        "linux ${live_kernel} ${live_common} wayland ${live_nonfree} "
        "${live_ui} ${kopts}"
    ) in KERNELS
    assert (
        "linux ${live_kernel} ${live_common} wayland ${live_free} "
        "${live_ui} ${kopts}"
    ) in KERNELS

    common = re.search(r'^set live_common="([^"]+)"$', KERNELS, re.MULTILINE)
    assert common
    rejected = {
        "audit=0",
        "clearcpuid=514",
        "cryptomgr.notests",
        "intremap=off",
        "nomce",
        "nosoftlockup",
        "nowatchdog",
        "rcupdate.rcu_expedited=1",
        "skew_tick=1",
        "split_lock_detect=off",
        "tsc=nowatchdog",
    }
    assert rejected.isdisjoint(common.group(1).split())


def test_every_biglinux_kernel_entry_receives_dynamic_options():
    kernel_lines = [
        line.strip()
        for line in KERNELS.splitlines()
        if line.lstrip().startswith("linux ${live_kernel}")
    ]
    assert kernel_lines
    assert all("${kopts}" in line for line in kernel_lines)


def test_basic_graphics_does_not_request_wayland():
    block = KERNELS.split('menuentry "2.4 ', 1)[1].split("\n    }", 1)[0]
    linux_line = next(line for line in block.splitlines() if "linux ${live_kernel}" in line)
    assert "nomodeset" in linux_line
    assert " wayland " not in linux_line


def test_support_codes_are_complete_unique_and_stable():
    codes = _support_codes(SUPPORT)
    assert len(codes) == len(set(codes))

    expected = [
        f"{category}.{number}"
        for category, last in EXPECTED_CATEGORY_LAST_CODE.items()
        for number in range(1, last + 1)
    ]
    assert codes == expected

    menu_codes = re.findall(r'(?:menuentry|submenu) "(\d+\.\d+) ', KERNELS)
    assert menu_codes == expected


def test_menu_ids_are_unique_and_match_support_codes():
    ids = _ids(KERNELS)
    assert len(ids) == len(set(ids))
    for code in _support_codes(SUPPORT):
        assert f"biglinux-opt-{code.replace('.', '-')}" in ids


def _menu_block(code: str) -> str:
    lines = KERNELS.splitlines()
    pattern = re.compile(rf'^(?:menuentry|submenu) "{re.escape(code)} ')
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if not pattern.match(stripped):
            continue
        indent = len(line) - len(stripped)
        closing = " " * indent + "}"
        for end in range(index + 1, len(lines)):
            if lines[end] == closing:
                return "\n".join(lines[index : end + 1])
    raise AssertionError(f"menu block not found for support code {code}")


def test_documented_parameters_match_the_numbered_menu():
    rows = re.findall(
        r'^\| \*\*(\d+\.\d+)\*\* \| [^|]+ \| [^|]+ \| `([^`]+)` \|',
        SUPPORT,
        re.MULTILINE,
    )
    assert [code for code, _parameters in rows] == _support_codes(SUPPORT)

    for code, parameters in rows:
        block = _menu_block(code)
        if parameters == "(session/driver selection)":
            expected = {
                "2.1": "wayland ${live_free}",
                "2.2": "${live_nonfree} ${live_ui}",
                "2.3": "${live_free} ${live_ui}",
            }
            assert expected[code] in block
        elif parameters == "not a Linux kernel entry":
            assert "linux /boot/memtest-efi" in block
            assert "linux16 /boot/memtest" in block
        elif parameters == "UEFI chainloader scan":
            assert "chainloader" in block
            assert "(*,gpt*)" in block and "(*,msdos*)" in block
        elif parameters == "GRUB hardware information screen":
            assert "set biglinux_show_info=true" in block
            assert "smbios --type 1" in KERNELS
            assert "probe --set biglinux_boot_filesystem --fs" in KERNELS
            assert 'System product: ${biglinux_system_product}' in KERNELS
        elif parameters == "UEFI firmware setup":
            assert "fwsetup" in block
        else:
            assert parameters in block, f"{code} does not contain {parameters!r}"


def test_first_screen_has_only_the_four_primary_actions():
    top_level = [
        line.strip()
        for line in KERNELS.splitlines()
        if line.startswith(("menuentry ", "submenu "))
    ]
    assert [re.search(r'"([^"]+)"', line).group(1) for line in top_level] == [
        "1 Start BigLinux",
        "2 Start without proprietary drivers",
        "3 Compatibility options >",
        "4 Restart computer",
    ]
    assert "--id=biglinux-opt-1-free" in top_level[1]
    assert "--id=biglinux-cat-compatibility" in top_level[2]


def test_support_submenus_have_clear_markers_and_back_is_first_entry():
    lines = KERNELS.splitlines()
    submenu_lines = [
        (index, line)
        for index, line in enumerate(lines)
        if re.match(r'\s+submenu "(?:[2-9] |9\.9 )', line)
    ]
    assert len(submenu_lines) == 9

    for index, line in submenu_lines:
        title = re.search(r'submenu "([^"]+)"', line)
        assert title and title.group(1).endswith(" >")
        assert "..." not in title.group(1)

        indent = len(line) - len(line.lstrip())
        child_prefix = " " * (indent + 4) + "menuentry "
        first_child = next(
            candidate
            for candidate in lines[index + 1 :]
            if candidate.startswith(child_prefix)
        )
        assert 'menuentry "0 Return to previous menu"' in first_child


def test_back_navigation_reloads_the_correct_parent_menu():
    assert "function menu_reload" not in GRUB
    assert "function return_to_diagnostics" not in GRUB
    assert KERNELS.count("configfile /boot/grub/grub.cfg") == 12
    assert KERNELS.count("set biglinux_return_menu=compatibility") == 8
    assert KERNELS.count("set biglinux_return_menu=diagnostics") == 2
    assert "set default=biglinux-cat-compatibility" in KERNELS
    assert 'set default="biglinux-cat-compatibility>biglinux-cat-9"' in KERNELS
    assert "export biglinux_return_menu" in KERNELS
    assert not re.search(r'biglinux-back-[^\s{]+ \{(?:.|\n)*?\bexit\b', KERNELS)


def test_kopts_preserve_all_dynamic_sources_without_forcing_blank_tokens():
    for variable in ("clinput", "bootlang", "keyboard", "timezone", "hwclock", "auto"):
        assert f'"${{{variable}}}"' in GRUB
    assert 'set auto="img_loop=${iso_path}"' in GRUB
    assert "img_dev=/dev/disk/by-uuid/${rootuuid}" in GRUB
    assert "export kopts" in GRUB


def test_legacy_hybrid_gpu_numbers_are_gone():
    assert not re.search(r"\bbignvidia=\d+\b", KERNELS)
    assert "bignvidia=integrated" in KERNELS
    assert "bignvidia=nvidia" in KERNELS


def test_memtest_and_efi_scanner_cover_bios_and_uefi():
    assert "linux /boot/memtest-efi" in KERNELS
    assert "linux16 /boot/memtest" in KERNELS
    assert "(*,gpt*)/efi/*/*.efi" in KERNELS
    assert "(*,msdos*)/efi/*/*.efi" in KERNELS



def test_every_static_menu_entry_has_a_unique_icon():
    entries = []
    for line in KERNELS.splitlines():
        match = re.match(
            r'^\s*(menuentry|submenu) "([^"]+)"(.*--id=([^\s{]+).*)$',
            line,
        )
        if not match:
            continue
        _kind, _title, options, entry_id = match.groups()
        classes = re.findall(r'--class=([^\s{]+)', options)
        assert classes and classes[0] == f"icon-{entry_id}"
        entries.append((entry_id, classes[0]))

    assert len(entries) == 216
    assert len({class_name for _entry_id, class_name in entries}) == len(entries)
    assert 'menuentry --class="${efi_class}" "${efi}"' in KERNELS

    for theme_name in ("manjaro-live", "biglinux-live"):
        icon_dir = SOURCE / "themes" / theme_name / "icons"
        icons = [icon_dir / f"{class_name}.png" for _entry_id, class_name in entries]
        assert all(icon.is_file() for icon in icons)
        digests = [hashlib.sha256(icon.read_bytes()).digest() for icon in icons]
        assert len(set(digests)) == len(digests)


def test_unique_grub_icons_are_synchronized_to_generated_profiles():
    source_icons = SOURCE / "themes/manjaro-live/icons"
    names = sorted(path.name for path in source_icons.glob("icon-biglinux-*.png"))
    assert len(names) == 248
    dynamic = [name for name in names if name.startswith("icon-biglinux-efi-detected-")]
    assert len(dynamic) == 32
    assert len(set(dynamic)) == 32
    assert 'set efi_icon_slots="icon-biglinux-efi-detected-01 ' in KERNELS
    assert '--set=1:efi_class --set=2:efi_icon_slots' in KERNELS

    for edition in EDITIONS:
        for theme_name in ("manjaro-live", "biglinux-live"):
            target = (
                ROOT
                / f"biglinux/{edition}/live-overlay/usr/share/grub/themes/{theme_name}/icons"
            )
            assert sorted(path.name for path in target.glob("icon-biglinux-*.png")) == names
            for name in names:
                assert (target / name).read_bytes() == (source_icons / name).read_bytes()

def test_theme_image_references_resolve():
    pattern = re.compile(
        r'(?:desktop-image|bar_style|highlight_style|selected_item_pixmap_style|'
        r'menu_pixmap_style|scrollbar_thumb|center_bitmap|tick_bitmap|terminal-box|'
        r'file)\s*[:=]\s*"([^"]+)"'
    )
    for edition in (None, *EDITIONS):
        if edition is None:
            themes = SOURCE / "themes"
        else:
            themes = ROOT / f"biglinux/{edition}/live-overlay/usr/share/grub/themes"
        for name in ("manjaro-live", "biglinux-live"):
            directory = themes / name
            for theme_path in directory.glob("theme*.txt"):
                text = theme_path.read_text(encoding="utf-8")
                for reference in pattern.findall(text):
                    assert list(directory.glob(reference)), (
                        f"missing theme asset: {directory / reference}"
                    )


def test_theme_selection_reports_live_firmware_and_architecture():
    assert "grub_theme_dir=/boot/grub/themes/manjaro-live" in VARIABLES
    assert 'set grub_theme_main_file="${grub_theme_dir}/theme${grub_theme_suffix}.txt"' in GRUB
    assert 'set grub_theme_support_file="${grub_theme_dir}/theme-support${grub_theme_suffix}.txt"' in GRUB
    assert 'set grub_theme_detail_file="${grub_theme_dir}/theme-detail${grub_theme_suffix}.txt"' in GRUB
    assert 'set grub_theme_info_file="${grub_theme_dir}/theme-info${grub_theme_suffix}.txt"' in GRUB
    assert 'set theme="${grub_theme_file}"' in GRUB
    assert 'set theme="${grub_theme_support_file}"' in KERNELS
    assert KERNELS.count('set theme="${grub_theme_detail_file}"') == 8
    assert KERNELS.count('set theme="${grub_theme_diagnostics_file}"') == 1
    assert "theme=($root)" not in GRUB

    contexts = {
        "": "BIGLINUX LIVE • x86_64",
        "-uefi": "BIGLINUX LIVE • UEFI • x86_64",
        "-bios": "BIGLINUX LIVE • BIOS • x86_64",
    }
    layouts = ("theme", "theme-support", "theme-detail", "theme-diagnostics", "theme-info")
    for name in ("manjaro-live", "biglinux-live"):
        directory = SOURCE / "themes" / name
        for layout in layouts:
            for suffix, context in contexts.items():
                theme = (directory / f"{layout}{suffix}.txt").read_text(
                    encoding="utf-8"
                )
                assert f'text = "{context}"' in theme
        assert (directory / "ter-u22b.pf2").is_file()
        assert (directory / "terminus-16.pf2").is_file()

def test_theme_uses_native_circular_timeout_and_solid_widescreen_layout():
    assert 'set biglinux_gfx_modes="1920x1080,1600x900,1366x768,1280x720,1024x768,800x600,auto"' in GRUB
    assert 'set gfxmode="${biglinux_gfx_modes}"' in GRUB
    assert "export grub_theme_file" in GRUB
    assert 'loadfont "${grub_theme_dir}/terminus-16.pf2"' in GRUB

    for name in ("manjaro-live", "biglinux-live"):
        directory = SOURCE / "themes" / name
        assert not (directory / "background.png").exists()
        assert (directory / "timeout_tick.png").is_file()
        assert (directory / "timeout_center.png").is_file()

        for theme_path in directory.glob("theme*.txt"):
            theme = theme_path.read_text(encoding="utf-8")
            assert 'desktop-color: "#05080d"' in theme
            assert "desktop-image:" not in theme
            assert '+ circular_progress {' in theme
            assert 'id = "__timeout__"' in theme
            assert 'center_bitmap = "timeout_center.png"' in theme
            assert 'file = "biglinux-grub.png"' in theme
            assert 'top = 5%+49' in theme
            assert 'tick_bitmap = "timeout_tick.png"' in theme
            assert 'num_ticks = 48' in theme

        main = (directory / "theme.txt").read_text(encoding="utf-8")
        overview = (directory / "theme-support.txt").read_text(encoding="utf-8")
        detail = (directory / "theme-detail.txt").read_text(encoding="utf-8")
        diagnostics = (directory / "theme-diagnostics.txt").read_text(encoding="utf-8")
        info = (directory / "theme-info.txt").read_text(encoding="utf-8")
        assert 'left = 50%-310' in main and 'width = 620' in main
        assert 'height = 250' in main and 'item_font = "Terminus Bold 22"' in main
        assert 'top = 27%' in overview and 'height = 330' in overview
        assert 'width = 780' in overview and 'item_font = "Terminus Regular 16"' in overview
        assert 'top = 25%' in detail and 'height = 62%' in detail
        assert 'scrollbar = true' in detail and 'scrollbar_width = 14' in detail
        assert 'text = "DIAGNOSTICS AND TOOLS"' in diagnostics
        assert 'top = 27%' in diagnostics and 'height = 390' in diagnostics
        assert 'top = 32%' in info and 'height = 390' in info
        assert 'item_height = 24' in info and 'item_spacing = 1' in info

def test_terminal_and_editor_use_themed_relative_geometry():
    for name in ("manjaro-live", "biglinux-live"):
        for theme_path in (SOURCE / "themes" / name).glob("theme*.txt"):
            theme = theme_path.read_text(encoding="utf-8")
            assert 'terminal-box: "terminal_*.png"' in theme
            assert 'terminal-border: "18"' in theme
            assert 'terminal-left: "9%"' in theme
            assert 'terminal-top: "22%"' in theme
            assert 'terminal-width: "82%"' in theme
            assert 'terminal-height: "68%"' in theme


def test_support_layout_transitions_preserve_numbered_navigation():
    assert 'menuentry "0 Return to main menu"' in KERNELS
    for category in range(2, 9):
        marker = f'--id=biglinux-cat-{category} {{'
        block = KERNELS.split(marker, 1)[1].split("menuentry ", 1)[0]
        assert 'set theme="${grub_theme_detail_file}"' in block
    diagnostics = KERNELS.split('--id=biglinux-cat-9 {', 1)[1].split("menuentry ", 1)[0]
    assert 'set theme="${grub_theme_diagnostics_file}"' in diagnostics
    assert 'set theme="${grub_theme_support_file}"' in KERNELS

    special = (ROOT / "sources/editions/xivastudio/special-commands.sh").read_text(
        encoding="utf-8"
    )
    assert special.count("-name 'theme*.txt'") == 2


def test_shift_disables_timeout_only_when_modifier_status_is_supported():
    assert "if keystatus; then" in GRUB
    shift_block = GRUB.split("if keystatus; then", 1)[1].split("fi\n\n", 1)[0]
    assert "if keystatus --shift; then" in shift_block
    assert "set timeout=-1" in shift_block
    assert "set timeout_style=menu" in shift_block


def test_diagnostics_expose_hardware_information_in_the_graphical_theme():
    launcher = _menu_block("9.10")
    assert "set biglinux_show_info=true" in launcher
    assert "configfile /boot/grub/grub.cfg" in launcher

    assert 'if [ "${biglinux_show_info}" = "true" ]; then' in KERNELS
    assert 'smbios --type 0 --get-string 4 --set biglinux_firmware_vendor' in KERNELS
    assert 'smbios --type 1 --get-string 5 --set biglinux_system_product' in KERNELS
    assert 'probe --set biglinux_boot_filesystem --fs "${root}"' in KERNELS
    assert 'probe --set biglinux_boot_uuid --fs-uuid "${root}"' in KERNELS
    assert 'menuentry "0 Return to diagnostics and tools"' in KERNELS
    assert 'Firmware mode: ${biglinux_firmware_mode}' in KERNELS
    assert 'Boot filesystem UUID: ${biglinux_boot_uuid}' in KERNELS
    assert "echo " not in KERNELS
    assert not re.search(r"^\s+read\s*$", KERNELS, re.MULTILINE)

    assert 'if [ "${feature_efifwsetup_check}" = "y" ]; then' in KERNELS
    assert "fwsetup --is-supported" in KERNELS
    firmware = _menu_block("9.11")
    assert "fwsetup" in firmware


def test_uefi_uses_grub_and_legacy_bios_remains_supported():
    for path in (ROOT / "sources/common/profile.conf",) + tuple(
        ROOT / f"biglinux/{edition}/profile.conf" for edition in EDITIONS
    ):
        assert 'efi_boot_loader="grub"' in path.read_text(encoding="utf-8")
    assert "linux16 /boot/memtest" in KERNELS


def test_generated_profiles_match_the_common_grub_source():
    for edition in EDITIONS:
        generated = ROOT / f"biglinux/{edition}/live-overlay/usr/share/grub"
        for name in ("defaults.cfg", "grub.cfg", "kernels.cfg", "loopback.cfg", "variable.cfg"):
            assert (generated / "cfg" / name).read_bytes() == (CFG / name).read_bytes()

        for theme_name in ("manjaro-live", "biglinux-live"):
            source_theme = SOURCE / "themes" / theme_name
            generated_theme = generated / "themes" / theme_name
            source_files = sorted(path.relative_to(source_theme) for path in source_theme.rglob("*") if path.is_file())
            generated_files = sorted(path.relative_to(generated_theme) for path in generated_theme.rglob("*") if path.is_file())
            expected_files = list(source_files)
            if edition == "xivastudio" and Path("xivastudio.png") not in expected_files:
                expected_files.append(Path("xivastudio.png"))
                expected_files.sort()
            assert generated_files == expected_files

            for relative in source_files:
                source_bytes = (source_theme / relative).read_bytes()
                generated_bytes = (generated_theme / relative).read_bytes()
                if edition == "xivastudio" and relative.name.startswith("theme") and relative.suffix == ".txt":
                    source_bytes = source_bytes.replace(
                        b'top = 5%+49\n    width = 101\n    height = 70\n    file = "biglinux-grub.png"',
                        b'top = 5%+43\n    width = 101\n    height = 82\n    file = "xivastudio.png"',
                    )
                assert generated_bytes == source_bytes


def test_build_engine_rewrites_only_the_theme_directory():
    engine = (ROOT / "build-iso/build-iso.sh").read_text(encoding="utf-8")
    assert "grub_theme_dir=/boot/grub/themes/" in engine
    assert "themes/${DISTRONAME}-live" in engine
    assert "grub_theme=" not in engine
    assert "theme=($root)" not in engine
