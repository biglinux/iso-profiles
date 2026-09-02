# The distribution's release and codename must survive the build.
#
# manjaro-tools' configure_lsb_release rewrites DISTRIB_RELEASE and
# DISTRIB_CODENAME inside the chroot with ${dist_release}/${dist_codename},
# which default to the build host's own /etc/lsb-release. A BigCommunity ISO
# built on a Manjaro host therefore shipped `26.1.1 / Bian-May` where
# community-release had installed `1.7.0 / Powerful`, and that is what
# comm-release showed on the live system.
#
# keep_release_identity renames upstream's function and puts a wrapper in front
# of it. The tests extract that wrapper from the engine and run it against a
# fake chroot, so no container and no root are needed.

import re
import subprocess
from pathlib import Path

import pytest

from conftest import SCRIPTS

ENGINE = SCRIPTS / "build-iso.sh"

UPSTREAM = """\
configure_lsb_release(){
    msg2 "Configuring lsb-release"
    sed -i -e "s/^.*DISTRIB_RELEASE.*/DISTRIB_RELEASE=${dist_release}/" $1/etc/lsb-release
    sed -i -e "s/^.*DISTRIB_CODENAME.*/DISTRIB_CODENAME=${dist_codename}/" $1/etc/lsb-release
}
"""

DISTRO_LSB = (
    'DISTRIB_ID="BigCommunity based in Manjaro Linux"\n'
    'DISTRIB_RELEASE="1.7.0"\n'
    'DISTRIB_CODENAME="Powerful"\n'
    'DISTRIB_DESCRIPTION="BigCommunity"\n'
)


