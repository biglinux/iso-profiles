#!/usr/bin/env python3
"""Build a self-contained human-readable report from openQA result files."""

from __future__ import annotations

import argparse
import gzip
import html
import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RESULT_PRIORITY = {
    "fail": 4,
    "failed": 4,
    "softfail": 3,
    "unknown": 2,
    "ok": 1,
    "passed": 1,
}
RESULT_LABEL = {
    "fail": "Falhou",
    "failed": "Falhou",
    "softfail": "Alerta",
    "unknown": "Inconclusivo",
    "ok": "Passou",
    "passed": "Passou",
    "skipped": "Ignorado",
}


@dataclass(frozen=True)
class ModuleResult:
    name: str
    result: str
    duration_seconds: float | None
    checks: int
    screenshots: int


def load_json(path: Path) -> dict[str, Any]:
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                value = json.load(stream)
        else:
            value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def module_result(path: Path, runtime_seconds: float | None = None) -> ModuleResult:
    payload = load_json(path)
    details = payload.get("details")
    if not isinstance(details, list):
        details = []

    results: list[str] = []
    screenshots = 0
    for detail in details:
        if not isinstance(detail, dict):
            continue
        result = detail.get("result")
        if isinstance(result, str):
            results.append(result)
        if isinstance(detail.get("screenshot"), str):
            screenshots += 1

    result = max(
        results, key=lambda value: RESULT_PRIORITY.get(value, 2), default="unknown"
    )
    return ModuleResult(
        name=path.stem.removeprefix("details-"),
        result=result,
        duration_seconds=runtime_seconds,
        checks=len(details),
        screenshots=screenshots,
    )


def load_module_runtimes(job_dir: Path | None) -> dict[str, float]:
    if job_dir is None:
        return {}
    try:
        log = (job_dir / "autoinst-log.txt").read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        return {}
    return {
        match.group("module"): float(match.group("seconds"))
        for match in re.finditer(
            r"\|\|\| finished (?P<module>[A-Za-z0-9_]+) tests \(runtime: (?P<seconds>[0-9.]+) s\)",
            log,
        )
    }


def find_biglinux_job(results_root: Path) -> tuple[Path | None, dict[str, Any]]:
    candidates = find_biglinux_jobs(results_root)
    return max(candidates, key=lambda item: item[0].stat().st_mtime, default=(None, {}))


def find_biglinux_jobs(results_root: Path) -> list[tuple[Path, dict[str, Any]]]:
    candidates: list[tuple[Path, dict[str, Any]]] = []
    for vars_path in results_root.rglob("vars.json"):
        variables = load_json(vars_path)
        if variables.get("DISTRI") == "biglinux":
            candidates.append((vars_path.parent, variables))
    return sorted(candidates, key=lambda item: item[0].stat().st_mtime)


