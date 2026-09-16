#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise production report publication with explicitly synthetic evidence."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

EXPECTED = {"success": "ok", "failure": "fail", "incomplete": "unknown"}


def write_json(path: Path, value: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")


def create(scenario: str, root: Path) -> int:
    work = root / "results" / "bios"
    write_json(work / "vars.json", {"DISTRI": "biglinux", "TEST": "bios",
        "ISO": "synthetic-report-check.iso", "BUILD": "reportcheck-" + scenario})
    write_json(work / "testresults" / "test_order.json", [
        {"name": "live_desktop"}, {"name": "applications"}])
    write_json(work / "testresults" / "result-live_desktop.json", {
        "result": "ok", "details": []})
    if scenario != "incomplete":
        # A failed top-level module must win over informational positive details.
        write_json(work / "testresults" / "result-applications.json", {
            "result": EXPECTED[scenario], "details": [{"result": "ok"}]})
    write_json(work / "testresults" / "installed-application-smoke.json", {
        "schema_version": 1, "applications": [
            {"desktop_id": "optional-not-installed.desktop", "status": "skipped",
             "skip_reason": "Not installed in this synthetic ISO"}]})
    write_json(root / "run-status.json", {"schema_version": 1, "name": "bios",
        "status": "failure" if scenario == "failure" else "success",
        "synthetic": True})
    return 17 if scenario == "failure" else 0


def published_artifacts(root: Path) -> list[Path]:
    """Partial reruns keep successful artifacts from earlier attempts of this run."""
    pattern = re.compile(r"biglinux-iso-validation-reportcheck-(success|failure|incomplete)-([0-9]+)-([1-9][0-9]*)")
    selected: dict[str, tuple[int, Path]] = {}
    runs = set()
    for directory in sorted(root.glob("biglinux-iso-validation-reportcheck-*")):
        match = pattern.fullmatch(directory.name)
        if not match or not directory.is_dir() or directory.is_symlink():
            raise ValueError("invalid published report artifact name or directory")
        scenario, run, attempt = match.groups()
        runs.add(run)
        if int(attempt) > selected.get(scenario, (0, directory))[0]:
            selected[scenario] = (int(attempt), directory)
    if len(runs) > 1:
        raise ValueError("published reports belong to different workflow runs")
    if set(selected) != set(EXPECTED):
        raise ValueError(f"expected three published artifacts, found {len(selected)} scenarios")
    return [selected[key][1] for key in sorted(selected)]


def verify(root: Path) -> None:
    directories = published_artifacts(root)
    seen = set()
    for directory in directories:
        summary = json.loads((directory / "RESULTADO.json").read_text(encoding="utf-8"))
        scenario = summary["context"]["build"].removeprefix("reportcheck-")
        if scenario not in EXPECTED or scenario in seen:
            raise ValueError("duplicate or unexpected report scenario")
        seen.add(scenario)
        if summary["result"] != EXPECTED[scenario]:
            raise ValueError(f"{scenario}: unexpected verdict {summary['result']}")
        if summary.get("report_errors") or summary["formats"] != {
                "html": "detailed", "markdown": "detailed", "pdf": "detailed"}:
            raise ValueError(f"{scenario}: detailed report was not generated")
        for name in ("RESULTADO.md", "RESULTADO.json", "run-status.json",
                     "biglinux-validation-report.html", "biglinux-iso-validation.pdf"):
            if not (directory / name).is_file() or not (directory / name).stat().st_size:
                raise ValueError(f"{scenario}: missing published {name}")
        pdf = (directory / "biglinux-iso-validation.pdf").read_bytes()
        if not pdf.startswith(b"%PDF-") or b"%%EOF" not in pdf[-32:]:
            raise ValueError(f"{scenario}: PDF is incomplete")
        label = {"success": "Passou", "failure": "Falhou", "incomplete": "Inconclusivo"}[scenario]
        markdown = (directory / "RESULTADO.md").read_text(encoding="utf-8")
        if label not in markdown.splitlines()[0]:
            raise ValueError(f"{scenario}: Markdown contradicts JSON")
        if label not in (directory / "biglinux-validation-report.html").read_text(encoding="utf-8"):
            raise ValueError(f"{scenario}: HTML contradicts JSON")
        if summary["application_counts"] != {"skipped": 1}:
            raise ValueError(f"{scenario}: absent application changed the outcome")
        print(f"{scenario}: downloaded PDF/HTML/Markdown/JSON verified ({summary['result']})")
    if seen != set(EXPECTED):
        raise ValueError("incomplete scenario coverage")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    producer = sub.add_parser("create")
    producer.add_argument("scenario", choices=EXPECTED)
    producer.add_argument("root", type=Path)
    consumer = sub.add_parser("verify")
    consumer.add_argument("root", type=Path)
    args = parser.parse_args()
    if args.operation == "create":
        return create(args.scenario, args.root)
    verify(args.root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
