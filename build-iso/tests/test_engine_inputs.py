# Behaviour of the engine's input and validation stages.
#
# These run the real functions. `build-iso.sh` only calls main() when executed,
# not when sourced, so a test can source it, call one stage with fixtures and
# read the globals back -- without root, without a container, without pacman.
#
# This is the counterpart to test_engine_source.py, which matches the source
# text: that file pins patches whose effect only exists inside a build, this one
# covers what can actually be executed.

import subprocess

import pytest
from conftest import SCRIPTS

ENGINE = SCRIPTS / "build-iso.sh"


def run_stages(profiles_root, *, args=(), **env):
    """Source the engine, run read_inputs/validate_inputs, dump the globals.

    Returns (returncode, {variable: value}, stderr). fakeroot is what gets past
    the root check; validate_inputs rejects a normal user before anything else.
    """
    dumped = [
        "EDITION", "KERNEL", "MANJARO_BRANCH", "BIGLINUX_BRANCH",
        "BIGCOMMUNITY_BRANCH", "RELEASE_TAG", "WORK_PATH", "BUILD_MIRROR",
        "BIGLINUX_REPO_HOST", "COMMUNITY_REPO_HOST", "UNIX_TIMESTAMP",
        "DISTRONAME", "PROFILE_PATH_EDITION", "VOL_ID", "DISTRO_BRANCH",
    ]
    script = (
        f'source "{ENGINE}"\n'
        'read_inputs "$@"\n'
        "validate_inputs\n"
        + "".join(f'printf "%s=%s\\n" {v} "${v}"\n' for v in dumped)
    )
    proc = subprocess.run(
        ["fakeroot", "bash", "-c", script, "bash", *args],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(profiles_root), "PROFILES_ROOT": str(profiles_root), **env},
    )
    values = dict(
        line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line
    )
    return proc.returncode, values, proc.stderr


@pytest.fixture
def profiles(tmp_path):
    """A minimal biglinux profiles checkout: two editions, nothing else."""
    root = tmp_path / "biglinux-checkout"
    for edition in ("kde", "xivastudio"):
        (root / "biglinux" / edition).mkdir(parents=True)
    return root


@pytest.fixture
def community_profiles(tmp_path):
    # Its own directory, not the one above: a checkout carrying both layouts
    # resolves to bigcommunity, which is a different case (below).
    root = tmp_path / "community-checkout"
    (root / "bigcommunity" / "kde").mkdir(parents=True)
    return root


def test_the_defaults_are_the_documented_ones(profiles):
    code, values, stderr = run_stages(profiles, EDITION="kde")
    assert code == 0, stderr
    assert values["KERNEL"] == "lts"
    assert values["MANJARO_BRANCH"] == "stable"
    assert values["BIGLINUX_BRANCH"] == "stable"
    assert values["BIGCOMMUNITY_BRANCH"] == "stable"
    assert values["BUILD_MIRROR"] == "http://mirrors.manjaro.org/repo"
    assert values["BIGLINUX_REPO_HOST"] == "repo.biglinux.com.br"
    assert values["COMMUNITY_REPO_HOST"] == "repo.communitybig.org"


@pytest.mark.parametrize(
    "given",
    ["http://mirror.example.org/repo/", "http://mirror.example.org/repo///"],
)
def test_a_trailing_slash_is_stripped_from_the_build_mirror(profiles, given):
    # manjaro-tools appends `/$branch/$repo/$arch`, so a trailing slash here
    # becomes `repo//stable/core/...`. Behind a CDN that empty path segment caches
    # a database of its own, which goes stale and makes the build resolve package
    # versions the mirror no longer serves.
    _, values, _ = run_stages(profiles, EDITION="kde", BUILD_MIRROR=given)
    assert values["BUILD_MIRROR"] == "http://mirror.example.org/repo"


def test_the_edition_can_come_from_the_first_argument(profiles):
    code, values, stderr = run_stages(profiles, args=("xivastudio",))
    assert code == 0, stderr
    assert values["EDITION"] == "xivastudio"


def test_the_environment_wins_over_the_argument(profiles):
    # gitrepo and both CI jobs pass EDITION in the environment while the
    # quickstart passes it positionally; the environment is the documented one.
    code, values, stderr = run_stages(profiles, args=("xivastudio",), EDITION="kde")
    assert code == 0, stderr
    assert values["EDITION"] == "kde"


def test_the_volume_id_is_upper_case_and_matches_the_profile(profiles):
    # profile.conf label, kernels.cfg misolabel and manjaro-tools iso_label all
    # carry this value; a lower-case one and the live medium does not mount.
    _, values, _ = run_stages(profiles, EDITION="kde")
    assert values["VOL_ID"] == "BIGLINUX_LIVE_KDE"
    assert values["PROFILE_PATH_EDITION"] == str(profiles / "biglinux" / "kde")


