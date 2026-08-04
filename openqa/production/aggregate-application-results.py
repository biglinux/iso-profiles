#!/usr/bin/env python3
"""Validate and aggregate the complete openQA application shard matrix."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import sys
from pathlib import Path
from typing import Any


CLASSIFICATIONS = {"launchable", "excluded", "duplicate-alias", "invalid"}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def shard_for(desktop_id: str, shard_count: int) -> int:
    if shard_count <= 0:
        raise ValueError("shard count must be positive")
    digest = hashlib.sha256(desktop_id.encode("utf-8")).hexdigest()
    return int(digest, 16) % shard_count


def read_json_gzip(path: Path) -> dict[str, Any]:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid metrics file {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"metrics file is not an object: {path}")
    return value


def require_string(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"metrics field {key!r} is missing or empty")
    return value


def validate_inventory(coverage: dict[str, Any], expected_count: int) -> dict[str, dict[str, Any]]:
    if coverage.get("shard_count") != expected_count:
        raise ValueError(
            f"all application shards must use APPLICATION_SHARD_COUNT={expected_count}"
        )
    inventory = coverage.get("inventory")
    if not isinstance(inventory, list) or not inventory:
        raise ValueError("application inventory is missing or empty")
    desktop_ids: dict[str, dict[str, Any]] = {}
    for item in inventory:
        if not isinstance(item, dict):
            raise ValueError("application inventory contains a non-object entry")
        desktop_id = require_string(item, "desktop_id")
        if (
            not desktop_id.endswith(".desktop")
            or Path(desktop_id).is_absolute()
            or ".." in Path(desktop_id).parts
        ):
            raise ValueError(f"invalid desktop ID in inventory: {desktop_id}")
        if desktop_id in desktop_ids:
            raise ValueError(f"duplicate desktop ID in inventory: {desktop_id}")
        classification = item.get("classification")
        if classification not in CLASSIFICATIONS:
            raise ValueError(f"invalid classification for {desktop_id}: {classification!r}")
        assigned_shard = item.get("assigned_shard")
        if assigned_shard != shard_for(desktop_id, expected_count):
            raise ValueError(f"incorrect shard assignment for {desktop_id}")
        if classification == "excluded" and not item.get("exclusion_reason"):
            raise ValueError(f"excluded entry has no reason: {desktop_id}")
        if classification == "duplicate-alias" and not item.get("canonical"):
            raise ValueError(f"duplicate alias has no canonical entry: {desktop_id}")
        if classification == "invalid" and not item.get("classification_reason"):
            raise ValueError(f"invalid entry has no reason: {desktop_id}")
        desktop_ids[desktop_id] = item

    expected_hash = coverage.get("inventory_hash")
    actual_hash = hashlib.sha256(canonical_json(inventory).encode("utf-8")).hexdigest()
    if expected_hash != actual_hash:
        raise ValueError("application inventory hash does not match its contents")
    totals = {
        classification: sum(
            item["classification"] == classification for item in inventory
        )
        for classification in CLASSIFICATIONS
    }
    expected_totals = {
        "inventory_total": len(inventory),
        "launchable_total": totals["launchable"],
        "excluded_total": totals["excluded"],
        "duplicate_total": totals["duplicate-alias"],
        "invalid_total": totals["invalid"],
    }
    for key, expected in expected_totals.items():
        if coverage.get(key) != expected:
            raise ValueError(f"coverage count {key} is inconsistent")
    return desktop_ids


def validate_policy(policy: dict[str, Any], inventory: dict[str, dict[str, Any]]) -> list[str]:
    if policy.get("version") != 1:
        raise ValueError("application policy version must be 1")
    critical = policy.get("critical", [])
    if not isinstance(critical, list):
        raise ValueError("application policy critical section is invalid")
    critical_ids: list[str] = []
    excluded = policy.get("exclude", [])
    aliases = policy.get("aliases", [])
    if not isinstance(excluded, list) or not isinstance(aliases, list):
        raise ValueError("application policy exclusion or alias section is invalid")
    for item in excluded:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("desktop_id"), str)
            or not isinstance(item.get("reason"), str)
            or not item["reason"]
        ):
            raise ValueError("application policy has an invalid exclusion entry")
        desktop_id = item["desktop_id"]
        if sum(
            isinstance(candidate, dict) and candidate.get("desktop_id") == desktop_id
            for candidate in excluded
        ) != 1:
            raise ValueError(f"excluded application is duplicated: {desktop_id}")
        current = inventory.get(desktop_id)
        if current is None or current["classification"] != "excluded":
            raise ValueError(f"excluded application is absent or not excluded: {desktop_id}")
    for item in aliases:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("desktop_id"), str)
            or not isinstance(item.get("canonical"), str)
            or not item["canonical"]
        ):
            raise ValueError("application policy has an invalid alias entry")
        desktop_id = item["desktop_id"]
        canonical = item.get("canonical")
        if sum(
            isinstance(candidate, dict) and candidate.get("desktop_id") == desktop_id
            for candidate in aliases
        ) != 1:
            raise ValueError(f"alias application is duplicated: {desktop_id}")
        current = inventory.get(desktop_id)
        if current is None or current["classification"] != "duplicate-alias":
            raise ValueError(f"alias application is absent or not an alias: {desktop_id}")
        if (
            current.get("canonical") != canonical
            or canonical not in inventory
            or inventory[canonical]["classification"] != "launchable"
        ):
            raise ValueError(f"alias canonical target is invalid: {desktop_id}")
    for item in critical:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("desktop_id"), str)
            or not isinstance(item.get("functional_test"), str)
            or not item["functional_test"]
        ):
            raise ValueError("application policy has an invalid critical entry")
        desktop_id = item["desktop_id"]
        if desktop_id in critical_ids:
            raise ValueError(f"critical application is duplicated: {desktop_id}")
        critical_ids.append(desktop_id)
        current = inventory.get(desktop_id)
        if current is None:
            raise ValueError(f"critical application is absent from the ISO: {desktop_id}")
        if current["classification"] != "launchable":
            raise ValueError(f"critical application is not launchable: {desktop_id}")
    return critical_ids


def validate_shards(
    metrics_files: list[Path],
    expected_count: int,
    policy: dict[str, Any],
) -> dict[str, Any]:
    if len(metrics_files) != expected_count:
        raise ValueError(
            f"expected {expected_count} application metric files, found {len(metrics_files)}"
        )
    payloads = [read_json_gzip(path) for path in metrics_files]
    coverages = [payload.get("coverage") for payload in payloads]
    if any(not isinstance(coverage, dict) for coverage in coverages):
        raise ValueError("every shard must contain coverage metadata")
    first = coverages[0]
    assert isinstance(first, dict)
    metadata_keys = (
        "iso_filename",
        "iso_sha256",
        "build_id",
        "commit_sha",
        "needles_git_hash",
        "policy_hash",
        "policy_version",
        "inventory_hash",
    )
    for coverage in coverages[1:]:
        assert isinstance(coverage, dict)
        for key in metadata_keys:
            if coverage.get(key) != first.get(key):
                raise ValueError(f"shard metadata differs for {key}")

    inventory = validate_inventory(first, expected_count)
    for coverage in coverages[1:]:
        assert isinstance(coverage, dict)
        if coverage.get("inventory") != first.get("inventory"):
            raise ValueError("application shards do not share the same inventory")
    critical_ids = validate_policy(policy, inventory)
    if set(first.get("critical_desktop_ids", [])) != set(critical_ids):
        raise ValueError("metrics critical application list differs from policy")
    if first.get("missing_critical"):
        raise ValueError("metrics report missing critical applications")
    expected_policy_hash = hashlib.sha256(canonical_json(policy).encode("utf-8")).hexdigest()
    if first.get("policy_hash") != expected_policy_hash:
        raise ValueError("application policy hash does not match the committed policy")

    shard_indexes: set[int] = set()
    seen_launchables: dict[str, dict[str, Any]] = {}
    shard_summaries: list[dict[str, Any]] = []
    for path, payload, coverage in zip(metrics_files, payloads, coverages, strict=True):
        assert isinstance(coverage, dict)
        if payload.get("schema_version") != 2 or coverage.get("schema_version") != 3:
            raise ValueError(f"unsupported application metrics schema: {path}")
        shard_index = coverage.get("shard_index")
        if not isinstance(shard_index, int) or not 0 <= shard_index < expected_count:
            raise ValueError(f"invalid shard index in {path}")
        if shard_index in shard_indexes:
            raise ValueError(f"duplicate application shard index: {shard_index}")
        shard_indexes.add(shard_index)
        applications = payload.get("applications")
        summary = payload.get("summary")
        if not isinstance(applications, list) or not isinstance(summary, dict):
            raise ValueError(f"shard payload is missing applications or summary: {path}")
        if summary.get("tested") != len(applications):
            raise ValueError(f"shard tested count is inconsistent: {path}")
        passed = sum(item.get("status") == "passed" for item in applications if isinstance(item, dict))
        failed = sum(item.get("status") == "failed" for item in applications if isinstance(item, dict))
        if summary.get("passed") != passed or summary.get("failed") != failed:
            raise ValueError(f"shard result counts are inconsistent: {path}")
        for item in applications:
            if not isinstance(item, dict):
                raise ValueError(f"shard application result is not an object: {path}")
            desktop_id = require_string(item, "desktop_id")
            inventory_item = inventory.get(desktop_id)
            if inventory_item is None:
                raise ValueError(f"shard tested an unknown desktop ID: {desktop_id}")
            if inventory_item["classification"] != "launchable":
                raise ValueError(f"shard tested a non-launchable entry: {desktop_id}")
            if inventory_item["assigned_shard"] != shard_index:
                raise ValueError(f"desktop ID assigned to the wrong shard: {desktop_id}")
            if item.get("classification") != "launchable":
                raise ValueError(f"application result classification is invalid: {desktop_id}")
            if item.get("status") not in {"passed", "failed"}:
                raise ValueError(f"application result has invalid status: {desktop_id}")
            if desktop_id in seen_launchables:
                raise ValueError(f"launchable desktop ID appears in multiple shards: {desktop_id}")
            seen_launchables[desktop_id] = item
        shard_summaries.append(
            {
                "shard_index": shard_index,
                "source": str(path),
                "tested": len(applications),
                "passed": passed,
                "failed": failed,
            }
        )

    if shard_indexes != set(range(expected_count)):
        raise ValueError("application shard indexes are incomplete")
    launchable_ids = {
        desktop_id
        for desktop_id, item in inventory.items()
        if item["classification"] == "launchable"
    }
    if set(seen_launchables) != launchable_ids:
        missing = sorted(launchable_ids - set(seen_launchables))
        extra = sorted(set(seen_launchables) - launchable_ids)
        raise ValueError(f"application coverage mismatch: missing={missing} extra={extra}")
    failed_ids = sorted(
        desktop_id for desktop_id, item in seen_launchables.items() if item["status"] == "failed"
    )
    if failed_ids:
        raise ValueError(f"mandatory applications failed: {', '.join(failed_ids)}")

    return {
        "status": "passed",
        "metadata": {key: first.get(key) for key in metadata_keys},
        "coverage": {
            "inventory_total": len(inventory),
            "launchable_total": len(launchable_ids),
            "excluded_total": sum(item["classification"] == "excluded" for item in inventory.values()),
            "duplicate_total": sum(item["classification"] == "duplicate-alias" for item in inventory.values()),
            "invalid_total": sum(item["classification"] == "invalid" for item in inventory.values()),
            "tested_total": len(seen_launchables),
            "passed_total": len(seen_launchables),
            "failed_total": 0,
        },
        "critical": {"expected": critical_ids, "tested": critical_ids},
        "shards": sorted(shard_summaries, key=lambda item: item["shard_index"]),
    }


def write_reports(output_dir: Path, summary: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "application-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    metadata = summary.get("metadata", {})
    coverage = summary.get("coverage", {})
    lines = [
        f"# Application coverage: {summary.get('status', 'failed')}",
        "",
        f"- ISO: `{metadata.get('iso_filename', 'unknown')}`",
        f"- SHA-256: `{metadata.get('iso_sha256', 'unknown')}`",
        f"- Inventory: {coverage.get('inventory_total', 0)} entries",
        f"- Launchable: {coverage.get('launchable_total', 0)}",
        f"- Excluded: {coverage.get('excluded_total', 0)}",
        f"- Duplicate aliases: {coverage.get('duplicate_total', 0)}",
        f"- Invalid: {coverage.get('invalid_total', 0)}",
        f"- Tested: {coverage.get('tested_total', 0)}",
        f"- Passed: {coverage.get('passed_total', 0)}",
        f"- Failed: {coverage.get('failed_total', 0)}",
        "",
        "## Shards",
        "",
        "| Shard | Tested | Passed | Failed |",
        "| ---: | ---: | ---: | ---: |",
    ]
    for shard in summary.get("shards", []):
        lines.append(
            f"| {shard['shard_index']} | {shard['tested']} | {shard['passed']} | {shard['failed']} |"
        )
    if summary.get("error"):
        lines.extend(["", "## Error", "", f"`{summary['error']}`"])
    (output_dir / "application-summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    rows = "".join(
        f"<tr><td>{shard['shard_index']}</td><td>{shard['tested']}</td>"
        f"<td>{shard['passed']}</td><td>{shard['failed']}</td></tr>"
        for shard in summary.get("shards", [])
    )
    error = f"<p><code>{html.escape(summary['error'])}</code></p>" if summary.get("error") else ""
    document = (
        "<!doctype html><meta charset='utf-8'><title>BigLinux application coverage</title>"
        f"<h1>Application coverage: {html.escape(str(summary.get('status', 'failed')))}</h1>"
        f"{error}<p>Inventory: {coverage.get('inventory_total', 0)}; "
        f"launchable: {coverage.get('launchable_total', 0)}; tested: {coverage.get('tested_total', 0)}; "
        f"passed: {coverage.get('passed_total', 0)}; failed: {coverage.get('failed_total', 0)}</p>"
        f"<table><thead><tr><th>Shard</th><th>Tested</th><th>Passed</th><th>Failed</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )
    (output_dir / "application-summary.html").write_text(document, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--policy-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-shards", type=int, default=4)
    args = parser.parse_args()
    summary: dict[str, Any]
    try:
        if args.expected_shards <= 0:
            raise ValueError("expected shard count must be positive")
        policy = json.loads(args.policy_json.read_text(encoding="utf-8"))
        if not isinstance(policy, dict):
            raise ValueError("policy JSON is not an object")
        metric_files = sorted(args.artifacts_root.rglob("application-metrics.json.gz"))
        summary = validate_shards(metric_files, args.expected_shards, policy)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        summary = {"status": "failed", "error": str(error), "shards": [], "coverage": {}}
        write_reports(args.output_dir, summary)
        print(f"Application coverage failed: {error}", file=sys.stderr)
        return 1
    write_reports(args.output_dir, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
