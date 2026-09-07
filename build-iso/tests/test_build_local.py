# build-local.sh drives the engine inside a container. These tests replace the
# container engine with a stub, so they exercise the wrapper's own logic (where
# the working copy goes, what it passes to the engine) without a 4-hour build.

import os
import shutil
import subprocess

from conftest import SCRIPTS

# A stand-in for podman: records its arguments, then produces the ISO the
# wrapper expects to find, inside whatever directory was bind-mounted to
# /build/output.
FAKE_ENGINE = """#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = info ]; then
    printf '%s\\n' "${FAKE_ROOTLESS:-false}"
    exit 0
fi
printf '%s\\n' "$@" > "$RECORD_FILE"
outputDir=
while [ $# -gt 0 ]; do
    if [ "$1" = "-v" ]; then
        case "$2" in
            *:/build/output) outputDir=${2%%:/build/output} ;;
        esac
    fi
    shift
done
test -n "$outputDir"
touch "$outputDir/fake.iso"
"""


def _make_checkout(root):
    """A minimal iso-profiles checkout: the wrapper plus one profile."""
    checkout = root / "iso-profiles"
    (checkout / "build-iso").mkdir(parents=True)
    (checkout / "biglinux" / "kde").mkdir(parents=True)
    script = checkout / "build-iso" / "build-local.sh"
    script.write_text((SCRIPTS / "build-local.sh").read_text(encoding="utf-8"), encoding="utf-8")
    script.chmod(0o755)
    return checkout


def _fake_podman(root, *, also_docker=False):
    """Put the stub first on PATH; returns where it will record its arguments."""
    bin_dir = root / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "podman"
    fake.write_text(FAKE_ENGINE, encoding="utf-8")
    fake.chmod(0o755)
    if also_docker:
        docker = bin_dir / "docker"
        docker.write_text(FAKE_ENGINE, encoding="utf-8")
        docker.chmod(0o755)
    return bin_dir, root / "podman-args"


def _run(checkout, bin_dir, record_file, *args, rootless=False, env=None):
    environment = dict(os.environ)
    environment["PATH"] = f"{bin_dir}{os.pathsep}{environment['PATH']}"
    environment["RECORD_FILE"] = str(record_file)
    environment["FAKE_ROOTLESS"] = "true" if rootless else "false"
    environment.update(env or {})
    return subprocess.run(
        ["bash", "build-iso/build-local.sh", *args],
        cwd=checkout,
        env=environment,
        capture_output=True,
        text=True,
    )


def test_the_default_output_directory_inside_the_checkout_still_builds(exec_tmp_path):
    # The documented invocation is `./build-iso/build-local.sh kde` from the
    # checkout, which puts the output in ./output -- inside the checkout. The
    # working copy therefore cannot live under the output directory: cp refuses
    # to copy a directory into itself and the build aborted before starting.
    checkout = _make_checkout(exec_tmp_path)
    bin_dir, record_file = _fake_podman(exec_tmp_path)

    result = _run(checkout, bin_dir, record_file, "kde")

    assert result.returncode == 0, result.stderr
    assert (checkout / "output" / "fake.iso").exists()

    # The engine must have been handed a copy, not the checkout itself: it edits
    # the profile files in place.
    arguments = record_file.read_text(encoding="utf-8").splitlines()
    mounts = [value for value in arguments if value.endswith(":/build/iso-profiles")]
    assert mounts, arguments
    source = mounts[0].removesuffix(":/build/iso-profiles")
    assert not source.startswith(f"{checkout}{os.sep}")
    assert source != str(checkout)

    # And the copy is cleaned up on exit.
    assert not os.path.exists(source)


