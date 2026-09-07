# The container and the ISO chroots install from one mirror.
#
# prepare_host used to rank five mirrors with `pacman-mirrors --fasttrack 5`
# while the chroots installed from BUILD_MIRROR. That is two package sources in
# one build: the databases are synced from a mirror the other source has not
# caught up with, the build resolves versions it then cannot fetch, and the
# failure arrives an hour in with a 404.

import subprocess

from conftest import SCRIPTS

ENGINE_PATH = SCRIPTS / "build-iso.sh"
ENGINE = ENGINE_PATH.read_text(encoding="utf-8")


def write_mirrorlist(tmp_path, **env):
    """Run write_build_mirrorlist against a file this test owns."""
    mirrorlist = tmp_path / "mirrorlist"
    script = f'source "{ENGINE_PATH}"\nwrite_build_mirrorlist "{mirrorlist}"\n'
    proc = subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "BUILD_MIRROR": "http://mirrors.manjaro.org/repo",
            "MANJARO_BRANCH": "stable",
            **env,
        },
    )
    assert proc.returncode == 0, proc.stderr
    return mirrorlist.read_text(encoding="utf-8")


def test_the_container_installs_from_the_build_mirror(tmp_path):
    written = write_mirrorlist(tmp_path)
    servers = [line for line in written.splitlines() if line.startswith("Server")]
    assert servers == ["Server = http://mirrors.manjaro.org/repo/stable/$repo/$arch"]


def test_the_branch_being_built_is_the_branch_being_synced(tmp_path):
    # A testing ISO whose container syncs stable resolves the wrong versions.
    written = write_mirrorlist(tmp_path, MANJARO_BRANCH="testing")
    assert "Server = http://mirrors.manjaro.org/repo/testing/$repo/$arch" in written


def test_an_overridden_mirror_is_used_verbatim(tmp_path):
    written = write_mirrorlist(tmp_path, BUILD_MIRROR="http://mirror.example.org/repo")
    assert "Server = http://mirror.example.org/repo/stable/$repo/$arch" in written


def test_a_previously_ranked_mirrorlist_is_replaced_not_extended(tmp_path):
    mirrorlist = tmp_path / "mirrorlist"
    mirrorlist.write_text(
        "Server = https://forksystems.mm.fcix.net/manjaro/stable/$repo/$arch\n",
        encoding="utf-8",
    )
    written = write_mirrorlist(tmp_path)
    assert "fcix" not in written


def test_the_engine_no_longer_ranks_its_own_mirrors():
    # pacman-mirrors would pick five mirrors for the container alone, which is
    # exactly the second source this function exists to remove. The comment
    # explaining that may name the command; no line may run it.
    code = [line for line in ENGINE.splitlines() if not line.lstrip().startswith("#")]
    assert not [line for line in code if "pacman-mirrors" in line]
    assert any("write_build_mirrorlist" in line for line in code)
