# SPDX-License-Identifier: GPL-2.0-or-later
"""Shared, conservative outcome handling for all openQA report formats."""
from __future__ import annotations

import gzip
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

PRIORITY = {"skipped": 0, "ok": 1, "softfail": 2, "unknown": 3, "fail": 4}
LABELS = {"ok": "Passou", "fail": "Falhou", "softfail": "Alerta",
          "unknown": "Inconclusivo", "skipped": "Não aplicável"}
ALIASES = {"passed": "ok", "success": "ok", "failed": "fail", "failure": "fail",
           "none": "unknown", "unk": "unknown", "inconclusive": "unknown",
           "cancelled": "unknown", "timed_out": "fail"}


def normalize(value: Any) -> str:
    value = value.lower() if isinstance(value, str) else "unknown"
    value = ALIASES.get(value, value)
    return value if value in PRIORITY else "unknown"


def worst(values: list[str]) -> str:
    return max((normalize(v) for v in values), key=PRIORITY.get, default="unknown")


def read_json(path: Path) -> dict[str, Any]:
    try:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as stream:
            value = json.load(stream)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, UnicodeError, EOFError):
        return {}


def module_outcome(payload: dict[str, Any]) -> str:
    """Honor the module result, including failures with only successful details."""
    details = payload.get("details", [])
    values = [normalize(d["result"]) for d in details
              if isinstance(d, dict) and "result" in d] if isinstance(details, list) else []
    if "result" in payload:
        # Informational details must not turn a skipped/unknown module into OK.
        top = normalize(payload["result"])
        if "fail" in values:
            return "fail"
        return worst([top, "softfail"]) if "softfail" in values else top
    return worst(values)


def workdirs(root: Path) -> list[Path]:
    """Partial results remain discoverable when vars.json was never written."""
    found = {p.parent for p in root.rglob("vars.json")}
    found.update(p.parent for p in root.rglob("testresults") if p.is_dir())
    return sorted(p for p in found if read_json(p / "vars.json").get("DISTRI", "biglinux") == "biglinux")


def environment_context() -> dict[str, Any]:
    """Persist only outcomes/identifiers, never GitHub step outputs or secrets."""
    result: dict[str, Any] = {"schema_version": 1}
    for field, variable in {
        "name": "REPORT_NAME", "iso": "ISO_FILENAME", "build": "OPENQA_BUILD",
        "commit": "GITHUB_SHA", "run_id": "GITHUB_RUN_ID", "attempt": "GITHUB_RUN_ATTEMPT",
        "status": "REPORT_STATUS", "runner_exit_code": "REPORT_RUNNER_EXIT_CODE",
        "isotovideo_exit_code": "REPORT_ISOTOVIDEO_EXIT_CODE",
    }.items():
        if os.environ.get(variable):
            result[field] = os.environ[variable]
    for field, variable in (("jobs", "REPORT_NEEDS_JSON"), ("steps", "REPORT_STEPS_JSON")):
        raw = os.environ.get(variable, "{}")
        try:
            items = json.loads(raw)
            if not isinstance(items, dict):
                raise ValueError("not an object")
            result[field] = {name: {key: item[key] for key in ("result", "outcome", "conclusion")
                                    if key in item and isinstance(item[key], str)}
                             for name, item in items.items() if isinstance(item, dict)}
        except (ValueError, TypeError):
            result[field] = {"invalid-context": {"result": "unknown"}}
    try:
        plans = json.loads(os.environ.get("REPORT_EXPECTED_PLANS", "[]") or "[]")
        if not isinstance(plans, list):
            raise ValueError("not a list")
        result["expected_plans"] = [p["name"] for p in plans
                                    if isinstance(p, dict) and isinstance(p.get("name"), str)]
    except (ValueError, TypeError):
        result["jobs"]["invalid-plan-context"] = {"result": "unknown"}
    return result


