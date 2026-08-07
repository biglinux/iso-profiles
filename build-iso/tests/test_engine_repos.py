# The repository list the build installs from.
#
# append_build_repos is its single owner. It used to share the job with the
# profiles' own user-repos.conf, which manjaro-tools concatenates onto the very
# file this function writes -- so [biglinux-stable] was declared twice and pacman
# refused the second copy with `could not register 'biglinux-stable' database`
# in the middle of a four-hour build.
#
# Order is the whole point of the function: pacman serves a package from the
# earliest section that has it, so these tests assert the sequence, not just the
# presence, of each repository.

import subprocess

import pytest
from conftest import SCRIPTS

ENGINE = SCRIPTS / "build-iso.sh"


def sections(tmp_path, **env):
    """Run append_build_repos over an empty file and list the sections it wrote."""
    config = tmp_path / "pacman.conf"
    config.touch()
    script = f'source "{ENGINE}"\nappend_build_repos "{config}"\n'
    proc = subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "DISTRONAME": "biglinux",
            "BIGLINUX_BRANCH": "stable",
            "BIGCOMMUNITY_BRANCH": "stable",
            "BIGLINUX_REPO_HOST": "repo.biglinux.com.br",
            "COMMUNITY_REPO_HOST": "repo.communitybig.org",
            **env,
        },
    )
    assert proc.returncode == 0, proc.stderr
    written = config.read_text(encoding="utf-8")
    return [line.strip("[]") for line in written.splitlines() if line.startswith("[")], written


def test_biglinux_stable_builds_from_update_stable_above_stable(tmp_path):
    # update-stable holds the packages held back from stable, so it has to
    # outrank it. biglinux used to receive it from user-repos.conf, which landed
    # it *below* stable and duplicated stable on the way.
    listed, _ = sections(tmp_path)
    assert listed == ["biglinux-update-stable", "biglinux-stable"]


def test_biglinux_testing_is_inserted_above_stable(tmp_path):
    # BigLinux branches are additive: testing wins where it has a package and
    # stable still answers for everything else.
    listed, _ = sections(tmp_path, BIGLINUX_BRANCH="testing")
    assert listed == ["biglinux-update-stable", "biglinux-testing", "biglinux-stable"]


def test_bigcommunity_keeps_its_own_repositories_between_the_two(tmp_path):
    listed, _ = sections(tmp_path, DISTRONAME="bigcommunity", BIGCOMMUNITY_BRANCH="testing")
    assert listed == [
        "biglinux-update-stable",
        "community-testing",
        "community-stable",
        "community-extra",
        "biglinux-stable",
    ]


def test_the_development_repository_outranks_everything(tmp_path):
    listed, _ = sections(tmp_path, UNSTABLE_REPO_MIRROR="repo.example.org/x", UNSTABLE_REPO_NAME="pr9")
    assert listed[0] == "bigiborg-pr9"


def test_no_repository_is_declared_twice(tmp_path):
    # The defect this file exists for: a name appearing in two sections is a
    # database pacman declines to register, and the build carries on without it.
    listed, _ = sections(tmp_path, DISTRONAME="bigcommunity", BIGLINUX_BRANCH="testing",
                         BIGCOMMUNITY_BRANCH="testing")
    assert len(listed) == len(set(listed))


@pytest.mark.parametrize("host_var,host", [
    ("BIGLINUX_REPO_HOST", "mirror.example.org"),
    ("COMMUNITY_REPO_HOST", "community.example.org"),
])
def test_a_fork_builds_from_its_own_host(tmp_path, host_var, host):
    # So an ISO built from a fork's repositories also updates from them.
    _, written = sections(tmp_path, DISTRONAME="bigcommunity", **{host_var: host})
    assert f"https://{host}/" in written


def test_the_arch_variable_reaches_pacman_unexpanded(tmp_path):
    # `$arch` is pacman's own variable; expanded here every Server line would
    # point at a directory that does not exist.
    _, written = sections(tmp_path)
    assert written.count("/$arch") == 2
