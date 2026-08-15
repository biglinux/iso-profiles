# Edition-specific package removals.
#
# A profile drops a package from a list it does not own by shipping
# <List>-remove next to it. bigcommunity/gnome does exactly that for vim and
# biglinux-zsh-config, and the packages shipped anyway once the build moved to
# this engine, which had no removal stage at all.
#
# apply_profile_removals only reads PROFILE_PATH_EDITION, so the tests build a
# profile directory and call the stage directly.

import subprocess

import pytest
from conftest import SCRIPTS

ENGINE = SCRIPTS / "build-iso.sh"


def run_removals(profile):
    proc = subprocess.run(
        ["bash", "-c", f'source "{ENGINE}"\nmsg() {{ :; }}\napply_profile_removals'],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "PROFILE_PATH_EDITION": str(profile)},
    )
    assert proc.returncode == 0, proc.stderr
    return proc


def make_profile(tmp_path, packages, removals, *, shared=None):
    profile = tmp_path / "edition"
    profile.mkdir()
    for name, text in packages.items():
        (profile / name).write_text(text, encoding="utf-8")
    for name, text in removals.items():
        (profile / name).write_text(text, encoding="utf-8")
    if shared:
        shared_dir = tmp_path / "shared"
        shared_dir.mkdir()
        for name, text in shared.items():
            (shared_dir / name).write_text(text, encoding="utf-8")
            (profile / name).symlink_to(f"../shared/{name}")
    return profile


def test_listed_packages_are_dropped(tmp_path):
    profile = make_profile(
        tmp_path,
        {"Packages-Desktop": "firefox\nvim\nvim-runtime\nmesa-demos\n"},
        {"Desktop-remove": "vim\nmesa-demos\n"},
    )

    run_removals(profile)

    assert (profile / "Packages-Desktop").read_text(encoding="utf-8") == "firefox\nvim-runtime\n"


def test_a_shared_list_is_unlinked_before_it_is_edited(tmp_path):
    # The bigcommunity editions share Packages-Root through a symlink into
    # shared/. Editing through the link would drop the package from every
    # edition, which is the opposite of what an edition-specific list means.
    profile = make_profile(
        tmp_path,
        {},
        {"Root-remove": "biglinux-zsh-config\n"},
        shared={"Packages-Root": "base\nbiglinux-zsh-config\n"},
    )

    run_removals(profile)

    target = profile / "Packages-Root"
    assert not target.is_symlink()
    assert target.read_text(encoding="utf-8") == "base\n"
    assert (tmp_path / "shared" / "Packages-Root").read_text(encoding="utf-8") == (
        "base\nbiglinux-zsh-config\n"
    )


def test_a_package_carrying_a_modifier_is_dropped_too(tmp_path):
    # manjaro-tools reads `pkg >extra` as a conditional install; the package is
    # still the first field, and a removal means it is not wanted either way.
    profile = make_profile(
        tmp_path,
        {"Packages-Live": "base\nvim >extra\n"},
        {"Live-remove": "vim\n"},
    )

    run_removals(profile)

    assert (profile / "Packages-Live").read_text(encoding="utf-8") == "base\n"


def test_comments_and_blank_lines_are_ignored(tmp_path):
    profile = make_profile(
        tmp_path,
        {"Packages-Mhwd": "# drivers\n\nvulkan-swrast\nmesa\n"},
        {"Mhwd-remove": "# not on this edition\n\nmesa\n"},
    )

    run_removals(profile)

    assert (profile / "Packages-Mhwd").read_text(encoding="utf-8") == (
        "# drivers\n\nvulkan-swrast\n"
    )


def test_an_emptied_list_is_still_a_file(tmp_path):
    # awk creating the output only when it prints a line would leave `mv` with
    # nothing to move and abort the build under errexit.
    profile = make_profile(
        tmp_path,
        {"Packages-Desktop": "vim\n"},
        {"Desktop-remove": "vim\n"},
    )

    run_removals(profile)

    assert (profile / "Packages-Desktop").read_text(encoding="utf-8") == ""


def test_a_stale_removal_is_reported_and_not_fatal(tmp_path):
    # The list naming a package the target no longer has is worth saying out
    # loud, but an edition that already dropped it is not a build failure.
    profile = make_profile(
        tmp_path,
        {"Packages-Desktop": "firefox\n"},
        {"Desktop-remove": "vim\n"},
    )

    proc = run_removals(profile)

    assert "vim: not in the list" in proc.stderr
    assert (profile / "Packages-Desktop").read_text(encoding="utf-8") == "firefox\n"


@pytest.mark.parametrize("missing", ["Packages-Desktop", None])
def test_a_removal_without_a_target_is_skipped(tmp_path, missing):
    profile = make_profile(tmp_path, {}, {"Desktop-remove": "vim\n"})
    if missing is None:
        (profile / "Desktop-remove").unlink()

    run_removals(profile)

    assert not (profile / "Packages-Desktop").exists()
