# Test fixtures for the build-iso shell scripts. Development-only: run with
# `pytest build-iso/tests/` from the repository root; nothing here ships in
# the ISO or runs during a build.

import os
import shutil
import tempfile
from pathlib import Path

import pytest

# The scripts under test live one directory up.
SCRIPTS = Path(__file__).resolve().parents[1]


def _execute_bit_is_honoured(directory: Path) -> bool:
    """Report whether `test -x` can succeed under *directory*.

    A hardened `noexec` mount clears X_OK for every file it holds, so a test
    that exercises an `[[ -x ... ]]` branch silently takes the wrong path there.
    """
    probe = directory / ".exec-probe"
    try:
        probe.write_text("#!/bin/sh\n", encoding="utf-8")
        probe.chmod(0o755)
        return os.access(probe, os.X_OK)
    except OSError:
        return False
    finally:
        probe.unlink(missing_ok=True)


def _force_remove(directory: Path) -> None:
    """Remove *directory*, including entries a test left unreadable."""
    os.chmod(directory, 0o700)
    for root, directories, _files in os.walk(directory):
        for name in directories:
            try:
                os.chmod(os.path.join(root, name), 0o700)
            except OSError:
                pass
    shutil.rmtree(directory)


@pytest.fixture
def exec_tmp_path(tmp_path):
    """A temporary directory where the execute bit is honoured."""
    if _execute_bit_is_honoured(tmp_path):
        yield tmp_path
        return

    cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "iso-profiles-tests"
    try:
        cache_root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        pytest.skip(f"no exec-capable temporary directory available: {error}")

    fallback = Path(tempfile.mkdtemp(prefix="exec-", dir=cache_root))
    try:
        if not _execute_bit_is_honoured(fallback):
            pytest.skip("no exec-capable temporary directory available")
        yield fallback
    finally:
        _force_remove(fallback)
