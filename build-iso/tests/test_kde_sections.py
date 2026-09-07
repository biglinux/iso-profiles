"""Upstream section changes must fail before modifying the generated profile."""

import subprocess

import pytest
from conftest import SCRIPTS

SCRIPT = SCRIPTS.parent / "sources/editions/kde/special-commands.sh"
SECTIONS = {
    "## Printing": "cups\n",
    "## Xorg Server and Graphics": "xorg-server\n",
    "## Xorg Input Drivers": "xf86-input-libinput\nxf86-input-void\n",
    "## Misc": "mesa-utils\n",
}
BASE = "# BigLinux desktop\nplasma-desktop\n"


def run_sections(tmp_path, source):
    upstream = tmp_path / "manjaro-iso-profiles/manjaro/kde/Packages-Desktop"
    upstream.parent.mkdir(parents=True)
    upstream.write_text(source, encoding="utf-8")
    generated = tmp_path / "biglinux/kde/Packages-Desktop"
    generated.parent.mkdir(parents=True)
    generated.write_text(BASE, encoding="utf-8")
    proc = subprocess.run(
        ["bash", str(SCRIPT)], cwd=tmp_path, env={"PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, check=False,
    )
    return proc, generated


def upstream_text(sections):
    return "".join(f"{header}\n{packages}\n" for header, packages in sections.items())


@pytest.mark.parametrize("final_newline", [False, True])
def test_all_sections_are_copied_and_void_is_removed(tmp_path, final_newline):
    source = upstream_text(SECTIONS)
    if not final_newline:
        source = source.rstrip("\n")
    proc, generated = run_sections(tmp_path, source)
    assert proc.returncode == 0, proc.stderr
    expected = BASE + upstream_text(SECTIONS).replace("xf86-input-void\n", "")
    assert generated.read_text(encoding="utf-8").rstrip("\n") == expected.rstrip("\n")


@pytest.mark.parametrize("header,problem", [
    (header, problem)
    for header in SECTIONS
    for problem in ["missing", "empty", "comments-only"]
    if header != "## Misc" or problem == "missing"
])
def test_invalid_sections_fail_without_partial_output(tmp_path, header, problem):
    sections = SECTIONS.copy()
    if problem == "missing":
        del sections[header]
    elif problem == "empty":
        sections[header] = ""
    else:
        sections[header] = "# no packages here\n   # another comment\n"
    proc, generated = run_sections(tmp_path, upstream_text(sections))
    assert proc.returncode != 0
    assert header in proc.stderr
    assert "Packages-Desktop" in proc.stderr
    assert generated.read_text(encoding="utf-8") == BASE


@pytest.mark.parametrize("misc", ["", "# no miscellaneous packages\n"])
def test_misc_may_be_empty_as_in_the_current_upstream_profile(tmp_path, misc):
    sections = SECTIONS.copy()
    sections["## Printing"] = ">extra manjaro-printer\n>extra gtk3-print-backends\n"
    sections["## Misc"] = misc
    proc, generated = run_sections(tmp_path, upstream_text(sections))
    assert proc.returncode == 0, proc.stderr
    expected = BASE + upstream_text(sections).replace("xf86-input-void\n", "")
    assert generated.read_text(encoding="utf-8").rstrip("\n") == expected.rstrip("\n")


def test_a_commented_reference_is_not_a_section_header(tmp_path):
    source = upstream_text(SECTIONS).replace("## Printing\n", "# renamed ## Printing\n")
    proc, generated = run_sections(tmp_path, source)
    assert proc.returncode != 0
    assert generated.read_text(encoding="utf-8") == BASE


def test_whitespace_only_lines_end_a_section(tmp_path):
    source = upstream_text(SECTIONS).replace("\n\n", "\n \t\n")
    proc, generated = run_sections(tmp_path, source)
    assert proc.returncode == 0, proc.stderr
    lines = generated.read_text(encoding="utf-8").splitlines()
    for header, packages in SECTIONS.items():
        assert lines.count(header) == 1
        for package in packages.splitlines():
            assert lines.count(package) == (0 if package == "xf86-input-void" else 1)
