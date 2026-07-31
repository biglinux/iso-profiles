import subprocess
from pathlib import Path

import pytest

from conftest import SCRIPTS

SCRIPT = SCRIPTS / "set-manjaro-branch.sh"

# The three CDN entries the profile ships, each with the branch hardcoded and in
# a different position, plus the mirrorlist Include that must survive.
MIRRORCDN = """## Static mirrors from CDNs

## CDN from CDN77
Server = https://mirrors2.manjaro.org/stable/$repo/$arch

## CDN from cloudflare
Server = https://mirrors.cicku.me/manjaro/stable/$repo/$arch

## CDN from CDN77 too
Server = http://mirrors.manjaro.org/repo/stable/$repo/$arch

Include=/etc/pacman.d/mirrorlist
"""


def _profile(tmp_path: Path) -> Path:
    profile = tmp_path / "profile"
    for overlay in ("root", "live"):
        target = profile / f"{overlay}-overlay" / "etc" / "pacman.d"
        target.mkdir(parents=True)
        (target / "mirrorcdn").write_text(MIRRORCDN, encoding="utf-8")
    return profile


def _run(profile: Path, branch: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env={"PATH": "/usr/bin:/bin", "MANJARO_BRANCH": branch, "PROFILE_PATH_EDITION": str(profile)},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("branch", ["stable", "testing", "unstable"])
def test_every_cdn_entry_follows_the_branch(tmp_path, branch):
    profile = _profile(tmp_path)

    assert _run(profile, branch).returncode == 0

    for overlay in ("root", "live"):
        text = (profile / f"{overlay}-overlay/etc/pacman.d/mirrorcdn").read_text(encoding="utf-8")
        assert text.count(f"/{branch}/$repo/$arch") == 3
        # The generic mirrorlist Include has to stay, and no other branch may remain.
        assert "Include=/etc/pacman.d/mirrorlist" in text
        for other in {"stable", "testing", "unstable"} - {branch}:
            assert f"/{other}/$repo/$arch" not in text


def test_switching_branches_is_reversible(tmp_path):
    profile = _profile(tmp_path)
    conf = profile / "root-overlay/etc/pacman.d/mirrorcdn"

    for branch in ("unstable", "testing", "stable"):
        assert _run(profile, branch).returncode == 0

    assert conf.read_text(encoding="utf-8") == MIRRORCDN


def test_running_twice_does_not_duplicate(tmp_path):
    profile = _profile(tmp_path)
    conf = profile / "root-overlay/etc/pacman.d/mirrorcdn"

    _run(profile, "testing")
    first = conf.read_text(encoding="utf-8")
    _run(profile, "testing")

    assert conf.read_text(encoding="utf-8") == first


def test_an_unknown_branch_fails_the_build(tmp_path):
    result = _run(_profile(tmp_path), "experimental")

    assert result.returncode != 0
    assert "unknown Manjaro branch" in result.stderr


def test_a_profile_without_mirrorcdn_fails_the_build(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()

    result = _run(empty, "testing")

    assert result.returncode != 0
    assert "no mirrorcdn found" in result.stderr
