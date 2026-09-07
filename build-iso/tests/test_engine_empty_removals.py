"""An empty opt-out file must never empty an edition's package list."""

import subprocess

import pytest
from conftest import SCRIPTS


@pytest.mark.parametrize("kind", ["Root", "Live", "Mhwd", "Desktop"])
@pytest.mark.parametrize("shared", [False, True], ids=["regular", "symlink"])
@pytest.mark.parametrize("removals", ["", "\n \t\n", "# nothing to remove\n"],
                         ids=["zero-bytes", "whitespace", "comments"])
def test_empty_removals_preserve_packages(tmp_path, kind, shared, removals):
    profile = tmp_path / "edition"
    profile.mkdir()
    packages = "# selected packages\n\nbase\nfirefox\nvim >extra\nlibfoo++\n"
    target = profile / f"Packages-{kind}"
    shared_target = tmp_path / "shared-packages"
    if shared:
        shared_target.write_text(packages, encoding="utf-8")
        target.symlink_to(shared_target)
    else:
        target.write_text(packages, encoding="utf-8")
    (profile / f"{kind}-remove").write_text(removals, encoding="utf-8")

    proc = subprocess.run(
        ["bash", "-c", 'source "$1"; apply_profile_removals',
         "test", str(SCRIPTS / "build-iso.sh")],
        env={"PATH": "/usr/bin:/bin", "PROFILE_PATH_EDITION": str(profile)},
        capture_output=True, text=True, check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert target.read_text(encoding="utf-8") == packages
    assert not target.is_symlink()
    if shared:
        assert shared_target.read_text(encoding="utf-8") == packages
    staged = profile / "root-overlay/var/lib/packages-remove" / f"{kind}-remove"
    assert staged.read_text(encoding="utf-8") == removals
    assert not target.with_name(target.name + ".new").exists()
