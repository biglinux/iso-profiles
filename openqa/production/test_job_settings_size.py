#!/usr/bin/env python3
"""No job setting may carry a file's worth of content.

openQA indexes every job setting, and PostgreSQL refuses an index row over
2704 bytes. The scheduler used to pass the whole application policy as
BIGLINUX_APPLICATION_POLICY_JSON; at 2.7 KB it was one entry short of the
limit, and adding one exclusion made every job in a release run fail to be
created at all:

    index row size 2808 exceeds btree version 4 maximum 2704
    for index "idx_value_settings"

Nothing about that error names the policy, and the run looks like six
unrelated failures, so the rule is pinned here rather than remembered.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
SCHEDULER = REPOSITORY / "openqa/development/schedule-release-gate.sh"
POLICY = REPOSITORY / "openqa/application-policy.yaml"
CANONICALISER = REPOSITORY / "openqa/production/aggregate_policy.py"

# PostgreSQL's limit for an indexed value, which is what a job setting is.
INDEX_ROW_LIMIT = 2704


class JobSettingsSizeTests(unittest.TestCase):
    def test_the_policy_is_not_passed_as_a_job_setting(self) -> None:
        scheduler = SCHEDULER.read_text(encoding="utf-8")
        self.assertNotIn("BIGLINUX_APPLICATION_POLICY_JSON", scheduler)
        # The hash still travels: it is what lets a test verify the policy in
        # its own checkout against the one the run was scheduled with.
        self.assertIn("BIGLINUX_APPLICATION_POLICY_HASH=$policy_hash", scheduler)

    def test_the_policy_would_not_fit_in_a_setting_anyway(self) -> None:
        canonical = subprocess.run(
            ["python3", str(CANONICALISER), str(POLICY)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        # If this ever shrinks below the limit again, the rule above still
        # stands: the next entry would put it back over.
        self.assertGreater(len(canonical.encode("utf-8")), 1000, canonical[:200])

    def test_every_literal_setting_stays_well_inside_the_limit(self) -> None:
        scheduler = SCHEDULER.read_text(encoding="utf-8")
        block = scheduler[scheduler.index("api_post_args=(") :]
        block = block[: block.index("\n)")]
        for line in block.splitlines():
            match = re.search(r'"?([A-Z_][A-Z0-9_]*)=([^"]*)"?\s*$', line.strip())
            if not match:
                continue
            name, value = match.groups()
            self.assertLess(
                len(value.encode("utf-8")),
                INDEX_ROW_LIMIT,
                f"{name} is close to the job setting index limit",
            )


if __name__ == "__main__":
    unittest.main()
