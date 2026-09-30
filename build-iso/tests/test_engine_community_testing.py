# COMMUNITY_TESTING: [community-testing] in a biglinux build.
#
# Off by default. When on, the community testing repository -- testing alone,
# never community-stable or community-extra -- sits right above the BigLinux
# repositories: above [biglinux-testing] when the build has it, above
# [biglinux-stable] otherwise. Both the build and the installed system get it,
# and the installed system gets community-keyring to verify it with.

import shutil
import subprocess

import pytest
from conftest import SCRIPTS

ENGINE = SCRIPTS / "build-iso.sh"
KDE_PACMAN_CONF = SCRIPTS.parent / "biglinux" / "kde" / "root-overlay" / "etc" / "pacman.conf"

BASE_ENV = {
    "PATH": "/usr/bin:/bin",
    "DISTRONAME": "biglinux",
    "BIGLINUX_BRANCH": "stable",
    "BIGCOMMUNITY_BRANCH": "stable",
    "BIGLINUX_REPO_HOST": "repo.biglinux.com.br",
    "COMMUNITY_REPO_HOST": "repo.communitybig.org",
}


def section_names(text):
    return [
        line.strip("[]")
        for line in text.splitlines()
        if line.startswith("[") and line.strip("[]") != "options"
    ]


def build_sections(tmp_path, **env):
    config = tmp_path / "pacman.conf"
    config.write_text("", encoding="utf-8")
    proc = subprocess.run(
        ["bash", "-c", f'source "{ENGINE}"\nappend_build_repos "{config}"\n'],
        check=False,
        capture_output=True,
        text=True,
        env={**BASE_ENV, **env},
    )
    assert proc.returncode == 0, proc.stderr
    return section_names(config.read_text(encoding="utf-8"))


@pytest.mark.parametrize("branch,expected", [
    ("stable", ["biglinux-update-stable", "community-testing", "biglinux-stable"]),
    ("testing", ["biglinux-update-stable", "community-testing", "biglinux-testing", "biglinux-stable"]),
])
def test_the_build_puts_community_testing_above_the_biglinux_repositories(tmp_path, branch, expected):
    assert build_sections(tmp_path, BIGLINUX_BRANCH=branch, COMMUNITY_TESTING="true") == expected


def test_the_build_is_unchanged_when_off(tmp_path):
    assert build_sections(tmp_path, COMMUNITY_TESTING="false") == ["biglinux-update-stable", "biglinux-stable"]
    # Unset is off too: callers that predate the option send nothing.
    assert build_sections(tmp_path) == ["biglinux-update-stable", "biglinux-stable"]


def test_a_bigcommunity_build_is_not_affected(tmp_path):
    listed = build_sections(tmp_path, DISTRONAME="bigcommunity", BIGCOMMUNITY_BRANCH="testing",
                            COMMUNITY_TESTING="true")
    assert listed.count("community-testing") == 1


def installed_profile(tmp_path, **env):
    """The kde profile's real pacman.conf, run through configure_profile's repository steps."""
    edition = tmp_path / "biglinux" / "kde"
    etc = edition / "root-overlay" / "etc"
    etc.mkdir(parents=True)
    shutil.copy(KDE_PACMAN_CONF, etc / "pacman.conf")
    (edition / "Packages-Root").write_text("base\n  biglinux-keyring\n", encoding="utf-8")
    script = (
        f'source "{ENGINE}"\n'
        f'bash "{SCRIPTS}/set-biglinux-branch.sh"\n'
        'if [[ "$COMMUNITY_TESTING" == "true" ]]; then add_community_testing_to_profile; fi\n'
    )
    proc = subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env={**BASE_ENV, "PROFILE_PATH_EDITION": str(edition), "COMMUNITY_TESTING": "false", **env},
    )
    written = (etc / "pacman.conf").read_text(encoding="utf-8")
    packages = (edition / "Packages-Root").read_text(encoding="utf-8").split()
    return proc, section_names(written), written, packages


@pytest.mark.parametrize("branch,expected_tail", [
    ("stable", ["community-testing", "biglinux-stable"]),
    ("testing", ["community-testing", "biglinux-testing", "biglinux-stable"]),
])
def test_the_installed_system_gets_community_testing_above_biglinux(tmp_path, branch, expected_tail):
    proc, listed, _, _ = installed_profile(tmp_path, BIGLINUX_BRANCH=branch, COMMUNITY_TESTING="true")
    assert proc.returncode == 0, proc.stderr
    # update-stable and Manjaro's repositories keep their place at the top.
    assert listed[0] == "biglinux-update-stable"
    assert listed[-len(expected_tail):] == expected_tail
    assert "community-stable" not in listed
    assert "community-extra" not in listed


def test_the_installed_section_is_well_formed(tmp_path):
    _, _, written, _ = installed_profile(tmp_path, COMMUNITY_TESTING="true")
    assert ("[community-testing]\nSigLevel = PackageRequired\n"
            "Server = https://repo.communitybig.org/testing/$arch\n\n[biglinux-stable]") in written


def test_the_installed_system_gets_the_keyring(tmp_path):
    _, _, _, packages = installed_profile(tmp_path, COMMUNITY_TESTING="true")
    assert "community-keyring" in packages
    assert "biglinux-keyring" in packages


def test_the_installed_system_is_unchanged_when_off(tmp_path):
    proc, listed, written, packages = installed_profile(tmp_path, BIGLINUX_BRANCH="testing")
    assert proc.returncode == 0, proc.stderr
    assert "community-testing" not in listed
    assert "[community" not in written
    assert "community-keyring" not in packages


def test_running_twice_does_not_declare_it_twice(tmp_path):
    edition = tmp_path / "biglinux" / "kde"
    installed_profile(tmp_path, COMMUNITY_TESTING="true")
    conf = edition / "root-overlay" / "etc" / "pacman.conf"
    subprocess.run(
        ["bash", "-c", f'source "{ENGINE}"\nadd_community_testing_to_profile\n'],
        check=True,
        capture_output=True,
        env={**BASE_ENV, "PROFILE_PATH_EDITION": str(edition), "COMMUNITY_TESTING": "true"},
    )
    assert section_names(conf.read_text(encoding="utf-8")).count("community-testing") == 1


def validate(tmp_path, **env):
    root = tmp_path / "checkout"
    for distro in ("biglinux", "bigcommunity"):
        (root / distro / "kde").mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        ["fakeroot", "bash", "-c", f'source "{ENGINE}"\nread_inputs\nvalidate_inputs\necho "CT=$COMMUNITY_TESTING"\n'],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(root), "PROFILES_ROOT": str(root), "EDITION": "kde", **env},
    )


def test_the_default_is_off(tmp_path):
    proc = validate(tmp_path, DISTRONAME="biglinux")
    assert proc.returncode == 0, proc.stderr
    assert "CT=false" in proc.stdout


@pytest.mark.parametrize("env,message", [
    ({"DISTRONAME": "biglinux", "COMMUNITY_TESTING": "yes"}, "COMMUNITY_TESTING must be true or false"),
    ({"DISTRONAME": "bigcommunity", "COMMUNITY_TESTING": "true"}, "COMMUNITY_TESTING is for biglinux builds"),
])
def test_bad_values_are_rejected_before_the_build(tmp_path, env, message):
    proc = validate(tmp_path, **env)
    assert proc.returncode != 0
    assert message in proc.stderr
