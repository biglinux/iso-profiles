#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Publish reports after success or failure; reporting never changes test results.

The dependency-free summary is written first. Optional renderers replace it
atomically, so a broken renderer or missing PDF dependency still leaves a report.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import tempfile
import textwrap
from pathlib import Path
from typing import Any

from report_outcome import LABELS, environment_context, summarize, read_json


def latest_artifacts(root: Path, run_id: str) -> list[Path]:
    """Select latest attempts numerically, never fall back to an older green run."""
    if not re.fullmatch(r"[0-9]+", run_id):
        raise ValueError("a numeric run ID is required")
    pattern = re.compile(r"^(openqa-.+)-" + re.escape(run_id) + r"-([0-9]+)$")
    selected: dict[str, tuple[int, Path]] = {}
    if not root.exists():
        return []
    for path in sorted(root.iterdir()):
        match = pattern.fullmatch(path.name)
        if not path.is_dir() or path.is_symlink() or not match:
            continue
        key, attempt = match.group(1), int(match.group(2))
        if attempt > selected.get(key, (-1, path))[0]:
            selected[key] = (attempt, path)
    return [item[1] for _, item in sorted(selected.items())]


def summary_lines(summary: dict[str, Any]) -> list[str]:
    context = summary.get("context", {})
    lines = ["Relatório openQA — " + LABELS[summary["result"]],
             "ISO: " + str(context.get("iso") or "não identificada"),
             "Build: " + str(context.get("build") or "não identificado"),
             "Commit: " + str(context.get("commit") or "não identificado"),
             "Execução: " + str(context.get("run_id") or "local"), ""]
    for key, label in (("runner_exit_code", "Saída do executor"), ("isotovideo_exit_code", "Saída do isotovideo")):
        if context.get(key) is not None:
            lines.append(f"{label}: {context[key]}")
    for label, key in (("Módulos", "module_counts"), ("Aplicativos", "application_counts")):
        counts = summary.get(key, {})
        lines.append(f"{label}: {counts.get('ok', 0)} passaram; {counts.get('fail', 0)} falharam; "
                     f"{counts.get('unknown', 0)} inconclusivos; {counts.get('skipped', 0)} não aplicáveis.")
    lines += ["", "Diagnóstico:"] + (summary.get("problems") or ["Nenhuma falha registrada nos resultados disponíveis."])
    for error in summary.get("report_errors", []):
        lines.append("Falha na geração detalhada: " + error)
    lines += ["", "Este resumo não certifica acessibilidade completa. Capturas são apenas diagnóstico."]
    return lines


def emergency_pdf(path: Path, lines: list[str]) -> None:
    """Small PDF 1.4 text fallback with no packages, fonts or network required."""
    wrapped = [line for row in lines for line in (textwrap.wrap(row, 88) or [""])]
    pages = [wrapped[n:n + 48] for n in range(0, len(wrapped), 48)] or [[]]
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>", b"",
                           b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    kids = []
    for page in pages:
        page_id = len(objects) + 1
        content_id = page_id + 1
        kids.append(f"{page_id} 0 R")
        objects.append((f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                        f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>").encode())
        commands = [b"BT /F1 10 Tf 13 TL 42 795 Td"]
        for row in page:
            encoded = row.encode("cp1252", errors="replace")
            encoded = encoded.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
            commands.append(b"(" + encoded + b") Tj T*")
        content = b"\n".join(commands + [b"ET"])
        objects.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")
    objects[1] = (f"<< /Type /Pages /Count {len(pages)} /Kids [{' '.join(kids)}] >>").encode()
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    start = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend((f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n").encode())
    path.write_bytes(output)


def write_summary(output: Path, summary: dict[str, Any], pdf: bool) -> None:
    lines = summary_lines(summary)
    (output / "RESULTADO.md").write_text("# " + "\n\n".join(lines) + "\n", encoding="utf-8")
    document = ("<!doctype html><html lang='pt-BR'><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<title>Relatório openQA</title><body><main><h1>Relatório openQA</h1>"
                "<p>Relatório resumido; consulte RESULTADO.json e os diagnósticos disponíveis.</p>"
                + "".join("<p>" + html.escape(line) + "</p>" for line in lines) + "</main></body></html>")
    (output / "biglinux-validation-report.html").write_text(document, encoding="utf-8")
    (output / "RESULTADO.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if pdf:
        emergency_pdf(output / "biglinux-iso-validation.pdf", lines)


def finalize(root: Path, output: Path, *, pdf: bool = False,
             context: dict[str, Any] | None = None) -> int:
    output.mkdir(parents=True, exist_ok=True)
    if context is None:
        context = environment_context()
        # Regenerating a report must not erase an earlier executor failure.
        if not context.get("status"):
            context = read_json(output / "run-status.json") or context
    (output / "run-status.json").write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    errors = []
    try:
        summary = summarize(root, context)
    except Exception as error:
        # Report untrusted/malformed artifacts without printing payloads/secrets.
        summary = {"schema_version": 1, "result": "unknown", "context": context,
                   "problems": ["Não foi possível interpretar os resultados disponíveis."],
                   "modules": [], "applications": []}
        errors.append("result-reader: " + type(error).__name__)
    summary["report_errors"] = errors
    summary["formats"] = {"html": "summary", "markdown": "summary"}
    if pdf:
        summary["formats"]["pdf"] = "summary"
    write_summary(output, summary, pdf)
    try:
        from generate_report import build
        with tempfile.TemporaryDirectory(dir=output) as temporary:
            temporary = Path(temporary)
            build(root, temporary / "report.html", temporary / "report.md", summary)
            (temporary / "report.html").replace(output / "biglinux-validation-report.html")
            (temporary / "report.md").replace(output / "RESULTADO.md")
        summary["formats"].update(html="detailed", markdown="detailed")
    except Exception as error:
        errors.append("html-markdown: " + type(error).__name__)
    if pdf:
        try:
            from build_pdf_report import build as build_pdf
            with tempfile.TemporaryDirectory(dir=output) as temporary:
                candidate = Path(temporary) / "report.pdf"
                build_pdf(root, candidate, summary)
                candidate.replace(output / "biglinux-iso-validation.pdf")
            summary["formats"]["pdf"] = "detailed"
        except Exception as error:
            errors.append("pdf: " + type(error).__name__)
    if errors:
        # All fallback formats consistently identify the incomplete report.
        summary["formats"] = {"html": "summary", "markdown": "summary", **({"pdf": "summary"} if pdf else {})}
        write_summary(output, summary, pdf)
    else:
        (output / "RESULTADO.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # A failed ISO with a successfully generated report returns 0 here. A failed
    # renderer returns 1 AFTER publishing its fallback, for CI to flag separately.
    return int(bool(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--pdf", action="store_true")
    parser.add_argument("--latest-attempts", action="store_true")
    args = parser.parse_args()
    context = environment_context()
    if args.latest_attempts:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            try:
                for path in latest_artifacts(args.results_root, str(context.get("run_id", ""))):
                    shutil.copytree(path, root / path.name, symlinks=True)
            except (OSError, ValueError):
                context.setdefault("steps", {})["artifact-selection"] = {"outcome": "failure"}
                finalize(root, args.output_dir, pdf=args.pdf, context=context)
                return 1
            return finalize(root, args.output_dir, pdf=args.pdf, context=context)
    return finalize(args.results_root, args.output_dir, pdf=args.pdf)


if __name__ == "__main__":
    raise SystemExit(main())
