# SPDX-License-Identifier: GPL-2.0-or-later
"""Validate the checked-in application policy used by the real workflow."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).parents[1]
POLICY = ROOT / "openqa" / "application-policy.yaml"
AGGREGATOR_PATH = ROOT / "openqa" / "production" / "aggregate-application-results.py"
SPEC = importlib.util.spec_from_file_location("application_aggregator", AGGREGATOR_PATH)
assert SPEC and SPEC.loader
AGGREGATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AGGREGATOR)


def load_policy() -> dict:
    # Production converts the policy with Ruby's safe YAML loader. Test the same
    # parser and reject aliases/classes instead of relying on a CI-only parser.
    program = (
        "require 'yaml'; require 'json'; "
        "value=YAML.safe_load_file(ARGV.fetch(0), permitted_classes: [], aliases: false); "
        "STDOUT.write(JSON.generate(value))"
    )
    result = subprocess.run(
        ["ruby", "-e", program, str(POLICY)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise TypeError("application policy must be an object")
    return value


class ApplicationPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = load_policy()

    def test_steam_bootstrap_is_explicitly_excluded(self):
        exclusions = {
            item["desktop_id"]: item["reason"]
            for item in self.policy.get("exclude", [])
        }
        self.assertIn("steam.desktop", exclusions)
        reason = exclusions["steam.desktop"].casefold()
        self.assertIn("bootstrap", reason)
        self.assertIn("install", reason)
        for section in ("aliases", "contracts", "critical"):
            self.assertNotIn(
                "steam.desktop",
                {item["desktop_id"] for item in self.policy.get(section, [])},
            )

    def test_policy_is_structurally_valid_against_a_synthetic_inventory(self):
        policy = self.policy
        ids = {
            item["desktop_id"]
            for section in ("exclude", "aliases", "contracts", "critical")
            for item in policy.get(section, [])
        }
        ids.update(item["canonical"] for item in policy.get("aliases", []))
        exclusions = {item["desktop_id"]: item for item in policy.get("exclude", [])}
        aliases = {item["desktop_id"]: item for item in policy.get("aliases", [])}
        contracts = {item["desktop_id"]: item for item in policy.get("contracts", [])}
        inventory = {}
        for desktop_id in ids:
            if desktop_id in exclusions:
                inventory[desktop_id] = {
                    "desktop_id": desktop_id,
                    "classification": "excluded",
                    "exclusion_reason": exclusions[desktop_id]["reason"],
                }
            elif desktop_id in aliases:
                inventory[desktop_id] = {
                    "desktop_id": desktop_id,
                    "classification": "duplicate-alias",
                    "canonical": aliases[desktop_id]["canonical"],
                }
            else:
                contract = AGGREGATOR.normalized_contract(contracts.get(desktop_id))
                inventory[desktop_id] = {
                    "desktop_id": desktop_id,
                    "classification": "launchable",
                    "execution_contract": contract["kind"],
                    "contract_reason": contract["reason"],
                    "contract_close_key": contract["close_key"],
                    "contract_close_timeout": contract["close_timeout"],
                    "contract_content_timeout": contract["content_timeout"],
                    "contract_allowed_exit_codes": contract["allowed_exit_codes"],
                    "contract_requirements": contract["requirements"],
                }
        AGGREGATOR.validate_policy(policy, inventory)

    def test_aliases_are_one_level_and_have_distinct_targets(self):
        aliases = {
            item["desktop_id"]: item["canonical"]
            for item in self.policy.get("aliases", [])
        }
        self.assertEqual(len(aliases), len(self.policy.get("aliases", [])))
        for desktop_id, canonical in aliases.items():
            self.assertNotEqual(desktop_id, canonical)
            self.assertNotIn(canonical, aliases, "alias chains are intentionally unsupported")

    def test_nonzero_exit_codes_are_never_globally_accepted(self):
        for item in self.policy.get("contracts", []):
            contract = AGGREGATOR.normalized_contract(item)
            nonzero = set(contract["allowed_exit_codes"]) - {0}
            if nonzero:
                self.assertEqual(contract["kind"], "transient-dialog")
                self.assertEqual(nonzero, {1})


if __name__ == "__main__":
    unittest.main()