def patch(tmp_path, image_text=UPSTREAM):
    """Run keep_release_identity over a stub util-iso-image.sh."""
    image = tmp_path / "util-iso-image.sh"
    image.write_text(image_text, encoding="utf-8")
    proc = subprocess.run(
        ["bash", "-c", f'source "{ENGINE}"\nmsg() {{ :; }}\nkeep_release_identity "{image}"'],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    return proc, image


def make_chroot(tmp_path, *, owned):
    """A chroot holding /etc/lsb-release, optionally owned by a package."""
    chroot = tmp_path / "chroot"
    (chroot / "etc").mkdir(parents=True)
    (chroot / "etc/lsb-release").write_text(DISTRO_LSB, encoding="utf-8")

    local = chroot / "var/lib/pacman/local"
    for name, files in (
        ("filesystem-2026.01-1", "%FILES%\netc/\netc/fstab\n"),
        ("community-release-26.09.01-1753", "%FILES%\netc/\netc/lsb-release\n"),
    ):
        if name.startswith("community-release") and not owned:
            continue
        package = local / name
        package.mkdir(parents=True)
        (package / "files").write_text(files, encoding="utf-8")
    return chroot


def configure(image, chroot, entry="configure_lsb_release"):
    """Call the patched wrapper the way manjaro-tools does."""
    script = f"""
        msg2() {{ printf '%s\\n' "$1"; }}
        dist_release=26.1.1
        dist_codename=Bian-May
        source "{image}"
        {entry} "{chroot}"
    """
    proc = subprocess.run(
        ["bash", "-c", script], check=False, capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 0, proc.stderr
    return proc, (chroot / "etc/lsb-release").read_text(encoding="utf-8")


def test_a_packaged_lsb_release_is_left_alone(tmp_path):
    # The regression: community-release owns the file, so its values stay.
    _proc, image = patch(tmp_path)
    chroot = make_chroot(tmp_path, owned=True)

    proc, text = configure(image, chroot)

    assert text == DISTRO_LSB
    assert "Bian-May" not in text
    assert "an installed package owns it" in proc.stdout


def test_an_unowned_lsb_release_still_gets_the_manjaro_values(tmp_path):
    # No package owns the file, so there is no identity to protect and
    # upstream's behaviour is kept.
    _proc, image = patch(tmp_path)
    chroot = make_chroot(tmp_path, owned=False)

    _proc, text = configure(image, chroot)

    assert "DISTRIB_RELEASE=26.1.1" in text
    assert "DISTRIB_CODENAME=Bian-May" in text
    assert 'DISTRIB_DESCRIPTION="BigCommunity"' in text


def test_upstream_is_renamed_not_deleted(tmp_path):
    _proc, image = patch(tmp_path)
    text = image.read_text(encoding="utf-8")

    assert "mkiso_upstream_configure_lsb_release(){" in text
    assert text.count("configure_lsb_release() {") == 1


def test_a_moved_upstream_function_fails_the_build(tmp_path):
    # Patching by function signature: if manjaro-tools renames or reformats it,
    # the build must stop instead of silently shipping the host's values again.
    proc, _image = patch(tmp_path, image_text="configure_lsb_release() {\n    :\n}\n")

    assert proc.returncode != 0
    assert "configure_lsb_release" in proc.stderr


def test_the_patch_runs_during_the_build(tmp_path):
    source = ENGINE.read_text(encoding="utf-8")

    assert re.search(r"^\s+keep_release_identity \"\$image\"$", source, re.MULTILINE)


# manjaro-tools renamed the function.
#
# The stub above carries the historic name, so these tests kept passing while
# the real package moved on: a container with manjaro-tools 5c97abe aborted the
# build with "expected '^configure_lsb_release(){'". The wrapper now discovers
# whichever name is present, and both are exercised here so neither can regress
# unnoticed.

CURRENT_UPSTREAM = """\
configure_lsb(){
    msg2 "Configuring lsb-release"
    sed -i -e "s/^.*DISTRIB_RELEASE.*/DISTRIB_RELEASE=${dist_release}/" $1/etc/lsb-release
    sed -i -e "s/^.*DISTRIB_CODENAME.*/DISTRIB_CODENAME=${dist_codename}/" $1/etc/lsb-release
}
"""


def test_the_current_upstream_name_is_wrapped(tmp_path):
    proc, image = patch(tmp_path, CURRENT_UPSTREAM)

    assert proc.returncode == 0, proc.stderr
    text = image.read_text(encoding="utf-8")
    assert "mkiso_upstream_configure_lsb(){" in text
    assert "configure_lsb() {" in text


def test_a_packaged_lsb_release_is_left_alone_under_the_current_name(tmp_path):
    _proc, image = patch(tmp_path, CURRENT_UPSTREAM)
    chroot = make_chroot(tmp_path, owned=True)

    _proc, text = configure(image, chroot, entry="configure_lsb")

    assert text == DISTRO_LSB
    assert "Bian-May" not in text


def test_an_unowned_lsb_release_still_gets_the_manjaro_values(tmp_path):
    # With no package owning the file there is no identity to preserve, so
    # upstream's behaviour has to survive the rename too.
    _proc, image = patch(tmp_path, CURRENT_UPSTREAM)
    chroot = make_chroot(tmp_path, owned=False)

    _proc, text = configure(image, chroot, entry="configure_lsb")

    assert "26.1.1" in text
    assert "Bian-May" in text


def test_a_missing_function_fails_loudly(tmp_path):
    # Better a named failure here than a silent one that ships the host's
    # release inside the ISO.
    proc, _image = patch(tmp_path, "configure_something_else(){\n    :\n}\n")

    assert proc.returncode != 0
    assert "no configure_lsb or configure_lsb_release" in proc.stderr


def test_the_real_manjaro_tools_function_is_recognised(tmp_path):
    # The check the stubs cannot make: if manjaro-tools is installed here, its
    # actual function name must be one this engine knows how to wrap.
    installed = Path("/usr/lib/manjaro-tools/util-iso-image.sh")
    if not installed.is_file():
        pytest.skip("manjaro-tools is not installed on this host")

    text = installed.read_text(encoding="utf-8")
    assert re.search(r"^configure_lsb(_release)?\(\)\{", text, re.MULTILINE), (
        "manjaro-tools renamed the lsb-release function again; teach "
        "keep_release_identity the new name"
    )
