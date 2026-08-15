import subprocess
from pathlib import Path

import pytest

from conftest import SCRIPTS

SCRIPT = SCRIPTS / "set-biglinux-branch.sh"
MANJARO_SCRIPT = SCRIPTS / "set-manjaro-branch.sh"

# The tail of the profile's pacman.conf: BigLinux repositories sit around the
# Manjaro ones, and only stable is ever shipped.
PACMAN_CONF = """[biglinux-update-stable]
SigLevel = PackageRequired
Server = https://repo.biglinux.com.br/update-stable/$arch

[core]
SigLevel = PackageRequired
Include = /etc/pacman.d/mirrorcdn

[extra]
SigLevel = PackageRequired
Include = /etc/pacman.d/mirrorcdn

[multilib]
SigLevel = PackageRequired
Include = /etc/pacman.d/mirrorcdn

[biglinux-stable]
SigLevel = PackageRequired
Server = https://repo.biglinux.com.br/stable/$arch
"""


def _profile(tmp_path: Path) -> Path:
    profile = tmp_path / "profile"
    for overlay in ("root", "live"):
        target = profile / f"{overlay}-overlay" / "etc"
        target.mkdir(parents=True)
        (target / "pacman.conf").write_text(PACMAN_CONF, encoding="utf-8")
    return profile


def _run(profile: Path, branch: str, host: str = "repo.biglinux.com.br") -> subprocess.CompletedProcess:
    # build-iso.sh exports all three; the script requires them rather than
    # keeping a second copy of the default host.
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env={
            "PATH": "/usr/bin:/bin",
            "BIGLINUX_BRANCH": branch,
            "BIGLINUX_REPO_HOST": host,
            "PROFILE_PATH_EDITION": str(profile),
        },
        capture_output=True,
        text=True,
        check=False,
    )


def _sections(conf: Path) -> list[str]:
    return [line for line in conf.read_text(encoding="utf-8").splitlines() if line.startswith("[")]


def test_stable_changes_nothing(tmp_path):
    profile = _profile(tmp_path)

    assert _run(profile, "stable").returncode == 0

    for overlay in ("root", "live"):
        assert (profile / f"{overlay}-overlay/etc/pacman.conf").read_text(encoding="utf-8") == PACMAN_CONF


def test_testing_is_inserted_above_stable_and_stable_stays(tmp_path):
    profile = _profile(tmp_path)

    assert _run(profile, "testing").returncode == 0

    for overlay in ("root", "live"):
        conf = profile / f"{overlay}-overlay/etc/pacman.conf"
        sections = _sections(conf)
        # Additive: stable survives, testing precedes it so testing wins.
        assert "[biglinux-stable]" in sections
        assert sections.index("[biglinux-testing]") < sections.index("[biglinux-stable]")
        # And below the Manjaro repositories, as the build-time order has it.
        assert sections.index("[multilib]") < sections.index("[biglinux-testing]")
        assert "Server = https://repo.biglinux.com.br/testing/$arch" in conf.read_text(encoding="utf-8")


def test_running_twice_inserts_one_section(tmp_path):
    profile = _profile(tmp_path)

    _run(profile, "testing")
    once = (profile / "root-overlay/etc/pacman.conf").read_text(encoding="utf-8")
    assert _run(profile, "testing").returncode == 0

    assert (profile / "root-overlay/etc/pacman.conf").read_text(encoding="utf-8") == once
    assert once.count("[biglinux-testing]") == 1


def test_an_unsupported_branch_fails_the_build(tmp_path):
    # The engine only knows stable and testing; anything else would build with
    # no BigLinux repository at all.
    result = _run(_profile(tmp_path), "unstable")

    assert result.returncode != 0
    assert "unsupported BigLinux branch" in result.stderr


def test_a_conf_without_the_stable_section_fails_the_build(tmp_path):
    profile = _profile(tmp_path)
    conf = profile / "root-overlay/etc/pacman.conf"
    conf.write_text(PACMAN_CONF.split("[biglinux-stable]")[0], encoding="utf-8")

    result = _run(profile, "testing")

    assert result.returncode != 0
    assert "no [biglinux-stable] section" in result.stderr


def test_a_profile_without_pacman_conf_fails_the_build(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()

    result = _run(empty, "testing")

    assert result.returncode != 0
    assert "no pacman.conf found" in result.stderr


@pytest.mark.parametrize("branch", ["stable", "testing"])
def test_the_manjaro_and_biglinux_scripts_are_independent(tmp_path, branch):
    # Both edit the same overlays; neither may undo the other.
    profile = _profile(tmp_path)
    for overlay in ("root", "live"):
        pacman_d = profile / f"{overlay}-overlay" / "etc" / "pacman.d"
        pacman_d.mkdir()
        (pacman_d / "mirrorcdn").write_text(
            "Server = https://mirrors2.manjaro.org/stable/$repo/$arch\nInclude=/etc/pacman.d/mirrorlist\n",
            encoding="utf-8",
        )

    assert _run(profile, branch).returncode == 0
    assert (
        subprocess.run(
            ["bash", str(MANJARO_SCRIPT)],
            env={"PATH": "/usr/bin:/bin", "MANJARO_BRANCH": "testing", "PROFILE_PATH_EDITION": str(profile)},
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        == 0
    )

    conf = (profile / "root-overlay/etc/pacman.conf").read_text(encoding="utf-8")
    mirrorcdn = (profile / "root-overlay/etc/pacman.d/mirrorcdn").read_text(encoding="utf-8")
    assert "/testing/$repo/$arch" in mirrorcdn
    assert ("[biglinux-testing]" in conf) is (branch == "testing")
    assert "[biglinux-stable]" in conf
