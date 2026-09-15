import gzip
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "production" / "aggregate-application-results.py"
SPEC = importlib.util.spec_from_file_location("aggregate_application_results", SCRIPT)
assert SPEC and SPEC.loader
AGGREGATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AGGREGATOR)


class AggregateApplicationResultsTest(unittest.TestCase):
    def setUp(self):
        self.policy = {
            "version": 2,
            "exclude": [{"desktop_id": "service.desktop", "reason": "not graphical"}],
            "aliases": [],
            "contracts": [],
            "critical": [{"desktop_id": "app.desktop", "functional_test": "app"}],
        }
        default_contract = AGGREGATOR.normalized_contract()
        self.inventory = [
            {
                "desktop_id": "app.desktop",
                "classification": "launchable",
                "assigned_shard": AGGREGATOR.shard_for("app.desktop", 4),
                **self._contract_inventory(default_contract),
            },
            {
                "desktop_id": "other.desktop",
                "classification": "launchable",
                "assigned_shard": AGGREGATOR.shard_for("other.desktop", 4),
                **self._contract_inventory(default_contract),
            },
            {
                "desktop_id": "service.desktop",
                "classification": "excluded",
                "exclusion_reason": "not graphical",
                "assigned_shard": AGGREGATOR.shard_for("service.desktop", 4),
            },
        ]
        self.inventory.sort(key=lambda item: item["desktop_id"])

    @staticmethod
    def _contract_inventory(contract):
        return {
            "execution_contract": contract["kind"],
            "contract_reason": contract["reason"],
            "contract_close_key": contract["close_key"],
            "contract_dismiss_auxiliary": contract["dismiss_auxiliary"],
            "contract_close_timeout": contract["close_timeout"],
            "contract_content_timeout": contract["content_timeout"],
            "contract_allowed_exit_codes": contract["allowed_exit_codes"],
            "contract_requirements": contract["requirements"],
        }

    def _write_metrics(self, root: Path, status_by_id=None):
        status_by_id = status_by_id or {}
        inventory_hash = hashlib.sha256(
            AGGREGATOR.canonical_json(self.inventory).encode("utf-8")
        ).hexdigest()
        coverage = {
            "schema_version": 5,
            "iso_filename": "candidate.iso",
            "iso_sha256": "a" * 64,
            "build_id": "test-build",
            "commit_sha": "b" * 40,
            "needles_git_hash": "c" * 40,
            "policy_hash": hashlib.sha256(
                AGGREGATOR.canonical_json(self.policy).encode("utf-8")
            ).hexdigest(),
            "policy_version": 2,
            "inventory_hash": inventory_hash,
            "shard_count": 4,
            "shard_index": 0,
            "inventory": self.inventory,
            "inventory_total": len(self.inventory),
            "launchable_total": sum(i["classification"] == "launchable" for i in self.inventory),
            "excluded_total": sum(i["classification"] == "excluded" for i in self.inventory),
            "duplicate_total": sum(i["classification"] == "duplicate-alias" for i in self.inventory),
            "invalid_total": sum(i["classification"] == "invalid" for i in self.inventory),
            "critical_desktop_ids": sorted(i["desktop_id"] for i in self.policy["critical"]),
            "not_installed_desktop_ids": sorted(
                {i["desktop_id"] for i in self.policy["critical"]}
                - {i["desktop_id"] for i in self.inventory}),
        }
        root.mkdir(parents=True, exist_ok=True)
        for shard_index in range(4):
            coverage["shard_index"] = shard_index
            applications = []
            for item in self.inventory:
                desktop_id = item["desktop_id"]
                if item["classification"] == "launchable" and AGGREGATOR.shard_for(desktop_id, 4) == shard_index:
                    contract = item["execution_contract"]
                    status = status_by_id.get(desktop_id, "passed")
                    applications.append(
                        {
                            "desktop_id": desktop_id,
                            "classification": "launchable",
                            "execution_contract": contract,
                            "contract_reason": item["contract_reason"],
                            "capability_requirements": item["contract_requirements"],
                            "allowed_exit_codes": item["contract_allowed_exit_codes"],
                            "dismiss_auxiliary": item["contract_dismiss_auxiliary"],
                            "validation_mode": "atspi-smoke",
                            "accessible_window": True,
                            "accessibility_status": "available",
                            "functional_status": (
                                "window-closed" if contract == "shared-window"
                                else "open-cancel" if contract == "transient-dialog"
                                else "open-close"
                            ),
                            "graceful_exit": True,
                            "process_gone": True,
                            "application_exit_code": 0,
                            "application_crashed": False,
                            "window_closed": True,
                            "close_action": "keyboard." + (item["contract_close_key"] or "alt-f4"),
                            "cleanup_status": "passed",
                            "status": status,
                        }
                    )
                    if status == "skipped":
                        applications[-1].update(
                            validation_mode="capability-not-applicable",
                            functional_status="not-applicable",
                            accessibility_status="not-applicable",
                            cleanup_status="not-needed",
                            capability_requirements=item["contract_requirements"],
                            skip_reason="required capability unavailable",
                        )
            payload = {
                "schema_version": 3,
                "summary": {
                    "total": len(applications),
                    "tested": sum(item["status"] != "skipped" for item in applications),
                    "passed": sum(item["status"] == "passed" for item in applications),
                    "failed": sum(item["status"] == "failed" for item in applications),
                    "skipped": sum(item["status"] == "skipped" for item in applications),
                },
                "coverage": coverage,
                "applications": applications,
            }
            shard_root = root / f"shard-{shard_index}"
            shard_root.mkdir()
            with gzip.open(
                shard_root / "application-metrics.json.gz", "wt", encoding="utf-8"
            ) as stream:
                json.dump(payload, stream)

    def test_complete_matrix_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_metrics(root)
            summary = AGGREGATOR.validate_shards(
                sorted(root.rglob("application-metrics.json.gz")), 4, self.policy
            )
            self.assertEqual(summary["status"], "passed")
            self.assertEqual(summary["coverage"]["tested_total"], 2)
            self.assertEqual(summary["coverage"]["not_applicable_total"], 0)
            self.assertEqual(summary["coverage"]["contract_counts"]["standard"], 2)
            self.assertEqual(summary["policy_exclusions"][0]["desktop_id"], "service.desktop")


    def test_reports_make_exclusions_and_aliases_auditable(self):
        self.policy["aliases"].append(
            {"desktop_id": "alias.desktop", "canonical": "app.desktop"}
        )
        self.inventory.append(
            {
                "desktop_id": "alias.desktop",
                "classification": "duplicate-alias",
                "canonical": "app.desktop",
                "assigned_shard": AGGREGATOR.shard_for("alias.desktop", 4),
            }
        )
        self.inventory.sort(key=lambda item: item["desktop_id"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_metrics(root)
            summary = AGGREGATOR.validate_shards(
                sorted(root.rglob("*.json.gz")), 4, self.policy
            )
            report = root / "report"
            AGGREGATOR.write_reports(report, summary)
            markdown = (report / "application-summary.md").read_text(encoding="utf-8")
            document = (report / "application-summary.html").read_text(encoding="utf-8")
        self.assertIn("service.desktop", markdown)
        self.assertIn("not graphical", markdown)
        self.assertIn("alias.desktop", markdown)
        self.assertIn("app.desktop", markdown)
        self.assertIn("Contracts: standard=2, shared-window=0, transient-dialog=0", markdown)
        self.assertIn("Policy exclusions", document)
        self.assertIn("Duplicate aliases", document)
        self.assertIn("Contracts: standard=2; shared-window=0; transient-dialog=0", document)

    def test_failed_application_blocks_matrix_and_keeps_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_metrics(root, {"other.desktop": "failed"})

            summary = AGGREGATOR.validate_shards(
                sorted(root.rglob("application-metrics.json.gz")), 4, self.policy
            )

        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["coverage"]["tested_total"], 2)
        self.assertEqual(summary["coverage"]["passed_total"], 1)
        self.assertEqual(summary["coverage"]["failed_total"], 1)
        self.assertEqual(summary["failed_desktop_ids"], ["other.desktop"])
        self.assertEqual(len(summary["shards"]), 4)

    def test_missing_shard_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_metrics(root)
            (root / "shard-3" / "application-metrics.json.gz").unlink()
            with self.assertRaisesRegex(
                ValueError, "expected 4 application metric files"
            ):
                AGGREGATOR.validate_shards(
                    sorted(root.rglob("application-metrics.json.gz")), 4, self.policy
                )

    def _rewrite_payloads(self, root, transform):
        for path in root.rglob("application-metrics.json.gz"):
            payload = AGGREGATOR.read_json_gzip(path)
            transform(payload)
            with gzip.open(path, "wt", encoding="utf-8") as stream:
                json.dump(payload, stream)

    def test_weak_visual_or_process_modes_cannot_pass_as_gui(self):
        for mode in ("process-alive", "x11-open", "delegated-open", "process-start"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._write_metrics(root)
                self._rewrite_payloads(root, lambda payload: [item.update(validation_mode=mode)
                    for item in payload["applications"]])
                with self.assertRaises(ValueError):
                    AGGREGATOR.validate_shards(sorted(root.rglob("*.json.gz")), 4, self.policy)

    def test_empty_provenance_cannot_pass_by_agreement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_metrics(root)
            self._rewrite_payloads(root, lambda payload: payload["coverage"].update(commit_sha=""))
            with self.assertRaises(ValueError):
                AGGREGATOR.validate_shards(sorted(root.rglob("*.json.gz")), 4, self.policy)

    def test_wrong_expected_commit_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_metrics(root)
            with self.assertRaises(ValueError):
                AGGREGATOR.validate_shards(sorted(root.rglob("*.json.gz")), 4, self.policy,
                                          expected_commit="d" * 40)

    def test_accessible_window_without_semantic_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_metrics(root)
            self._rewrite_payloads(root, lambda payload: [item.pop("accessibility_status", None)
                for item in payload["applications"]])
            with self.assertRaises(ValueError):
                AGGREGATOR.validate_shards(sorted(root.rglob("*.json.gz")), 4, self.policy)

    def test_policy_program_absent_from_iso_is_not_applicable(self):
        self.policy["critical"].append({"desktop_id": "optional-kde-app.desktop", "functional_test": "kde-app"})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_metrics(root)
            summary = AGGREGATOR.validate_shards(sorted(root.rglob("*.json.gz")), 4, self.policy)
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["not_installed_desktop_ids"], ["optional-kde-app.desktop"])
        self.assertNotIn("optional-kde-app.desktop", summary["critical"]["tested"])

    def test_policy_exclusion_and_alias_may_be_absent(self):
        self.policy["exclude"].append({"desktop_id": "optional-service.desktop", "reason": "service"})
        self.policy["aliases"].append({"desktop_id": "optional-alias.desktop", "canonical": "missing.desktop"})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_metrics(root)
            summary = AGGREGATOR.validate_shards(sorted(root.rglob("*.json.gz")), 4, self.policy)
        self.assertEqual(summary["status"], "passed")

    def test_policy_contract_may_be_absent_from_this_iso(self):
        self.policy["contracts"].append(
            {
                "desktop_id": "optional-camera.desktop",
                "kind": "standard",
                "requires": ["video-device"],
                "reason": "camera required",
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_metrics(root)
            summary = AGGREGATOR.validate_shards(
                sorted(root.rglob("*.json.gz")), 4, self.policy
            )
        self.assertEqual(summary["status"], "passed")

    def test_empty_complete_inventory_has_no_applicable_tests(self):
        self.inventory = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_metrics(root)
            summary = AGGREGATOR.validate_shards(sorted(root.rglob("*.json.gz")), 4, self.policy)
        self.assertEqual(summary["application_result"], "not-applicable")
        self.assertEqual(summary["coverage"]["passed_total"], 0)

    def test_installed_but_not_applicable_to_desktop_is_not_mandatory(self):
        self.inventory[0].update(classification="excluded", exclusion_reason="OnlyShowIn=KDE on GNOME")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_metrics(root)
            summary = AGGREGATOR.validate_shards(sorted(root.rglob("*.json.gz")), 4, self.policy)
        self.assertEqual(summary["status"], "passed")
        self.assertNotIn("app.desktop", summary["critical"]["applicable"])

    def test_exit_error_or_missing_close_evidence_cannot_be_passed(self):
        for changes in ({"application_exit_code": 139}, {"application_exit_code": 1},
                        {"application_exit_code": None}, {"application_exit_code": False},
                        {"graceful_exit": False}, {"process_gone": False},
                        {"window_closed": False}, {"close_action": "process-group.sigterm"},
                        {"functional_status": "launch-only"}, {"cleanup_status": "failed"},
                        {"allowed_exit_codes": [0, 1]}, {"capability_requirements": ["video-device"]},
                        {"contract_reason": "tampered"}, {"dismiss_auxiliary": True}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._write_metrics(root)
                self._rewrite_payloads(root, lambda p: [item.update(changes) for item in p["applications"]])
                with self.assertRaises(ValueError):
                    AGGREGATOR.validate_shards(sorted(root.rglob("*.json.gz")), 4, self.policy)

    def test_string_exit_status_is_rejected_before_it_can_break_a_real_aggregate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_metrics(root)
            self._rewrite_payloads(
                root,
                lambda payload: [item.update(application_exit_code="0")
                                 for item in payload["applications"]],
            )
            with self.assertRaisesRegex(ValueError, "complete smoke evidence"):
                AGGREGATOR.validate_shards(sorted(root.rglob("*.json.gz")), 4, self.policy)

    def test_installed_app_cannot_be_silently_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_metrics(root, {"app.desktop": "skipped"})
            with self.assertRaisesRegex(ValueError, "without an unmet capability"):
                AGGREGATOR.validate_shards(sorted(root.rglob("*.json.gz")), 4, self.policy)

    def test_capability_gated_application_can_be_not_applicable(self):
        contract = AGGREGATOR.normalized_contract(
            {
                "kind": "standard",
                "requires": ["video-device"],
                "reason": "camera required",
            }
        )
        self.inventory[0].update(self._contract_inventory(contract))
        self.policy["contracts"].append(
            {
                "desktop_id": "app.desktop",
                "kind": "standard",
                "requires": ["video-device"],
                "reason": "camera required",
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_metrics(root, {"app.desktop": "skipped"})
            summary = AGGREGATOR.validate_shards(
                sorted(root.rglob("*.json.gz")), 4, self.policy
            )
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["coverage"]["not_applicable_total"], 1)
        self.assertEqual(summary["runtime_not_applicable_desktop_ids"], ["app.desktop"])
        self.assertNotIn("app.desktop", summary["critical"]["tested"])

    def test_transient_dialog_accepts_only_its_declared_cancel_exit(self):
        contract = AGGREGATOR.normalized_contract(
            {
                "kind": "transient-dialog",
                "allowed_exit_codes": [0, 1],
                "reason": "cancel is normal",
            }
        )
        self.inventory[0].update(self._contract_inventory(contract))
        self.policy["contracts"].append(
            {
                "desktop_id": "app.desktop",
                "kind": "transient-dialog",
                "allowed_exit_codes": [0, 1],
                "reason": "cancel is normal",
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_metrics(root)
            self._rewrite_payloads(
                root,
                lambda payload: [
                    item.update(application_exit_code=1)
                    for item in payload["applications"]
                    if item["desktop_id"] == "app.desktop"
                ],
            )
            summary = AGGREGATOR.validate_shards(
                sorted(root.rglob("*.json.gz")), 4, self.policy
            )
        self.assertEqual(summary["status"], "passed")


    def test_auxiliary_dismissal_is_boolean_and_requires_ctrl_q(self):
        with self.assertRaisesRegex(ValueError, "dismiss_auxiliary"):
            AGGREGATOR.normalized_contract({"dismiss_auxiliary": 1})
        with self.assertRaisesRegex(ValueError, r"requires.*Ctrl\+Q"):
            AGGREGATOR.normalized_contract(
                {"dismiss_auxiliary": True, "close_key": "alt-f4"}
            )
        contract = AGGREGATOR.normalized_contract(
            {
                "kind": "standard",
                "close_key": "ctrl-q",
                "dismiss_auxiliary": True,
                "reason": "first-run dialog",
            }
        )
        self.assertTrue(contract["dismiss_auxiliary"])

    def test_escape_is_a_valid_explicit_window_close_shortcut(self):
        contract = AGGREGATOR.normalized_contract(
            {"kind": "shared-window", "close_key": "esc", "reason": "runner hide"}
        )
        self.assertEqual(contract["close_key"], "esc")
        self.assertIn("keyboard.esc", AGGREGATOR.CLOSE_ACTIONS)

    def test_configured_close_shortcut_must_match_evidence(self):
        contract = AGGREGATOR.normalized_contract(
            {
                "kind": "standard",
                "close_key": "ctrl-q",
                "reason": "documented quit shortcut",
            }
        )
        self.inventory[0].update(self._contract_inventory(contract))
        self.policy["contracts"].append(
            {
                "desktop_id": "app.desktop",
                "kind": "standard",
                "close_key": "ctrl-q",
                "reason": "documented quit shortcut",
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_metrics(root)
            summary = AGGREGATOR.validate_shards(
                sorted(root.rglob("*.json.gz")), 4, self.policy
            )
            self.assertEqual(summary["status"], "passed")
            self._rewrite_payloads(
                root,
                lambda payload: [
                    item.update(close_action="keyboard.alt-f4")
                    for item in payload["applications"]
                    if item["desktop_id"] == "app.desktop"
                ],
            )
            with self.assertRaises(ValueError):
                AGGREGATOR.validate_shards(
                    sorted(root.rglob("*.json.gz")), 4, self.policy
                )

    def test_shared_window_can_close_without_terminating_resident_process(self):
        contract = AGGREGATOR.normalized_contract(
            {"kind": "shared-window", "reason": "resident service"}
        )
        self.inventory[0].update(self._contract_inventory(contract))
        self.policy["contracts"].append(
            {
                "desktop_id": "app.desktop",
                "kind": "shared-window",
                "reason": "resident service",
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_metrics(root)
            self._rewrite_payloads(
                root,
                lambda payload: [
                    item.update(
                        graceful_exit=False,
                        process_gone=False,
                        application_exit_code=None,
                    )
                    for item in payload["applications"]
                    if item["desktop_id"] == "app.desktop"
                ],
            )
            summary = AGGREGATOR.validate_shards(
                sorted(root.rglob("*.json.gz")), 4, self.policy
            )
        self.assertEqual(summary["status"], "passed")

    def test_shared_window_still_rejects_crash_or_missing_window_close(self):
        contract = AGGREGATOR.normalized_contract(
            {"kind": "shared-window", "reason": "resident service"}
        )
        self.inventory[0].update(self._contract_inventory(contract))
        self.policy["contracts"].append(
            {
                "desktop_id": "app.desktop",
                "kind": "shared-window",
                "reason": "resident service",
            }
        )
        for changes in (
            {"window_closed": False},
            {"application_crashed": True},
            {"application_exit_code": 139},
        ):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._write_metrics(root)
                self._rewrite_payloads(
                    root,
                    lambda payload: [
                        item.update(changes)
                        for item in payload["applications"]
                        if item["desktop_id"] == "app.desktop"
                    ],
                )
                with self.assertRaises(ValueError):
                    AGGREGATOR.validate_shards(
                        sorted(root.rglob("*.json.gz")), 4, self.policy
                    )

    def test_invented_absence_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_metrics(root)
            self._rewrite_payloads(root, lambda p: p["coverage"].update(not_installed_desktop_ids=["app.desktop"]))
            with self.assertRaisesRegex(ValueError, "not-installed list"):
                AGGREGATOR.validate_shards(sorted(root.rglob("*.json.gz")), 4, self.policy)

    def test_shard_assignment_is_deterministic_for_unicode(self):
        desktop_id = "Aplicação/日本語.desktop"
        self.assertEqual(
            AGGREGATOR.shard_for(desktop_id, 4),
            AGGREGATOR.shard_for(desktop_id, 4),
        )
        with self.assertRaisesRegex(ValueError, "positive"):
            AGGREGATOR.shard_for(desktop_id, 0)


if __name__ == "__main__":
    unittest.main()
