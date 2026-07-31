# Structural guarantees of build-iso.sh that earlier generators enforced with
# patches. Each one shipped broken ISOs when violated, so they are pinned here.

import re

from conftest import SCRIPTS

ENGINE = (SCRIPTS / "build-iso.sh").read_text(encoding="utf-8")


def test_the_image_cleanups_keep_man_pages():
    # BigLinux ships man pages on purpose; the cleanup may drop docs and
    # wallpapers but never /usr/share/man.
    cleanups = ENGINE.split("<<'CLEANUPS'", 1)[1].split("CLEANUPS", 1)[0]
    assert "usr/share/doc" in cleanups
    assert "usr/share/man" not in cleanups


def test_buildiso_runs_without_the_full_iso_flag():
    # -f makes manjaro-tools set extra=true and install every `>extra` line of
    # the profile; the published ISOs build with extra=false.
    invocations = [line for line in ENGINE.splitlines() if re.search(r"\bbuildiso -", line)]
    assert invocations, "no buildiso invocation found"
    assert all(" -f" not in line for line in invocations)


def test_the_kernel_version_check_is_disabled():
    # manjaro-tools reads a digit out of the package name and would reject
    # linux-xanmod.
    assert r"sed -i '/\${iso_kernel}/s/^/#/'" in ENGINE


def test_the_live_setup_guard_is_wired_in():
    # The black-screen fix: manjaro-live-setup verified, or the build fails.
    assert 'bash "$scriptDir/patch-live-setup.sh"' in ENGINE
    assert ENGINE.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in ENGINE


def test_negative_assertions_do_not_use_bang_grep():
    # POSIX ignores errexit for a pipeline starting with `!`, so `! grep -q ...`
    # is a no-op assertion: a failed check would let the build carry on. Every
    # negative check goes through assert_absent() instead.
    assert "assert_absent()" in ENGINE
    assert not re.search(r"^\s*!\s*grep", ENGINE, re.MULTILINE)


def test_the_branch_scripts_are_wired_in():
    assert 'bash "$scriptDir/set-manjaro-branch.sh"' in ENGINE
    assert 'bash "$scriptDir/set-biglinux-branch.sh"' in ENGINE


def test_the_build_mirror_is_configured_not_patched():
    # manjaro-tools.conf is the supported interface; a sed against
    # /usr/lib/manjaro-tools/util.sh breaks silently when upstream moves.
    assert "build_mirror=$BUILD_MIRROR" in ENGINE
    assert "manjaro-tools.conf" in ENGINE
