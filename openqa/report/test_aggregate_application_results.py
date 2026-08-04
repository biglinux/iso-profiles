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
            "version": 1,
            "exclude": [{"desktop_id": "service.desktop", "reason": "not graphical"}],
            "aliases": [],
            "critical": [{"desktop_id": "app.desktop", "functional_test": "app"}],
        }
        self.inventory = [
            {
                "desktop_id": "app.desktop",
                "classification": "launchable",
                "assigned_shard": AGGREGATOR.shard_for("app.desktop", 4),
            },
            {
                "desktop_id": "other.desktop",
                "classification": "launchable",
                "assigned_shard": AGGREGATOR.shard_for("other.desktop", 4),
            },
            {
                "desktop_id": "service.desktop",
                "classification": "excluded",
                "exclusion_reason": "not graphical",
                "assigned_shard": AGGREGATOR.shard_for("service.desktop", 4),
            },
        ]
        self.inventory.sort(key=lambda item: item["desktop_id"])

    def _write_metrics(self, root: Path, status_by_id=None):
        status_by_id = status_by_id or {}
        inventory_hash = hashlib.sha256(
            AGGREGATOR.canonical_json(self.inventory).encode("utf-8")
        ).hexdigest()
        coverage = {
            "schema_version": 3,
            "iso_filename": "candidate.iso",
            "iso_sha256": "a" * 64,
            "build_id": "test-build",
            "commit_sha": "b" * 40,
            "needles_git_hash": "c" * 40,
            "policy_hash": hashlib.sha256(
                AGGREGATOR.canonical_json(self.policy).encode("utf-8")
            ).hexdigest(),
            "policy_version": 1,
            "inventory_hash": inventory_hash,
            "shard_count": 4,
            "shard_index": 0,
            "inventory": self.inventory,
            "inventory_total": 3,
            "launchable_total": 2,
            "excluded_total": 1,
            "duplicate_total": 0,
            "invalid_total": 0,
            "critical_desktop_ids": ["app.desktop"],
            "missing_critical": [],
        }
        root.mkdir(parents=True, exist_ok=True)
        for shard_index in range(4):
            coverage["shard_index"] = shard_index
            applications = []
            for desktop_id in ("app.desktop", "other.desktop"):
                if AGGREGATOR.shard_for(desktop_id, 4) == shard_index:
                    applications.append(
                        {
                            "desktop_id": desktop_id,
                            "classification": "launchable",
                            "status": status_by_id.get(desktop_id, "passed"),
                        }
                    )
            payload = {
                "schema_version": 2,
                "summary": {
                    "tested": len(applications),
                    "passed": sum(item["status"] == "passed" for item in applications),
                    "failed": sum(item["status"] == "failed" for item in applications),
                },
                "coverage": coverage,
                "applications": applications,
            }
            shard_root = root / f"shard-{shard_index}"
            shard_root.mkdir()
            with gzip.open(shard_root / "application-metrics.json.gz", "wt", encoding="utf-8") as stream:
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

    def test_failed_application_blocks_matrix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_metrics(root, {"other.desktop": "failed"})
            with self.assertRaisesRegex(ValueError, "mandatory applications failed"):
                AGGREGATOR.validate_shards(
                    sorted(root.rglob("application-metrics.json.gz")), 4, self.policy
                )

    def test_missing_shard_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_metrics(root)
            (root / "shard-3" / "application-metrics.json.gz").unlink()
            with self.assertRaisesRegex(ValueError, "expected 4 application metric files"):
                AGGREGATOR.validate_shards(
                    sorted(root.rglob("application-metrics.json.gz")), 4, self.policy
                )

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
