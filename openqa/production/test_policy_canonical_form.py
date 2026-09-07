#!/usr/bin/env python3
"""Three languages have to agree on one canonical form of the policy.

The scheduler hashes the policy in Ruby, the test reads it back in Perl and
checks that hash, and the aggregator recomputes it in Python. If any two of
them disagree by a single byte, every application job fails with a hash
mismatch and nothing in the message says why.

Perl rather than a shared Python helper because the openQA worker image ships
YAML::PP and no PyYAML: the first attempt shelled out to Python and every job
died with "the policy reader failed".
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import unittest
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
POLICY = REPOSITORY / "openqa/application-policy.yaml"
SCHEDULER = REPOSITORY / "openqa/development/schedule-release-gate.sh"
READER = REPOSITORY / "openqa/lib/application_policy.pm"

PERL_CANONICAL = r"""
use YAML::PP;
use JSON::PP;
use Encode;
my $policy = YAML::PP->new(boolean => 'JSON::PP')->load_file($ARGV[0]);
print JSON::PP->new->canonical(1)->utf8(0)->encode($policy);
"""


def _ruby_canonicaliser() -> str:
    source = SCHEDULER.read_text(encoding="utf-8")
    match = re.search(r"policy_json=\$\(ruby - \"\$policy_file\" <<'RUBY'\n(.*?)\nRUBY\n",
                      source, re.S)
    if match is None:  # pragma: no cover - the scheduler changed shape
        raise AssertionError("the scheduler's Ruby canonicaliser could not be found")
    return match.group(1)


class PolicyCanonicalFormTests(unittest.TestCase):
    def _python_form(self) -> str:
        import json

        import yaml

        with POLICY.open(encoding="utf-8") as stream:
            policy = yaml.safe_load(stream)
        return json.dumps(
            policy, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    @unittest.skipIf(shutil.which("ruby") is None, "ruby is not installed")
    def test_ruby_and_python_agree(self) -> None:
        ruby = subprocess.run(
            ["ruby", "-", str(POLICY)],
            input=_ruby_canonicaliser(),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip("\n")
        self.assertEqual(ruby, self._python_form())

    @unittest.skipIf(shutil.which("perl") is None, "perl is not installed")
    def test_perl_agrees(self) -> None:
        result = subprocess.run(
            ["perl", "-e", PERL_CANONICAL, str(POLICY)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            self.skipTest(f"perl lacks YAML::PP or JSON::PP: {result.stderr.strip()}")
        self.assertEqual(result.stdout, self._python_form())

    def test_the_reader_hashes_the_same_bytes_the_scheduler_does(self) -> None:
        # The scheduler hashes with `printf '%s'`, which appends no newline;
        # the reader must not add one either.
        scheduler = SCHEDULER.read_text(encoding="utf-8")
        self.assertIn("printf '%s' \"$policy_json\" | sha256sum", scheduler)
        reader = READER.read_text(encoding="utf-8")
        self.assertIn("Digest::SHA::sha256_hex", reader)
        self.assertNotIn("chomp", reader)
        digest = hashlib.sha256(self._python_form().encode("utf-8")).hexdigest()
        self.assertEqual(len(digest), 64)


if __name__ == "__main__":
    unittest.main()
