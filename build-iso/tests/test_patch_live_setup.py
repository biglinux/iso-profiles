import subprocess
from pathlib import Path

import pytest

from conftest import SCRIPTS

SCRIPT = SCRIPTS / "patch-live-setup.sh"

# Reproduces the call manjaro-tools-iso-git r3071 makes. manjaro-live-base
# 20260722 moved live-user creation here from the boot-time manjaro-live.service,
# so it must keep running -- but on the CI build filesystem `useradd -m` could
# not copy /etc/skel across the livefs overlayfs ("Bad file descriptor") and the
# live session came up as a black screen with no plasmashell.
UNPATCHED_CONFIGURE_LIVE_IMAGE = """configure_live_image(){
    write_live_session_conf "$1"
    msg2 "Call manjaro-live-setup ..."
    chroot $1 /usr/bin/manjaro-live-setup
    chroot $1 cat /var/log/manjaro-live-setup.log
    msg "Done configuring [livefs]"
}
"""


def _patch_script(target: Path) -> str:
    """The real patch script, pointed at a test copy of util-iso-image.sh."""
    return SCRIPT.read_text(encoding="utf-8").replace(
        "/usr/lib/manjaro-tools/util-iso-image.sh", str(target)
    )


def _livefs(root: Path, *, with_binary: bool = True, username: str = "biglinux") -> Path:
    livefs = root / "livefs"
    (livefs / "usr" / "bin").mkdir(parents=True)
    (livefs / "etc" / "manjaro-tools").mkdir(parents=True)
    (livefs / "etc" / "skel" / ".config").mkdir(parents=True)
    (livefs / "etc" / "manjaro-tools" / "live.conf").write_text(f"username={username}\n", encoding="utf-8")
    (livefs / "etc" / "skel" / ".bash_logout").write_text("x\n", encoding="utf-8")
    (livefs / "etc" / "skel" / ".config" / "plasmashellrc").write_text("y\n", encoding="utf-8")
    if with_binary:
        binary = livefs / "usr" / "bin" / "manjaro-live-setup"
        binary.write_text("#!/bin/sh\n", encoding="utf-8")
        binary.chmod(0o755)
    return livefs


def _run_configure_live_image(root: Path, target: Path, livefs: Path) -> subprocess.CompletedProcess:
    """Call configure_live_image() the way manjaro-tools' run_safe() does.

    run_safe() sets `set -e`, `set -E` and an ERR trap that exits 2, which is
    what turns a failure inside configure_live_image into an aborted build.
    Without errtrace the trap would not reach into the function and the harness
    would report success on a broken livefs.
    """
    harness = root / "harness.sh"
    harness.write_text(
        'msg(){ :; }\nmsg2(){ printf "  -> $1\\n" "${@:2}"; }\n'
        'error(){ printf "==> ERROR: $1\\n" "${@:2}" >&2; }\n'
        "chroot(){ :; }\nwrite_live_session_conf(){ :; }\n"
        f"source {target}\n"
        "set -e\nset -E\ntrap 'exit 2' ERR\n"
        f"configure_live_image {livefs}\n",
        encoding="utf-8",
    )
    return subprocess.run(["bash", str(harness)], capture_output=True, text=True, check=False)


@pytest.fixture
def patched(exec_tmp_path):
    """A patched util-iso-image.sh on a filesystem where test -x works."""
    target = exec_tmp_path / "util-iso-image.sh"
    target.write_text(UNPATCHED_CONFIGURE_LIVE_IMAGE, encoding="utf-8")
    patch = exec_tmp_path / "patch-live-setup.sh"
    patch.write_text(_patch_script(target), encoding="utf-8")
    assert subprocess.run(["bash", str(patch)], check=False).returncode == 0
    return target, patch


def test_the_bare_call_is_replaced_by_the_checked_one(patched):
    target, _ = patched

    text = target.read_text(encoding="utf-8")
    assert 'mkiso_live_setup "$1"' in text
    assert "chroot $1 /usr/bin/manjaro-live-setup" not in text
    assert subprocess.run(["bash", "-n", str(target)], check=False).returncode == 0


def test_patching_twice_appends_one_definition(patched):
    target, patch = patched

    assert subprocess.run(["bash", str(patch)], check=False).returncode == 0
    assert target.read_text(encoding="utf-8").count("mkiso_live_setup() {") == 1


def test_an_empty_live_home_is_repaired_from_skel(patched, exec_tmp_path):
    target, _ = patched
    livefs = _livefs(exec_tmp_path)
    # What the CI build produced: useradd reported EBADF and left the home empty.
    (livefs / "home" / "biglinux").mkdir(parents=True)

    result = _run_configure_live_image(exec_tmp_path, target, livefs)

    assert result.returncode == 0, result.stderr
    assert "Re-syncing /etc/skel" in result.stdout
    assert (livefs / "home" / "biglinux" / ".bash_logout").is_file()
    assert (livefs / "home" / "biglinux" / ".config" / "plasmashellrc").is_file()


def test_a_missing_live_home_fails_the_build(patched, exec_tmp_path):
    target, _ = patched
    livefs = _livefs(exec_tmp_path)

    result = _run_configure_live_image(exec_tmp_path, target, livefs)

    assert result.returncode != 0
    assert "did not create /home/biglinux" in result.stderr


def test_an_unreadable_skel_fails_the_build(patched, exec_tmp_path):
    target, _ = patched
    livefs = _livefs(exec_tmp_path)
    (livefs / "home" / "biglinux").mkdir(parents=True)
    (livefs / "etc" / "skel" / ".config").chmod(0o000)
    try:
        result = _run_configure_live_image(exec_tmp_path, target, livefs)
    finally:
        (livefs / "etc" / "skel" / ".config").chmod(0o755)

    assert result.returncode != 0
    assert "could not copy /etc/skel" in result.stderr


def test_a_live_conf_without_username_fails_the_build(patched, exec_tmp_path):
    target, _ = patched
    livefs = _livefs(exec_tmp_path)
    (livefs / "home" / "biglinux").mkdir(parents=True)
    (livefs / "etc" / "manjaro-tools" / "live.conf").write_text("", encoding="utf-8")

    result = _run_configure_live_image(exec_tmp_path, target, livefs)

    assert result.returncode != 0
    assert "declares no username" in result.stderr


def test_an_older_livefs_without_the_binary_is_skipped(patched, exec_tmp_path):
    target, _ = patched
    livefs = _livefs(exec_tmp_path, with_binary=False)

    result = _run_configure_live_image(exec_tmp_path, target, livefs)

    assert result.returncode == 0, result.stderr
    assert "Skipping manjaro-live-setup" in result.stdout


def test_patch_fails_loudly_when_the_call_survives(exec_tmp_path):
    target = exec_tmp_path / "util-iso-image.sh"
    # Trailing space defeats the sed's end-of-line anchor, so the grep must reject it.
    target.write_text("configure_live_image(){\n    chroot $1 /usr/bin/manjaro-live-setup \n}\n", encoding="utf-8")
    patch = exec_tmp_path / "patch-live-setup.sh"
    patch.write_text(_patch_script(target), encoding="utf-8")

    assert subprocess.run(["bash", str(patch)], check=False).returncode != 0