def load_application_metrics(
    job_dir: Path | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if job_dir is None:
        return {}, []
    candidates = sorted(
        [
            *job_dir.rglob("application-metrics.json"),
            *job_dir.rglob("application-metrics.json.gz"),
        ],
        key=lambda path: path.suffix == ".gz",
    )
    if not candidates:
        return {}, []
    payload = load_json(candidates[0])
    system_value = payload.get("system")
    system: dict[str, Any] = system_value if isinstance(system_value, dict) else {}
    applications = payload.get("applications")
    if not isinstance(applications, list):
        applications = []
    return system, [item for item in applications if isinstance(item, dict)]


def load_application_metrics_from_jobs(
    jobs: list[tuple[Path, dict[str, Any]]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    system: dict[str, Any] = {}
    applications: list[dict[str, Any]] = []
    for job, variables in jobs:
        job_system, job_applications = load_application_metrics(job)
        if job_system:
            system = job_system
        label = variables.get("BUILD") or variables.get("TEST") or job.name
        firmware = variables.get("UEFI") and "UEFI" or "BIOS"
        for application in job_applications:
            applications.append({"job": label, "firmware": firmware, **application})
    if len(jobs) > 1:
        system = {**system, "jobs_tested": len(jobs)}
    return system, applications


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def metric(value: Any, unit: str = "") -> str:
    if value is None or value == "":
        return '<span class="muted">Não coletado</span>'
    suffix = f" {esc(unit)}" if unit else ""
    return f"{esc(value)}{suffix}"


def duration(value: float | None) -> str:
    if value is None:
        return "Não coletado"
    if value < 60:
        return f"{value:.1f} s"
    minutes, seconds = divmod(value, 60)
    return f"{int(minutes)} min {seconds:.0f} s"


def status_badge(result: str) -> str:
    normalized = result.lower() if result else "unknown"
    label = RESULT_LABEL.get(normalized, normalized.capitalize())
    return f'<span class="badge badge-{esc(normalized)}">{esc(label)}</span>'


def atspi_status(application: dict[str, Any]) -> str | None:
    if (
        application.get("status") == "skipped"
        or application.get("accessible_window") is None
    ):
        return None
    if application.get("validation_mode") == "process-start":
        return None
    return "passed" if application.get("status") == "passed" else "fail"


def validation_badge(application: dict[str, Any]) -> str:
    if application.get("validation_mode") in {"x11-open", "x11-window"}:
        return '<span class="badge badge-softfail">Fallback X11</span>'
    if application.get("validation_mode") == "process-start":
        return '<span class="badge badge-softfail">Início do processo</span>'
    accessibility = atspi_status(application)
    return status_badge(accessibility) if accessibility else metric(None)


def render_report(
    variables: dict[str, Any],
    modules: list[ModuleResult],
    system: dict[str, Any],
    applications: list[dict[str, Any]],
) -> str:
    overall = max(
        (module.result for module in modules),
        key=lambda value: RESULT_PRIORITY.get(value, 2),
        default="unknown",
    )
    passed = sum(module.result in {"ok", "passed"} for module in modules)
    failed = sum(module.result == "fail" for module in modules)
    total_duration = sum(module.duration_seconds or 0 for module in modules)
    passed_apps = sum(app.get("status") == "passed" for app in applications)
    failed_apps = sum(app.get("status") == "failed" for app in applications)
    skipped_apps = sum(app.get("status") == "skipped" for app in applications)

    module_rows = (
        "".join(
            f"""
        <tr>
          <th scope="row">{esc(module.name.replace("_", " ").title())}</th>
          <td>{status_badge(module.result)}</td>
          <td>{esc(duration(module.duration_seconds))}</td>
          <td>{module.checks}</td>
          <td>{module.screenshots}</td>
        </tr>"""
            for module in modules
        )
        or '<tr><td colspan="5" class="empty">Nenhum módulo do openQA foi encontrado.</td></tr>'
    )

    application_rows = (
        "".join(
            f"""
        <tr>
          <th scope="row"><span class="app-name">{esc(app.get("name", "Aplicativo sem nome"))}</span>
            <span class="app-category">{esc(app.get("category", "Sem categoria"))}</span></th>
          <td>{status_badge(str(app.get("status", "unknown")))}</td>
          <td>{metric(app.get("open_seconds"), "s")}</td>
          <td>{metric(app.get("rss_mib_peak"), "MiB")}</td>
          <td>{metric(app.get("pss_mib_peak"), "MiB")}</td>
          <td>{metric(app.get("process_count_peak"))}</td>
          <td>{metric(app.get("mem_available_after_open_mib"), "MiB")}</td>
          <td>{validation_badge(app)}</td>
          <td>{esc(app.get("interaction", app.get("action", "—")))}</td>
          <td>{esc(app.get("error", app.get("skip_reason", app.get("cleanup_error", "—"))))}</td>
        </tr>"""
            for app in applications
        )
        or """
        <tr><td colspan="10" class="empty">
          As métricas por aplicativo ainda não foram anexadas a este job.
        </td></tr>"""
    )

    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    distribution = variables.get("DISTRI", "BigLinux")
    if str(distribution).lower() == "biglinux":
        distribution = "BigLinux"
    title_bits = [distribution, variables.get("VERSION"), variables.get("FLAVOR")]
    product = " ".join(str(value) for value in title_bits if value)

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Relatório de validação — {esc(product)}</title>
  <style>
    :root {{ color-scheme: light; --ink:#172033; --muted:#5d687b; --line:#dce2ea;
      --surface:#fff; --canvas:#f3f6fa; --brand:#3457d5; --ok:#12623b; --ok-bg:#e4f5eb;
      --fail:#a12626; --fail-bg:#fde8e7; --warn:#805500; --warn-bg:#fff1c9; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--canvas); color:var(--ink); font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }}
    main {{ width:min(1440px,calc(100% - 32px)); margin:32px auto 64px; }}
    header {{ padding:32px; border-radius:18px; color:#fff; background:linear-gradient(135deg,#233b93,#436be6); box-shadow:0 14px 34px rgba(35,59,147,.18); }}
    .eyebrow {{ margin:0 0 6px; font-size:.78rem; font-weight:750; letter-spacing:.1em; text-transform:uppercase; opacity:.78; }}
    h1 {{ margin:0; font-size:clamp(1.75rem,4vw,2.6rem); line-height:1.12; }}
    header p {{ margin:10px 0 0; opacity:.86; }}
    .summary {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin:18px 0; }}
    .card,section {{ background:var(--surface); border:1px solid var(--line); border-radius:14px; box-shadow:0 5px 18px rgba(23,32,51,.05); }}
    .card {{ padding:18px; }} .card .label {{ display:block; color:var(--muted); font-size:.82rem; }}
    .card strong {{ display:block; margin-top:3px; font-size:1.42rem; line-height:1.25; }}
    section {{ margin-top:18px; overflow:hidden; }}
    .section-head {{ padding:21px 24px 14px; }} h2 {{ margin:0; font-size:1.18rem; }}
    .section-head p {{ margin:4px 0 0; color:var(--muted); }}
    .table-wrap {{ overflow-x:auto; }} table {{ width:100%; border-collapse:collapse; }}
    th,td {{ padding:13px 14px; border-top:1px solid var(--line); text-align:left; vertical-align:middle; white-space:nowrap; }}
    thead th {{ color:var(--muted); background:#f8fafc; font-size:.76rem; line-height:1.3; text-transform:uppercase; letter-spacing:.04em; white-space:normal; }}
    tbody th {{ font-weight:650; }} .app-name,.app-category {{ display:block; }}
    tbody td:last-child {{ min-width:140px; white-space:normal; }}
    .app-category {{ color:var(--muted); font-size:.8rem; font-weight:450; }}
    .badge {{ display:inline-flex; align-items:center; min-height:26px; padding:3px 9px; border-radius:999px; font-size:.8rem; font-weight:750; }}
    .badge-ok,.badge-passed {{ color:var(--ok); background:var(--ok-bg); }}
    .badge-fail,.badge-failed {{ color:var(--fail); background:var(--fail-bg); }}
    .badge-softfail,.badge-unknown {{ color:var(--warn); background:var(--warn-bg); }}
    .badge-skipped {{ color:var(--muted); background:#edf0f4; }}
    .muted,.empty {{ color:var(--muted); }} .empty {{ padding:28px; text-align:center; white-space:normal; }}
    .facts {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); margin:0; padding:0 24px 24px; gap:14px 24px; }}
    .facts div {{ min-width:0; }} .facts dt {{ color:var(--muted); font-size:.8rem; }} .facts dd {{ margin:2px 0 0; font-weight:650; overflow-wrap:anywhere; }}
    .method {{ padding:0 24px 22px; color:var(--muted); }} footer {{ margin-top:18px; color:var(--muted); text-align:center; font-size:.82rem; }}
    @media (max-width:760px) {{ .summary {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .facts {{ grid-template-columns:1fr 1fr; }} header {{ padding:24px; }} }}
    @media (max-width:460px) {{ main {{ width:min(100% - 20px,1440px); margin-top:10px; }} .summary,.facts {{ grid-template-columns:1fr; }} }}
    @media print {{ body {{ background:#fff; }} main {{ width:100%; margin:0; }} header,section,.card {{ box-shadow:none; }} section {{ break-inside:avoid; }} .table-wrap {{ overflow:visible; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <p class="eyebrow">BigLinux · validação automatizada</p>
    <h1>{esc(product or "BigLinux")}</h1>
    <p>Build {esc(variables.get("BUILD", "não identificado"))} · relatório gerado em {generated_at}</p>
  </header>

  <div class="summary" aria-label="Resumo da execução">
    <div class="card"><span class="label">Resultado geral</span><strong>{status_badge(overall)}</strong></div>
    <div class="card"><span class="label">Módulos</span><strong>{passed} passaram · {failed} falharam</strong></div>
    <div class="card"><span class="label">Duração observada</span><strong>{esc(duration(total_duration) if modules else "Não coletada")}</strong></div>
    <div class="card"><span class="label">Aplicativos</span><strong>{passed_apps} passaram · {failed_apps} falharam · {skipped_apps} ignorados</strong></div>
  </div>

  <section aria-labelledby="modules-title">
    <div class="section-head"><h2 id="modules-title">Etapas da validação</h2><p>Resultado e duração observada de cada módulo do openQA.</p></div>
    <div class="table-wrap"><table><thead><tr><th scope="col">Módulo</th><th scope="col">Resultado</th><th scope="col">Duração</th><th scope="col">Verificações</th><th scope="col">Capturas</th></tr></thead><tbody>{module_rows}</tbody></table></div>
  </section>

  <section aria-labelledby="apps-title">
    <div class="section-head"><h2 id="apps-title">Aplicativos</h2><p>Todos os Desktop Entries descobertos, confirmando a abertura por AT-SPI quando possível. Quando o aplicativo não expõe AT-SPI, é usado fallback X11 por PID; entradas de terminal ou daemon são validadas pelo início do processo.</p></div>
    <div class="table-wrap"><table><thead><tr><th scope="col">Aplicativo</th><th scope="col">Resultado</th><th scope="col">Abertura</th><th scope="col">RSS pico</th><th scope="col">PSS pico</th><th scope="col">Processos pico</th><th scope="col">Mem. disponível aberto</th><th scope="col">Validação</th><th scope="col">Evento</th><th scope="col">Motivo</th></tr></thead><tbody>{application_rows}</tbody></table></div>
  </section>

  <section aria-labelledby="system-title">
    <div class="section-head"><h2 id="system-title">Ambiente testado</h2><p>Identidade da ISO e recursos atribuídos à máquina virtual.</p></div>
    <dl class="facts">
      <div><dt>ISO</dt><dd>{metric(variables.get("ISO"))}</dd></div>
      <div><dt>Arquitetura</dt><dd>{metric(variables.get("ARCH"))}</dd></div>
      <div><dt>Kernel</dt><dd>{metric(system.get("kernel"))}</dd></div>
      <div><dt>CPU da VM</dt><dd>{metric(variables.get("QEMUCPUS"), "vCPU")}</dd></div>
      <div><dt>Memória da VM</dt><dd>{metric(variables.get("QEMURAM"), "MiB")}</dd></div>
      <div><dt>Sessão gráfica</dt><dd>{metric(system.get("desktop"))}</dd></div>
      <div><dt>Barramento AT-SPI</dt><dd>{metric(system.get("accessibility_bus"))}</dd></div>
      <div><dt>Jobs BigLinux agregados</dt><dd>{metric(system.get("jobs_tested"), "jobs")}</dd></div>
      <div><dt>Job</dt><dd>{metric(variables.get("NAME"))}</dd></div>
      <div><dt>Cenário</dt><dd>{metric(variables.get("TEST"))}</dd></div>
    </dl>
  </section>

  <section aria-labelledby="method-title">
    <div class="section-head"><h2 id="method-title">Como interpretar</h2></div>
    <div class="method">Os tempos dos módulos vêm dos registros do os-autoinst. Cada aplicativo é aprovado quando o comando do Desktop Entry inicia e expõe uma janela AT-SPI utilizável. Se isso não for possível, o teste procura uma janela X11 pertencente ao processo iniciado; entradas sem janela são aprovadas somente quando o processo inicia. RSS e PSS são os picos agregados do processo e dos descendentes; PSS evita contar repetidamente bibliotecas compartilhadas. Não há validação por título, menu, tecla ou screenshot para declarar que um programa abriu.</div>
  </section>
  <footer>Relatório estático e autocontido · nenhum dado é enviado para serviços externos</footer>
</main>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    jobs = find_biglinux_jobs(args.results_root)
    variables = jobs[-1][1] if jobs else {}
    modules: list[ModuleResult] = []
    for job_dir, job_variables in jobs:
        runtimes = load_module_runtimes(job_dir)
        label = job_variables.get("BUILD") or job_variables.get("TEST") or job_dir.name
        for path in job_dir.glob("details-*.json"):
            result = module_result(
                path, runtimes.get(path.stem.removeprefix("details-"))
            )
            modules.append(replace(result, name=f"{label} / {result.name}"))
    modules.sort(key=lambda item: item.name)
    system, applications = load_application_metrics_from_jobs(jobs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        render_report(variables, modules, system, applications), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
