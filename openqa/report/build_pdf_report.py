#!/usr/bin/env python3
"""Build the PDF a person reads to decide whether an ISO is good.

Structure over prose: a verdict page, then one page per phase of the run with
the screen as it actually looked. Captions stay short because the pictures and
the badges carry the meaning.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from report_outcome import module_outcome, read_json, workdirs, summarize, LABELS, worst

from fpdf import FPDF
from PIL import Image

PAGE = (297, 210)  # A4 landscape, in millimetres: screenshots are 4:3
INK = (33, 37, 41)
MUTED = (110, 118, 129)
GOOD = (26, 127, 55)
BAD = (191, 35, 47)
WEAK = (154, 103, 0)
RULE = (222, 226, 230)

# The run in the order a person thinks about it, not the order openQA ran it.
PHASES: list[tuple[str, tuple[str, ...]]] = [
    ("Live boot", ("live_desktop",)),
    (
        "Installation",
        (
            "installer_launch",
            "installer_partitions",
            "installer_user",
            "installer_install",
        ),
    ),
    (
        "Installed system",
        (
            "installed_boot",
            "installed_login",
            "installed_health",
            "installed_critical_apps",
            "installed_brave",
        ),
    ),
]
CAPTIONS = {
    "live_desktop": "Live session reached the desktop",
    "installer_launch": "Installer started",
    "installer_partitions": "Disk layout accepted",
    "installer_user": "Account created",
    "installer_install": "Installation finished and the machine rebooted",
    "installed_boot": "Installed system booted, its account authenticates",
    "installed_login": "Graphical login started the desktop",
    "installed_health": "Filesystem, release and firmware as expected",
    "installed_critical_apps": "Critical applications opened and closed cleanly",
    "installed_brave": "Browser opened and closed cleanly",
    "applications": "Every desktop entry launched",
}


@dataclass
class Suite:
    name: str
    firmware: str
    iso: str = ""
    build: str = ""
    modules: dict[str, str] = field(default_factory=dict)
    shots: dict[str, Path] = field(default_factory=dict)
    applications: dict[str, str] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)
    weak: list[str] = field(default_factory=list)

    @property
    def result(self) -> str:
        values = list(self.modules.values())
        if self.failures:
            values.append("fail")
        if self.weak:
            values.append("unknown")
        return worst(values)

    @property
    def ok(self) -> bool:
        return bool(self.modules) and self.result == "ok"


def _json(path: Path) -> dict[str, Any]:
    return read_json(path)


def read_suite(directory: Path) -> Suite | None:
    """Read one uploaded artifact directory into the facts the report shows."""
    results = next(iter(sorted(directory.rglob("vars.json"))), None)
    if results is None and not (directory / "testresults").is_dir():
        return None
    work = results.parent if results is not None else directory
    testresults = work / "testresults"
    variables = _json(work / "vars.json")
    suite = Suite(
        name=variables.get("TEST") or directory.name.removeprefix("openqa-"),
        firmware="UEFI" if str(variables.get("UEFI")) == "1" else "BIOS",
        iso=str(variables.get("BIGLINUX_ISO_FILENAME") or variables.get("ISO") or ""),
        build=str(variables.get("BIGLINUX_OPENQA_BUILD") or variables.get("BUILD") or ""),
    )
    for details in sorted(testresults.glob("result-*.json")):
        module = details.stem.removeprefix("result-")
        payload = _json(details)
        steps = payload.get("details")
        steps = steps if isinstance(steps, list) else []
        suite.modules[module] = module_outcome(payload)
        # The last screenshot is the state the module left behind, which is what
        # someone wants to see for a phase that already happened.
        shots = [
            testresults / step["screenshot"]
            for step in steps
            if isinstance(step, dict) and isinstance(step.get("screenshot"), str)
        ]
        for shot in reversed(shots):
            if shot.is_file():
                suite.shots[module] = shot
                break

    metrics = next(iter(sorted(work.rglob("application-metrics.json*"))), None)
    if metrics is not None:
        payload = _json(metrics)
        applications = payload.get("applications")
        applications = applications if isinstance(applications, list) else []
        for application in applications:
            if not isinstance(application, dict):
                continue
            name = str(application.get("desktop_id") or "?")
            status = str(application.get("status") or "")
            suite.applications[name] = status
            if status == "failed":
                reason = str(application.get("error") or "no reason recorded")
                suite.failures[name] = reason.split(": child_pid=")[0][:150]
            elif application.get("validation_mode") in {
                "process-alive",
                "delegated-open",
            }:
                suite.weak.append(name)
    return suite


def encoded_screenshot(path: Path, width_px: int = 1100) -> io.BytesIO | None:
    """Return the smaller of JPEG and PNG for this screen.

    Neither format wins everywhere: a photographic wallpaper is a quarter of the
    size as JPEG, while a flat text console is more than twice. Encoding both and
    keeping the smaller costs milliseconds and is always right.
    """
    try:
        image = Image.open(path).convert("RGB")
    except (OSError, ValueError):
        return None
    if image.width > width_px:
        height = round(image.height * width_px / image.width)
        image = image.resize((width_px, height), Image.LANCZOS)
    candidates = []
    for fmt, options in (
        ("JPEG", {"quality": 88, "subsampling": 0, "optimize": True}),
        ("PNG", {"optimize": True}),
    ):
        buffer = io.BytesIO()
        image.save(buffer, fmt, **options)
        candidates.append(buffer)
    chosen = min(candidates, key=lambda buffer: buffer.getbuffer().nbytes)
    chosen.seek(0)
    return chosen


class Report(FPDF):
    def __init__(self) -> None:
        super().__init__(orientation="L", unit="mm", format="A4")
        self.set_auto_page_break(False)
        self.set_title("BigLinux ISO validation")

    def normalize_text(self, text: str) -> str:
        return super().normalize_text(str(text).encode("latin-1", errors="replace").decode("latin-1"))

    def badge(
        self, x: float, y: float, text: str, colour: tuple[int, int, int]
    ) -> None:
        self.set_fill_color(*colour)
        self.set_text_color(255, 255, 255)
        self.set_font("helvetica", "B", 10)
        width = self.get_string_width(text) + 8
        self.rect(x, y, width, 7, style="F")
        self.set_xy(x, y + 0.6)
        self.cell(width, 6, text, align="C")

    def heading(self, text: str, note: str = "") -> None:
        self.set_text_color(*INK)
        self.set_font("helvetica", "B", 20)
        self.set_xy(16, 14)
        self.cell(0, 10, text)
        if note:
            self.set_font("helvetica", "", 11)
            self.set_text_color(*MUTED)
            self.set_xy(16, 25)
            self.cell(0, 6, note)
        self.set_draw_color(*RULE)
        self.line(16, 33, PAGE[0] - 16, 33)


def cover(pdf: Report, suites: list[Suite], summary: dict[str, Any] | None = None) -> None:
    pdf.add_page()
    everything_ok = all(suite.ok for suite in suites) and bool(suites)
    verdict = summary["result"] if summary else ("ok" if everything_ok else "fail")
    context = summary.get("context", {}) if summary else {}
    iso = next((suite.iso for suite in suites if suite.iso), context.get("iso") or "unknown ISO")
    build = next((suite.build for suite in suites if suite.build), context.get("build", ""))

    pdf.set_text_color(*INK)
    pdf.set_font("helvetica", "B", 34)
    pdf.set_xy(16, 30)
    pdf.cell(0, 14, "BigLinux ISO validation")
    pdf.set_font("helvetica", "", 14)
    pdf.set_text_color(*MUTED)
    pdf.set_xy(16, 47)
    pdf.multi_cell(PAGE[0] - 32, 6, iso[:160])
    pdf.set_xy(16, 63)
    pdf.cell(0, 6, f"{build[:90]}   ·   {datetime.now(UTC):%Y-%m-%d %H:%M UTC}")

    colour = GOOD if verdict == "ok" else BAD if verdict == "fail" else WEAK
    pdf.set_fill_color(*colour)
    pdf.rect(16, 72, PAGE[0] - 32, 26, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("helvetica", "B", 22)
    pdf.set_xy(16, 79)
    pdf.cell(PAGE[0] - 32, 12, {"ok": "PASSED", "fail": "FAILED", "unknown": "INCONCLUSIVE", "softfail": "WARNING", "skipped": "NOT APPLICABLE"}[verdict], align="C")

    # One tile per firmware: the two paths a user can actually boot.
    left = 16.0
    tiles = suites[:3]
    width = (PAGE[0] - 32 - 8) / max(len(tiles), 1)
    for suite in tiles:
        modules_ok = sum(1 for r in suite.modules.values() if r == "ok")
        pdf.set_draw_color(*RULE)
        pdf.set_fill_color(250, 250, 251)
        pdf.rect(left, 108, width - 8, 48, style="DF")
        pdf.set_text_color(*INK)
        pdf.set_font("helvetica", "B", 15)
        pdf.set_xy(left + 6, 114)
        pdf.cell(0, 8, suite.firmware)
        pdf.badge(
            left + 6, 126, LABELS[suite.result], GOOD if suite.ok else BAD if suite.result == "fail" else WEAK
        )
        pdf.set_text_color(*MUTED)
        pdf.set_font("helvetica", "", 11)
        pdf.set_xy(left + 6, 138)
        pdf.cell(0, 6, f"{modules_ok}/{len(suite.modules)} stages")
        pdf.set_xy(left + 6, 145)
        ok = sum(1 for value in suite.applications.values() if value == "passed")
        pdf.cell(
            0,
            6,
            f"{ok}/{len(suite.applications)} applications"
            if suite.applications
            else "",
        )
        left += width


def phase_pages(pdf: Report, suite: Suite) -> None:
    for title, modules in PHASES:
        present = [m for m in modules if m in suite.modules]
        if not present:
            continue
        # Three to a page: every stage of the phase gets shown, none silently
        # dropped, and the screenshots stay large enough to read.
        groups = [present[i : i + 3] for i in range(0, len(present), 3)]
        for number, group in enumerate(groups, start=1):
            pdf.add_page()
            suffix = "" if len(groups) == 1 else f" ({number}/{len(groups)})"
            pdf.heading(f"{title} · {suite.firmware}{suffix}")
            column = 16.0
            span = (PAGE[0] - 32) / 3
            for module in group:
                result = suite.modules[module]
                pdf.badge(
                    column,
                    40,
                    LABELS.get(result, "Inconclusivo"),
                    GOOD if result == "ok" else BAD if result == "fail" else WEAK,
                )
                pdf.set_text_color(*INK)
                pdf.set_font("helvetica", "", 10)
                pdf.set_xy(column, 50)
                pdf.multi_cell(span - 6, 5, CAPTIONS.get(module, module) if result == "ok" else module.replace("_", " "))
                shot = suite.shots.get(module)
                if shot:
                    stream = encoded_screenshot(shot)
                    if stream is not None:
                        pdf.image(stream, x=column, y=64, w=span - 8)
                column += span


def applications_page(pdf: Report, suites: list[Suite]) -> None:
    combined = [s for s in suites if s.applications]
    if not combined:
        return
    pdf.add_page()
    # Distinct entries: the firmware jobs and the shards report overlapping sets,
    # so summing them would invent applications that do not exist.
    everything: dict[str, str] = {}
    for suite in combined:
        everything.update(suite.applications)
    passed = sum(1 for value in everything.values() if value == "passed")
    pdf.heading(
        "Applications",
        f"{passed} of {len(everything)} desktop entries opened and closed cleanly",
    )

    merged: dict[str, str] = {}
    for suite in combined:
        merged.update(suite.failures)
    failures = sorted(merged.items())
    weak = sorted({name for suite in combined for name in suite.weak})
    y = 44.0
    if failures:
        pdf.set_text_color(*BAD)
        pdf.set_font("helvetica", "B", 12)
        pdf.set_xy(16, y)
        pdf.cell(0, 6, "Failed")
        y += 9
        for name, reason in failures[:12]:
            pdf.set_text_color(*INK)
            pdf.set_font("helvetica", "B", 10)
            pdf.set_xy(16, y)
            pdf.cell(0, 5, name)
            pdf.set_text_color(*MUTED)
            pdf.set_font("helvetica", "", 9)
            pdf.set_xy(16, y + 5)
            pdf.multi_cell(PAGE[0] - 32, 4, reason)
            y = pdf.get_y() + 3
    if weak:
        pdf.set_text_color(*WEAK)
        pdf.set_font("helvetica", "B", 12)
        pdf.set_xy(16, y + 2)
        pdf.cell(0, 6, "Opened, but the window could not be inspected")
        pdf.set_text_color(*MUTED)
        pdf.set_font("helvetica", "", 9)
        pdf.set_xy(16, y + 11)
        pdf.multi_cell(PAGE[0] - 32, 4, ", ".join(weak))
    if not failures and not weak:
        pdf.set_text_color(*GOOD)
        pdf.set_font("helvetica", "B", 13)
        pdf.set_xy(16, y)
        pdf.cell(0, 8, "No failures.")


def outcome_pages(pdf: Report, summary: dict[str, Any]) -> None:
    """Always show nonvisual results, including phases without screenshots."""
    rows = ["Resultado: " + LABELS[summary["result"]]]
    rows += [str(p) for p in summary.get("problems", [])]
    rows += [f"{m['plan']} / {m['name']}: {LABELS[m['result']]}" for m in summary.get("modules", [])]
    rows += [f"{a['plan']} / {a['name']}: {LABELS[a['result']]}" for a in summary.get("applications", [])]
    pdf.add_page()
    pdf.heading("Resultados e diagnóstico", "Capturas são opcionais; ausência de evidência não significa aprovação.")
    pdf.set_font("helvetica", "", 10)
    pdf.set_text_color(*INK)
    pdf.set_xy(16, 42)
    # Wrap before rendering so long failure lists never overflow the page.
    import textwrap
    for row in rows:
        for line in textwrap.wrap(row, width=115, break_long_words=True) or [""]:
            if pdf.get_y() > 187:
                pdf.add_page()
                pdf.heading("Resultados e diagnóstico — continuação")
                pdf.set_font("helvetica", "", 10)
                pdf.set_text_color(*INK)
                pdf.set_xy(16, 42)
            y = pdf.get_y()
            pdf.cell(PAGE[0] - 32, 5, line)
            pdf.set_xy(16, y + 5)


def build(artifacts_root: Path, output: Path, summary: dict[str, Any] | None = None) -> int:
    summary = summary or summarize(artifacts_root)
    suites = [suite for directory in workdirs(artifacts_root)
              for suite in [read_suite(directory)] if suite is not None]
    firmware_first = sorted(suites, key=lambda s: (not s.shots, s.firmware))
    pdf = Report()
    cover(pdf, firmware_first, summary)
    outcome_pages(pdf, summary)
    for suite in firmware_first:
        phase_pages(pdf, suite)
    # The textual outcome pages already include all apps without merging away
    # failures from another plan or limiting diagnostics to twelve entries.
    output.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return build(args.artifacts_root, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
