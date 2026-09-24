# The kernel selector.
#
# resolve_kernel turns a selector into the package the KERNEL placeholders are
# filled with. big is the BigCommunity kernel, linux-big: its modules
# (linux-big-headers, -broadcom-wl, -nvidia-580xx, ...) sit in the community
# repositories, so only a bigcommunity build can install it.

import subprocess

from conftest import SCRIPTS

ENGINE = SCRIPTS / "build-iso.sh"


def resolve(kernel, distroname):
    script = f"""
        source "{ENGINE}"
        DISTRONAME={distroname}
        msg() {{ :; }}
        resolve_kernel
        printf '%s\\n' "$KERNEL_NAME"
    """
    return subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "KERNEL": kernel},
    )


def test_big_resolves_to_linux_big_on_bigcommunity():
    proc = resolve("big", "bigcommunity")

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "-big"


def test_big_is_refused_on_biglinux_before_anything_is_built():
    proc = resolve("big", "biglinux")

    assert proc.returncode != 0
    assert "bigcommunity" in proc.stdout + proc.stderr


def test_an_unknown_selector_lists_big_among_the_choices():
    proc = resolve("bigger", "bigcommunity")

    assert proc.returncode != 0
    assert "or big" in proc.stdout + proc.stderr
