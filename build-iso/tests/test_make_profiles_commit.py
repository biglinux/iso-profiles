"""Execute the real workflow commit step in an isolated Git repository."""

import os
import subprocess
import textwrap

import pytest
from conftest import SCRIPTS


def commit_step():
    # Extract just this named literal run block, without adding a YAML dependency
    # to the shell-script test suite. A moved/renamed step fails loudly here.
    workflow = (SCRIPTS.parent / ".github/workflows/make-profiles.yml").read_text(
        encoding="utf-8"
    )
    step = workflow.split("      - name: Update github\n", 1)[1]
    step = step.split("\n      - name:", 1)[0]
    return textwrap.dedent(step.split("        run: |\n", 1)[1])


def git(repo, env, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], env=env,
        capture_output=True, text=True, check=True,
    ).stdout.strip()


@pytest.fixture
def repository(exec_tmp_path):
    repo = exec_tmp_path / "repo"
    repo.mkdir()
    env = {
        "PATH": "/usr/bin:/bin", "HOME": str(exec_tmp_path), "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
    }
    git(repo, env, "init", "-q")
    git(repo, env, "config", "user.name", "Regression test")
    git(repo, env, "config", "user.email", "test@example.invalid")
    git(repo, env, "config", "commit.gpgsign", "false")
    git(repo, env, "config", "core.hooksPath", str(repo / ".git/hooks"))
    (repo / "Packages-Root").write_text("base\n", encoding="utf-8")
    git(repo, env, "add", "--all")
    git(repo, env, "commit", "-qm", "initial")
    return repo, env


def run_step(repo, env):
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", commit_step()],
        cwd=repo, env=env, capture_output=True, text=True, check=False,
    )


def test_no_changes_is_a_successful_noop(repository):
    repo, env = repository
    before = git(repo, env, "rev-parse", "HEAD")
    proc = run_step(repo, env)
    assert proc.returncode == 0, proc.stderr
    assert git(repo, env, "rev-parse", "HEAD") == before
    assert git(repo, env, "status", "--porcelain") == ""


@pytest.mark.parametrize("change", ["modify", "add", "delete"])
def test_generated_changes_are_committed(repository, change):
    repo, env = repository
    before = git(repo, env, "rev-parse", "HEAD")
    if change == "modify":
        (repo / "Packages-Root").write_text("base\nfirefox\n", encoding="utf-8")
    elif change == "add":
        (repo / "Packages-Desktop").write_text("plasma-desktop\n", encoding="utf-8")
    else:
        (repo / "Packages-Root").unlink()

    proc = run_step(repo, env)

    assert proc.returncode == 0, proc.stderr
    assert git(repo, env, "rev-parse", "HEAD") != before
    assert git(repo, env, "log", "-1", "--format=%s") == "new profile"
    assert git(repo, env, "status", "--porcelain") == ""


def test_a_real_commit_failure_is_not_reported_as_success(repository):
    repo, env = repository
    before = git(repo, env, "rev-parse", "HEAD")
    (repo / "Packages-Root").write_text("base\nfirefox\n", encoding="utf-8")
    hook = repo / ".git/hooks/pre-commit"
    hook.write_text(
        "#!/bin/sh\necho 'intentional pre-commit failure' >&2\nexit 23\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)

    proc = run_step(repo, env)

    assert "intentional pre-commit failure" in proc.stderr
    assert proc.returncode != 0
    assert git(repo, env, "rev-parse", "HEAD") == before
    assert git(repo, env, "diff", "--cached", "--name-only") == "Packages-Root"


def test_a_diff_error_is_not_treated_as_a_change(repository):
    repo, env = repository
    before = git(repo, env, "rev-parse", "HEAD")
    (repo / "Packages-Root").write_text("base\nfirefox\n", encoding="utf-8")
    bindir = repo.parent / "bin"
    bindir.mkdir()
    shim = bindir / "git"
    shim.write_text(
        '#!/bin/sh\nif [ "$1" = diff ]; then\n'
        "  echo 'intentional diff failure' >&2\n  exit 128\nfi\n"
        'exec /usr/bin/git "$@"\n', encoding="utf-8",
    )
    shim.chmod(0o755)

    proc = run_step(repo, {**env, "PATH": f"{bindir}:{env['PATH']}"})

    assert proc.returncode == 128
    assert "intentional diff failure" in proc.stderr
    assert git(repo, env, "rev-parse", "HEAD") == before