def test_the_selectors_reach_the_engine_as_environment(exec_tmp_path):
    checkout = _make_checkout(exec_tmp_path)
    bin_dir, record_file = _fake_podman(exec_tmp_path)

    result = _run(checkout, bin_dir, record_file, "-m", "testing", "-b", "testing", "kde", "latest")

    assert result.returncode == 0, result.stderr
    arguments = record_file.read_text(encoding="utf-8").splitlines()
    assert "EDITION=kde" in arguments
    assert "KERNEL=latest" in arguments
    assert "MANJARO_BRANCH=testing" in arguments
    assert "BIGLINUX_BRANCH=testing" in arguments
    assert "WORK_PATH=/build/output" in arguments


def test_the_build_mirror_reaches_the_engine(exec_tmp_path):
    # A slow default mirror kills the build hours in, so -r (or BUILD_MIRROR in
    # the environment) has to arrive at the engine; without the flag nothing is
    # passed and the engine keeps its own default.
    checkout = _make_checkout(exec_tmp_path)
    bin_dir, record_file = _fake_podman(exec_tmp_path)

    result = _run(checkout, bin_dir, record_file, "-r", "http://mirror.example/repo", "kde")

    assert result.returncode == 0, result.stderr
    arguments = record_file.read_text(encoding="utf-8").splitlines()
    assert "BUILD_MIRROR=http://mirror.example/repo" in arguments


def test_without_a_mirror_the_engine_keeps_its_default(exec_tmp_path):
    checkout = _make_checkout(exec_tmp_path)
    bin_dir, record_file = _fake_podman(exec_tmp_path)

    result = _run(checkout, bin_dir, record_file, "kde")

    assert result.returncode == 0, result.stderr
    arguments = record_file.read_text(encoding="utf-8").splitlines()
    assert not [value for value in arguments if value.startswith("BUILD_MIRROR")]
    assert "" not in arguments


def test_the_image_carries_its_registry(exec_tmp_path):
    # podman resolves a short name through unqualified-search-registries, and a
    # host with no containers-registries.conf has none: it refused
    # "talesam/community-build:latest" outright rather than trying Docker Hub,
    # so a local build died before pulling anything. Docker assumes Docker Hub,
    # which is why this only ever failed under podman.
    checkout = _make_checkout(exec_tmp_path)
    (checkout / "bigcommunity" / "cinnamon").mkdir(parents=True)
    bin_dir, record_file = _fake_podman(exec_tmp_path)

    result = _run(checkout, bin_dir, record_file, "cinnamon")

    assert result.returncode == 0, result.stderr
    arguments = record_file.read_text(encoding="utf-8").splitlines()
    images = [value for value in arguments if "community-build" in value]
    assert images == ["docker.io/talesam/community-build:latest"]


def test_an_explicit_image_is_used_as_given(exec_tmp_path):
    checkout = _make_checkout(exec_tmp_path)
    bin_dir, record_file = _fake_podman(exec_tmp_path)

    result = _run(checkout, bin_dir, record_file, "-i", "localhost/my-build:dev", "kde")

    assert result.returncode == 0, result.stderr
    assert "localhost/my-build:dev" in record_file.read_text(encoding="utf-8").splitlines()


def test_the_container_runs_as_root(exec_tmp_path):
    # Both build images declare USER builduser and the engine refuses to run as
    # anyone else ("must run as root"), so a local build failed at the first
    # check, after pulling several GB.
    checkout = _make_checkout(exec_tmp_path)
    bin_dir, record_file = _fake_podman(exec_tmp_path)

    result = _run(checkout, bin_dir, record_file, "kde")

    assert result.returncode == 0, result.stderr
    arguments = record_file.read_text(encoding="utf-8").splitlines()
    assert "--user" in arguments
    assert arguments[arguments.index("--user") + 1] == "0:0"


def test_rootless_podman_hands_the_build_to_docker(exec_tmp_path):
    # Rootless podman cannot mount devtmpfs in the build chroot, and
    # manjaro-tools only fails at that point, long after the download. When
    # docker is available the wrapper has to pick it instead.
    checkout = _make_checkout(exec_tmp_path)
    bin_dir, record_file = _fake_podman(exec_tmp_path, also_docker=True)

    result = _run(checkout, bin_dir, record_file, "kde", rootless=True)

    assert result.returncode == 0, result.stderr
    assert "using docker" in result.stdout
    assert (checkout / "output" / "fake.iso").exists()