def summarize(root: Path, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Missing evidence is unknown, not successful; a known failure stays failed."""
    statuses: list[str] = []
    problems: list[str] = []
    modules: list[dict[str, Any]] = []
    applications: list[dict[str, Any]] = []
    observed_plans: set[str] = set()
    for directory in workdirs(root):
        variables = read_json(directory / "vars.json")
        name = str(variables.get("TEST") or directory.name)
        observed_plans.add(name)
        present: set[str] = set()
        for path in sorted((directory / "testresults").glob("result-*.json")):
            payload = read_json(path)
            value = module_outcome(payload)
            module = path.stem.removeprefix("result-")
            present.add(module)
            modules.append({"plan": name, "name": module, "result": value})
            statuses.append(value)
            if value in {"unknown", "fail"}:
                problems.append(f"{name} / {module}: {LABELS[value]}")
        order = directory / "testresults" / "test_order.json"
        if not order.exists():
            order = directory / "test_order.json"
        if order.exists():
            try:
                expected = json.loads(order.read_text(encoding="utf-8"))
                if not isinstance(expected, list):
                    raise ValueError("invalid order")
                missing = [str(item["name"]) for item in expected
                           if isinstance(item, dict) and "name" in item and item["name"] not in present]
                if missing:
                    statuses.append("unknown")
                    problems.append(f"{name}: módulos sem resultado: {', '.join(missing)}")
            except (OSError, ValueError, UnicodeError):
                statuses.append("unknown")
                problems.append(f"{name}: test_order.json ilegível")
        if not present:
            statuses.append("unknown")
            problems.append(f"{name}: nenhum módulo executado ou resultado disponível")
        for basename in ("application-metrics.json", "installed-application-smoke.json"):
            paths = sorted(directory.rglob(basename)) or sorted(directory.rglob(basename + ".gz"))
            for path in paths:
                payload = read_json(path)
                entries = payload.get("applications")
                if not isinstance(entries, list):
                    statuses.append("unknown")
                    problems.append(f"{name}: {basename} ilegível ou incompleto")
                    continue
                coverage = payload.get("coverage", {})
                if isinstance(coverage, dict) and isinstance(coverage.get("not_installed_desktop_ids"), list):
                    applications.extend({"plan": name, "name": str(desktop_id), "result": "skipped"}
                                        for desktop_id in coverage["not_installed_desktop_ids"])
                for item in entries:
                    if not isinstance(item, dict):
                        statuses.append("unknown")
                        continue
                    value = normalize(item.get("status"))
                    applications.append({"plan": name, "name": str(item.get("desktop_id") or item.get("name") or "?"), "result": value})
                    statuses.append(value)
                    if value == "fail":
                        problems.append(f"{name}: aplicativo {applications[-1]['name']} falhou")
        for path in directory.rglob("nonvisual-contracts.json"):
            cases = read_json(path).get("cases")
            if not isinstance(cases, list) or not cases:
                statuses.append("unknown")
            else:
                statuses.extend(normalize(c.get("status")) if isinstance(c, dict) else "unknown" for c in cases)

    contexts = []
    for path in sorted(root.rglob("run-status.json")):
        current = read_json(path)
        if not current:
            statuses.append("unknown")
            problems.append("Contexto de execução run-status.json ilegível ou vazio.")
        contexts.append(current)
    if context:
        contexts.append(context)
    for current in contexts:
        name = str(current.get("name") or "execução")
        if name != "release-gate":
            observed_plans.add(name)
        if current.get("status"):
            statuses.append(normalize(current["status"]))
        for field, label in (("runner_exit_code", "executor"), ("isotovideo_exit_code", "isotovideo")):
            code = current.get(field)
            if code is not None and str(code) != "0":
                statuses.append("fail")
                problems.append(f"{name}: {label} terminou com código {code}")
        jobs = current.get("jobs", {})
        steps = current.get("steps", {})
        if not isinstance(jobs, dict) or not isinstance(steps, dict):
            statuses.append("unknown")
            problems.append(f"{name}: contexto do executor ilegível")
            continue
        for job, item in jobs.items():
            if not isinstance(item, dict):
                statuses.append("unknown")
                continue
            value = normalize(item.get("result"))
            value = "unknown" if value == "skipped" else value
            statuses.append(value)
            if value != "ok":
                problems.append(f"{name} / job {job}: {item.get('result', 'unknown')}")
        for step, item in steps.items():
            if not isinstance(item, dict):
                statuses.append("unknown")
                continue
            # Skipped steps are normal for mutually exclusive download paths.
            if item.get("outcome") in {"failure", "cancelled"}:
                statuses.append(normalize(item["outcome"]))
                problems.append(f"{name} / etapa {step}: {item['outcome']}")
    if context:
        missing_plans = set(context.get("expected_plans", [])) - observed_plans
        if missing_plans:
            statuses.append("unknown")
            problems.append("Planos sem artefato: " + ", ".join(sorted(missing_plans)))
    if context:
        for name in context.get("expected_plans", []):
            if name in observed_plans and not any(m["plan"] == name for m in modules):
                statuses.append("unknown")
                problems.append(f"{name}: artefato sem resultados de módulos")
    if not modules:
        statuses.append("unknown")
        problems.append("Sem resultados de módulos; não há aprovação da ISO confirmada.")
    elif all(m["result"] == "skipped" for m in modules):
        statuses.append("unknown")
        problems.append("Todos os módulos foram pulados; a ISO não foi validada.")
    return {"schema_version": 1, "result": worst(statuses), "modules": modules,
            "applications": applications, "module_counts": dict(Counter(m["result"] for m in modules)),
            "application_counts": dict(Counter(a["result"] for a in applications)),
            "problems": list(dict.fromkeys(problems)), "context": context or {}}