def test_the_distribution_is_detected_from_the_layout(profiles, community_profiles):
    _, biglinux, _ = run_stages(profiles, EDITION="kde")
    assert biglinux["DISTRONAME"] == "biglinux"
    _, community, _ = run_stages(community_profiles, EDITION="kde")
    assert community["DISTRONAME"] == "bigcommunity"
    assert community["VOL_ID"] == "BIGCOMMUNITY_LIVE_KDE"


def test_bigcommunity_wins_when_a_checkout_carries_both(tmp_path):
    # gitrepo builds bigcommunity profiles from a checkout that may still hold
    # the biglinux ones; the community layout is tested first for that reason.
    (tmp_path / "biglinux" / "kde").mkdir(parents=True)
    (tmp_path / "bigcommunity" / "kde").mkdir(parents=True)
    _, values, _ = run_stages(tmp_path, EDITION="kde")
    assert values["DISTRONAME"] == "bigcommunity"


@pytest.mark.parametrize(
    "distro_env,branch_env,expected",
    [
        ({}, {"BIGLINUX_BRANCH": "testing"}, "testing"),
        ({}, {"BIGCOMMUNITY_BRANCH": "testing"}, "stable"),
    ],
)
def test_the_tier_branch_is_the_distributions_own(profiles, distro_env, branch_env, expected):
    # DISTRO_BRANCH decides the ISO tier and the compression level. On biglinux
    # it must follow BIGLINUX_BRANCH and ignore the community one.
    _, values, _ = run_stages(profiles, EDITION="kde", **distro_env, **branch_env)
    assert values["DISTRO_BRANCH"] == expected


@pytest.mark.parametrize(
    "env,message",
    [
        ({}, "no edition given"),
        ({"EDITION": "nosuchedition"}, "profile not found"),
        ({"EDITION": "kde", "MANJARO_BRANCH": "nope"}, "unknown Manjaro branch"),
        ({"EDITION": "kde", "BIGLINUX_BRANCH": "unstable"}, "unknown BigLinux branch"),
        ({"EDITION": "kde", "BIGCOMMUNITY_BRANCH": "nope"}, "unknown BigCommunity branch"),
        ({"EDITION": "kde", "BUILD_MIRROR": "ftp://example.org"}, "must be an http(s) URL"),
        ({"EDITION": "kde", "BUILD_MIRROR": "https://example.org/$(id)"}, "must be an http(s) URL"),
        ({"EDITION": "kde", "BUILD_MIRROR": "https://example.org/m\nbuild_mirror=evil"}, "must be an http(s) URL"),
        ({"EDITION": "kde", "DISTRONAME": "somethingelse"}, "unknown DISTRONAME"),
    ],
)
def test_bad_input_is_rejected_with_a_message(profiles, env, message):
    # Every one of these costs a second here and up to four hours if it is only
    # discovered inside the chroot.
    code, _, stderr = run_stages(profiles, **env)
    assert code != 0
    assert message in stderr


def test_a_checkout_with_no_profile_directory_is_rejected(tmp_path):
    code, _, stderr = run_stages(tmp_path, EDITION="kde")
    assert code != 0
    assert "no biglinux/ or bigcommunity/ profile directory" in stderr


def test_the_helper_scripts_receive_the_repository_host(profiles):
    # set-biglinux-branch.sh writes [biglinux-testing] into the ISO's own
    # pacman.conf and needs the same host the build installed from.
    script = (
        f'source "{ENGINE}"\n'
        'read_inputs\n'
        "bash -c 'echo \"$BIGLINUX_REPO_HOST|$MANJARO_BRANCH|$BIGLINUX_BRANCH|$PROFILE_PATH_EDITION\"'\n"
    )
    proc = subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "PROFILES_ROOT": str(profiles),
            "EDITION": "kde",
            "BIGLINUX_REPO_HOST": "repo.myfork.org",
        },
    )
    assert proc.returncode == 0, proc.stderr
    host, manjaro, biglinux, profile = proc.stdout.strip().split("|")
    assert host == "repo.myfork.org"
    assert (manjaro, biglinux) == ("stable", "stable")
    assert profile.endswith("/biglinux/kde")


def test_sourcing_the_engine_runs_no_build():
    # The guard around main() is what makes every test above possible.
    proc = subprocess.run(
        ["bash", "-c", f'source "{ENGINE}"; echo sourced'],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "sourced"