def test_rootless_podman_without_docker_stops_before_downloading(exec_tmp_path):
    # A PATH of its own: the machine running the tests very likely has a real
    # docker, and the point here is the host that only offers rootless podman.
    checkout = _make_checkout(exec_tmp_path)
    bin_dir, record_file = _fake_podman(exec_tmp_path)
    only_bin = exec_tmp_path / "only-podman"
    only_bin.mkdir()
    for tool in ("bash", "cp", "ls", "mkdir", "mktemp", "rm", "sed", "dirname"):
        (only_bin / tool).symlink_to(shutil.which(tool))
    (only_bin / "podman").symlink_to(bin_dir / "podman")

    environment = dict(os.environ)
    environment["PATH"] = str(only_bin)
    environment["RECORD_FILE"] = str(record_file)
    environment["FAKE_ROOTLESS"] = "true"
    result = subprocess.run(
        ["bash", "build-iso/build-local.sh", "kde"],
        cwd=checkout,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "rootless" in result.stderr
    assert not record_file.exists()


def test_rootful_podman_still_builds(exec_tmp_path):
    checkout = _make_checkout(exec_tmp_path)
    bin_dir, record_file = _fake_podman(exec_tmp_path)

    result = _run(checkout, bin_dir, record_file, "kde")

    assert result.returncode == 0, result.stderr
    assert (checkout / "output" / "fake.iso").exists()


def test_the_chroot_work_directories_are_mounted_off_overlayfs(exec_tmp_path):
    # manjaro-tools builds its chroots with overlayfs, which refuses an upperdir
    # that already sits on overlayfs - the container's own filesystem. The
    # GitHub job mounts the runner's scratch disk over these two paths; a local
    # build has to do the same or it dies after downloading every package.
    checkout = _make_checkout(exec_tmp_path)
    bin_dir, record_file = _fake_podman(exec_tmp_path)

    result = _run(checkout, bin_dir, record_file, "kde")

    assert result.returncode == 0, result.stderr
    arguments = record_file.read_text(encoding="utf-8").splitlines()
    mounted = [value for value in arguments if ":" in value]
    assert any(value.endswith(":/var/lib/manjaro-tools/buildiso") for value in mounted), mounted
    assert any(value.endswith(":/var/cache/manjaro-tools/iso") for value in mounted), mounted


def test_the_work_directory_stays_out_of_the_checkout(exec_tmp_path):
    # The chroots contain device nodes, and the openQA gate copies the whole
    # checkout into its container: a work directory under ./output makes that
    # copy fail and takes the gate down with it.
    checkout = _make_checkout(exec_tmp_path)
    bin_dir, record_file = _fake_podman(exec_tmp_path)
    cache = exec_tmp_path / "cache-home"

    result = _run(checkout, bin_dir, record_file, "kde", env={"XDG_CACHE_HOME": str(cache)})

    assert result.returncode == 0, result.stderr
    arguments = record_file.read_text(encoding="utf-8").splitlines()
    mounted = [value for value in arguments if ":/var/" in value]
    assert any(value.startswith(f"{cache}/biglinux-build-iso/") for value in mounted), mounted
    assert not any(str(checkout) in value for value in mounted), mounted


def test_the_work_directory_can_be_placed_elsewhere(exec_tmp_path):
    checkout = _make_checkout(exec_tmp_path)
    bin_dir, record_file = _fake_podman(exec_tmp_path)
    elsewhere = exec_tmp_path / "scratch"

    result = _run(checkout, bin_dir, record_file, "-w", str(elsewhere), "kde")

    assert result.returncode == 0, result.stderr
    arguments = record_file.read_text(encoding="utf-8").splitlines()
    assert f"{elsewhere}/buildiso:/var/lib/manjaro-tools/buildiso" in arguments, arguments
