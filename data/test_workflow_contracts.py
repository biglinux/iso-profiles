# SPDX-License-Identifier: GPL-2.0-or-later
"""Regressions for the build/gate interface, independent of external services."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load_workflow(name: str) -> dict:
    result = subprocess.run(
        ["ruby", "-ryaml", "-rjson", "-e",
         "data = YAML.safe_load_file(ARGV[0], permitted_classes: [], aliases: false); "
         "data[\"on\"] = data.delete(true) if data.key?(true); puts JSON.generate(data)",
         str(ROOT / ".github/workflows" / name)],
        capture_output=True, text=True, timeout=10, check=True,
    )
    return json.loads(result.stdout)


class WorkflowContractsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = load_workflow("build-iso.yml")
        cls.gate = load_workflow("openqa.yml")
        cls.checks = load_workflow("openqa-nonvisual-checks.yml")

    def test_container_build_uses_bash_for_bash_arrays(self):
        self.assertEqual(self.build["jobs"]["build"].get("defaults", {}).get("run", {}).get("shell"), "bash")

    def test_caller_grants_read_permission_needed_by_reusable_gate(self):
        permissions = self.build["jobs"]["openqa"].get("permissions", {})
        self.assertEqual(permissions.get("contents"), "read")
        self.assertEqual(permissions.get("packages"), "read")

    def test_background_checksum_failure_fails_candidate_preparation(self):
        script = next(step["run"] for step in self.build["jobs"]["build"]["steps"]
                      if step.get("id") == "prepare")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "output").mkdir()
            (root / "output/candidate.iso").write_bytes(b"fixture")
            result = subprocess.run(
                ["bash", "-c", "md5sum() { return 72; }; sha256sum() { return 0; };\n" + script],
                cwd=root, env={"PATH": "/usr/bin:/bin", "GITHUB_OUTPUT": str(root / "outputs"),
                               "GITHUB_RUN_NUMBER": "1"},
                capture_output=True, text=True, timeout=10,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_ci_checks_build_caller_and_lints_every_workflow(self):
        self.assertIn(".github/workflows/build-iso.yml", self.checks["on"]["pull_request"]["paths"])
        lint = next(step["run"] for step in self.checks["jobs"]["workflow-syntax"]["steps"]
                    if "actionlint\" -color" in step.get("run", ""))
        # Without file arguments actionlint checks every workflow, so none can
        # be added and forgotten.
        self.assertEqual(lint.split(), ['"$RUNNER_TEMP/bin/actionlint"', "-color"])

    def test_both_gates_run_the_same_harness_checks(self):
        for workflow, job in ((self.checks, "harness"), (self.gate, "static")):
            runs = [step.get("run", "") for step in workflow["jobs"][job]["steps"]]
            self.assertIn("openqa/production/check-harness.sh", runs)

    def test_static_gate_installs_report_dependencies_before_tests(self):
        steps = self.gate["jobs"]["static"]["steps"]
        install = [i for i, step in enumerate(steps)
                   if "pip install" in step.get("run", "") and "requirements.txt" in step["run"]]
        tests = next(i for i, step in enumerate(steps) if "check-harness.sh" in step.get("run", ""))
        self.assertTrue(install and install[0] < tests)

    def test_manual_validation_requires_explicit_release_and_filename(self):
        inputs = self.gate["on"]["workflow_dispatch"]["inputs"]
        for key in ("iso_release_tag", "iso_filename"):
            self.assertTrue(inputs[key]["required"])
            self.assertNotIn("default", inputs[key])

    def test_profile_clone_preserves_paths_with_spaces(self):
        workflow = load_workflow("make-profiles.yml")
        script = next(step["run"] for step in workflow["jobs"]["build"]["steps"]
                      if step.get("name") == "Clone ManjaroIsoProfile")
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = "upstream profiles"
                if existing:
                    (root / target).mkdir()
                log = root / "git-call.txt"
                result = subprocess.run(
                    ["bash", "-e", "-c",
                     'git() { printf \'%s\\n\' "$PWD" "$@" >"$CALL_LOG"; };\n' + script],
                    cwd=root, env={"PATH": "/usr/bin:/bin", "manjaroProfiles": target,
                                   "CALL_LOG": str(log)},
                    capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                expected = ([str(root / target), "pull"] if existing else
                            [str(root), "clone",
                             "https://gitlab.manjaro.org/profiles-and-settings/iso-profiles.git", target])
                self.assertEqual(log.read_text().splitlines(), expected)

    def test_publish_requires_gate_and_rechecks_downloaded_candidate(self):
        publish = self.build["jobs"]["publish"]
        self.assertEqual(publish["needs"], ["build", "openqa"])
        self.assertIn("needs.openqa.result == 'success'", publish["if"])
        steps = publish["steps"]
        check = [i for i, step in enumerate(steps)
                 if "sha256sum --check" in step.get("run", "")]
        split = next(i for i, step in enumerate(steps) if step.get("id") == "split")
        self.assertTrue(check and check[0] < split)


if __name__ == "__main__":
    unittest.main()
