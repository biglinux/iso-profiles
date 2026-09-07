# Edition-specific package removals.
#
# A profile drops a package by shipping <List>-remove next to its package list,
# and that means two things, because a package arrives two ways:
#
#   1. apply_profile_removals edits the Packages-* file, so the package is
#      never asked for, and stages the list in root-overlay.
#   2. mkiso_build_iso_cleanups reads the staged list inside the chroot and
#      runs pacman -Rdd, which is the only half that can remove a package
#      pulled in as a dependency.
#
# Half two is why bigcommunity/gnome and cinnamon shipped vim: nothing lists
# it, Packages-Root lists `vi`, its only provider ex-vi-compat depends on vim.
# Editing the lists alone changes nothing there, which is exactly the state
# this engine was in.
#
# apply_profile_removals only reads PROFILE_PATH_EDITION, so the tests build a
# profile directory and call the stage directly. The cleanup half is extracted
# from the text the engine appends to manjaro-tools and run against a chroot
# stub, so no container and no root are needed.

import re
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


#--- the staging half ---------------------------------------------------------

STAGING = "root-overlay/var/lib/packages-remove"


def test_every_list_is_staged_for_the_chroot(tmp_path):
    profile = make_profile(
        tmp_path,
        {"Packages-Desktop": "firefox\n"},
        {"Desktop-remove": "vim\n", "Root-remove": "biglinux-zsh-config\n"},
    )

    run_removals(profile)

    staged = profile / STAGING
    assert (staged / "Desktop-remove").read_text(encoding="utf-8") == "vim\n"
    assert (staged / "Root-remove").read_text(encoding="utf-8") == "biglinux-zsh-config\n"


def test_a_list_without_a_package_file_is_staged_anyway(tmp_path):
    # The case that matters: nothing lists vim, so there is no Packages-* line
    # to edit, and the post-install removal is the only thing that can act.
    profile = make_profile(tmp_path, {}, {"Desktop-remove": "vim\n"})

    run_removals(profile)

    assert (profile / STAGING / "Desktop-remove").exists()


#--- the post-install half ----------------------------------------------------


def cleanups_function():
    """The mkiso_build_iso_cleanups text the engine appends to manjaro-tools."""
    source = ENGINE.read_text(encoding="utf-8")
    body = re.search(r"cat >>\"\$image\" <<'CLEANUPS'\n(.*?)\nCLEANUPS\n", source, re.DOTALL)
    assert body, "the CLEANUPS heredoc moved"
    return body.group(1)


def run_cleanups(tmp_path, installed, lists):
    """Run the cleanup over a fake image root, with chroot and pacman stubbed.

    The stub answers `pacman -Qi` from *installed* and appends every removal to
    a log, which is what the assertions read.
    """
    image = tmp_path / "image"
    staged = image / "var/lib/packages-remove"
    staged.mkdir(parents=True)
    for name, text in lists.items():
        (staged / name).write_text(text, encoding="utf-8")
    log = tmp_path / "removed.log"

    script = f"""
        chroot() {{
            shift            # the image path
            shift            # pacman
            case "$1" in
                -Qi) grep -qx "$2" "{tmp_path}/installed" ;;
                -Rdd) printf '%s\\n' "$3" >> "{log}" ;;
            esac
        }}
        {cleanups_function()}
        mkiso_build_iso_cleanups "{image}"
    """
    (tmp_path / "installed").write_text("\n".join(installed) + "\n", encoding="utf-8")
    log.touch()
    proc = subprocess.run(
        ["bash", "-c", script], check=False, capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 0, proc.stderr
    return log.read_text(encoding="utf-8").split(), image


def test_a_dependency_is_removed_after_the_install(tmp_path):
    # Nothing lists vim; it arrives through vi -> ex-vi-compat -> vim. This is
    # the step that takes it back out, and the reason the ISO shipped it.
    removed, _image = run_cleanups(
        tmp_path,
        installed=["vim", "vim-runtime", "ex-vi-compat", "firefox"],
        lists={"Desktop-remove": "ex-vi-compat\nvim\nvim-runtime\n"},
    )

    assert removed == ["ex-vi-compat", "vim", "vim-runtime"]


def test_a_package_that_is_not_installed_is_left_alone(tmp_path):
    # Each list is applied to every image, so most lines match nothing in any
    # given one. pacman -Rdd on a missing package would fail the build.
    removed, _image = run_cleanups(
        tmp_path,
        installed=["firefox"],
        lists={"Desktop-remove": "vim\nmesa-demos\n"},
    )

    assert removed == []


def test_comments_and_modifiers_are_understood_in_the_chroot(tmp_path):
    removed, _image = run_cleanups(
        tmp_path,
        installed=["vim"],
        lists={"Desktop-remove": "# editors\n\nvim >extra\n"},
    )

    assert removed == ["vim"]


def test_the_lists_do_not_reach_the_iso(tmp_path):
    # They are build instructions staged in root-overlay; leaving them behind
    # ships /var/lib/packages-remove on the installed system.
    _removed, image = run_cleanups(
        tmp_path, installed=["vim"], lists={"Desktop-remove": "vim\n"}
    )

    assert not (image / "var/lib/packages-remove").exists()


def test_the_cleanup_runs_on_the_installed_images_too(tmp_path):
    # The live image alone is not enough: what the user installs comes from
    # rootfs and desktopfs, which is where a removed package must stay removed.
    source = ENGINE.read_text(encoding="utf-8")

    assert "make_image_root()" in source
    assert "make_image_desktop()" in source
    assert source.count('mkiso_build_iso_cleanups "${path}"') == 2
