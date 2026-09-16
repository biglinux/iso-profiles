# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute the runner's actual finalization blocks with a fake Docker client.

These are shell/lifecycle tests, not VM tests. Only preflight and VM setup are
omitted; the traps, pipeline and report writer are the repository implementation.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest

REPOSITORY = Path(__file__).resolve().parents[2]
RUNNER = (REPOSITORY / "openqa/production/run-plan.sh").read_text()
DIE = RUNNER[RUNNER.index("die() {"):RUNNER.index("\nplan=")]
TRAPS = RUNNER[RUNNER.index("finish_report() {"):RUNNER.index("\ngate_file=")]
EXECUTOR = RUNNER[RUNNER.index("phase=isotovideo\n"):]


class RunnerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.binaries = self.root / "bin"
        self.binaries.mkdir()
        self.results = self.root / "results"
        self.results.mkdir()
        docker = self.binaries / "docker"
        docker.write_text('''#!/bin/bash
printf '%s\\n' "$*" >> "$DOCKER_CALLS"
if [[ "$1" == rm ]]; then exit 0; fi
: > "$DOCKER_STARTED"
if [[ "${FAKE_SLOW:-0}" == 1 ]]; then sleep 30; fi
printf '%s\\n' "${FAKE_OUTPUT:-backend did not start}"
exit "${FAKE_EXIT:-0}"
''')
        docker.chmod(0o755)
        self.environment = dict(os.environ, PATH=str(self.binaries) + ":" + os.environ["PATH"],
                                DOCKER_CALLS=str(self.root / "calls"),
                                DOCKER_STARTED=str(self.root / "started"))
        self.script = self.root / "runner.sh"
        self.script.write_text('''#!/bin/bash
set -euo pipefail
repository=$1
results=$2
plan=bios
iso=/missing/synthetic.iso
build=lifecycle-test
commit=
status=
phase=preflight
container_name=biglinux-plan-lifecycle-test
image=unused
isotovideo_arguments=()
docker_arguments=(run)
timeout_seconds=1
''' + DIE + TRAPS + "\n" + EXECUTOR)

    def launch(self):
        return subprocess.Popen(["bash", str(self.script), str(REPOSITORY), str(self.results)],
                                env=self.environment, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=True)

    def run_case(self, expected):
        process = self.launch()
        output, errors = process.communicate(timeout=10)
        self.assertEqual(process.returncode, expected, (output, errors))
        report = self.results / "report"
        for filename in ("RESULTADO.md", "RESULTADO.json", "run-status.json",
                         "biglinux-validation-report.html"):
            self.assertGreater((report / filename).stat().st_size, 0)
        return json.loads((report / "run-status.json").read_text())

    def broken_tee(self):
        tee = self.binaries / "tee"
        tee.write_text("#!/bin/sh\ncat >/dev/null\nexit 7\n")
        tee.chmod(0o755)

    def test_module_failure_code_survives_missing_kvm_evidence(self):
        self.environment["FAKE_EXIT"] = "101"
        self.run_case(101)
        self.assertIn("rm --force biglinux-plan-lifecycle-test", (self.root / "calls").read_text())

    def test_no_module_code_is_preserved(self):
        self.environment["FAKE_EXIT"] = "100"
        self.run_case(100)

    def test_success_without_kvm_evidence_is_not_approved(self):
        self.run_case(1)

    def test_log_failure_is_not_hidden_by_a_successful_executor(self):
        self.environment["FAKE_OUTPUT"] = "qemu -enable-kvm"
        self.broken_tee()
        self.run_case(1)

    def test_log_failure_does_not_replace_original_module_failure(self):
        self.environment["FAKE_EXIT"] = "101"
        self.broken_tee()
        self.run_case(101)

    def test_timeout_preserves_124_and_cleans_container(self):
        self.environment["FAKE_SLOW"] = "1"
        self.run_case(124)
        self.assertIn("rm --force biglinux-plan-lifecycle-test", (self.root / "calls").read_text())

    def test_term_still_cleans_container_and_writes_report(self):
        self.environment["FAKE_SLOW"] = "1"
        process = self.launch()
        try:
            deadline = time.monotonic() + 5
            while not (self.root / "started").exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue((self.root / "started").exists())
            os.killpg(process.pid, signal.SIGTERM)
            output, errors = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 143, (output, errors))
            self.assertTrue((self.results / "report/RESULTADO.json").is_file())
            self.assertIn("rm --force biglinux-plan-lifecycle-test", (self.root / "calls").read_text())
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()


if __name__ == "__main__":
    unittest.main()
