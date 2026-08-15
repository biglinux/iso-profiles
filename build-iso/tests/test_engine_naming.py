# The published ISO name.
#
# collect_output is the single owner of this scheme: the GitLab pipeline, the
# GitHub workflow and the Build ISO GUI all ship the file under the name it
# writes. When the rule lived in the pipeline instead, the GitHub workflow --
# which has no rename step -- published biglinux_STABLE_xivastudio_<date>.iso
# where the release is called xivastudio_<date>.iso.
#
# collect_output only touches the filesystem to find and move the ISO, so the
# tests stub find/mv and read ISO_BASENAME back.

import subprocess

import pytest
from conftest import SCRIPTS

ENGINE = SCRIPTS / "build-iso.sh"


def published_name(edition, manjaro_branch, distro_branch, *, release_tag="2026-07-31",
                   kernel="lts", kernel_name="618", distroname="biglinux", pkgs=""):
    # Assigned after the source: the engine declares KERNEL_NAME="" at the top,
    # so an environment value set before it would be wiped.
    script = f"""
        source "{ENGINE}"
        DISTRONAME={distroname}
        KERNEL_NAME="$IN_KERNEL_NAME"
        msg() {{ :; }}
        mv() {{ :; }}
        find() {{ case "$*" in *'*.iso'*) echo /cache/built.iso ;; *-pkgs.txt*) echo "$PKGS" ;; esac; }}
        collect_output
        printf '%s\\n' "$ISO_BASENAME"
    """
    proc = subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "EDITION": edition,
            "MANJARO_BRANCH": manjaro_branch,
            "REQUESTED_BRANCH": distro_branch,
            "RELEASE_TAG": release_tag,
            "KERNEL": kernel,
            "IN_KERNEL_NAME": kernel_name,
            "WORK_PATH": "/work",
            "PKGS": str(pkgs),
        },
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


@pytest.mark.parametrize(
    "manjaro,distro,expected",
    [
        # A release is stable on BOTH sides and carries no tier at all.
        ("stable", "stable", "biglinux_2026-07-31_k618.iso"),
        ("stable", "testing", "biglinux_TESTING_2026-07-31_k618.iso"),
        ("stable", "development", "biglinux_DEVELOPMENT_2026-07-31_k618.iso"),
        # Manjaro's branch is asked first: a non-stable Manjaro makes the build
        # a development one whatever our own branch says.
        ("testing", "stable", "biglinux_DEVELOPMENT_ManTesting_2026-07-31_k618.iso"),
        ("unstable", "stable", "biglinux_DEVELOPMENT_ManUnstable_2026-07-31_k618.iso"),
        ("unstable", "testing", "biglinux_DEVELOPMENT_ManUnstable_2026-07-31_k618.iso"),
    ],
)
def test_the_tier_comes_from_both_branches(manjaro, distro, expected):
    assert published_name("kde", manjaro, distro) == expected


def test_xivastudio_is_its_own_product_not_a_biglinux_flavour():
    assert published_name("xivastudio", "stable", "stable") == "xivastudio_2026-07-31_k618.iso"


def test_kde_carries_no_flavour_segment_because_it_is_the_default():
    assert published_name("kde", "stable", "stable") == "biglinux_2026-07-31_k618.iso"


@pytest.mark.parametrize("edition", ["gnome", "xfce"])
def test_any_other_edition_becomes_a_flavour_segment(edition):
    assert published_name(edition, "stable", "stable") == f"biglinux_{edition}_2026-07-31_k618.iso"


def test_the_flavour_sits_inside_the_tier_not_after_it():
    # biglinux_TESTING_gnome_..., never biglinux_gnome_TESTING_...
    assert published_name("gnome", "stable", "testing") == "biglinux_TESTING_gnome_2026-07-31_k618.iso"


def test_the_name_keeps_the_date_when_the_tag_carries_a_time():
    # The GUI sends %Y-%m-%d_%H-%M; /etc/big-release records it in full, the
    # file name does not.
    assert published_name("kde", "stable", "stable", release_tag="2026-07-31_23-59") == (
        "biglinux_2026-07-31_k618.iso"
    )


def test_a_xanmod_version_is_read_back_from_the_package_list(tmp_path):
    pkgs = tmp_path / "built-pkgs.txt"
    pkgs.write_text("linux-xanmod 7.1.4-1\n", encoding="utf-8")

    name = published_name("xivastudio", "stable", "stable", kernel="xanmod",
                          kernel_name="-xanmod", pkgs=pkgs)

    assert name == "xivastudio_2026-07-31_xanmod71.iso"


def test_bigcommunity_names_itself():
    assert published_name("kde", "stable", "stable", distroname="bigcommunity") == (
        "bigcommunity_2026-07-31_k618.iso"
    )
