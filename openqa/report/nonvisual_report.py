# SPDX-License-Identifier: GPL-2.0-or-later
"""Render nonvisual evidence separately from startup-only application metrics."""
import html
import json
from pathlib import Path

EXPECTED = {"kate-save-reopen", "konsole-execute", "dolphin-rename", "brave-live-region"}
LIMITS = ("Este resultado cobre quatro percursos de aplicativos instalados. Não certifica "
          "o desktop inteiro, a ativação nativa do leitor, SDDM, desbloqueio, diálogos de "
          "autorização, todo o instalador, todos os temas, áudio audível ou dispositivo braille.")


def load_nonvisual(root: Path) -> list[dict]:
    results = []
    for path in sorted(root.rglob("nonvisual-contracts.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("schema_version") != 1:
                raise ValueError("schema não reconhecido")
            cases = payload.get("cases")
            if not isinstance(cases, list) or any(not isinstance(c, dict) for c in cases):
                raise ValueError("lista de percursos inválida")
            names = [case.get("name") for case in cases]
            if len(names) != len(EXPECTED) or set(names) != EXPECTED:
                raise ValueError("evidência incompleta: faltam percursos obrigatórios")
            for case in cases:
                result = dict(case, source=str(path.relative_to(root)))
                if result.get("status") == "passed" and not (
                    result.get("functional") == "passed"
                    and result.get("accessibility") == "keyboard-path-passed"
                    and result.get("screen_reader") == "presenter-passed"
                ):
                    result.update(status="inconclusive", error="aprovação sem todas as evidências")
                if result.get("status") == "skipped" and result.get("skip_reason") != "not-installed":
                    result.update(status="inconclusive", error="exclusão sem ausência comprovada")
                results.append(result)
        except (OSError, ValueError, TypeError) as error:
            results.append({"name": str(path.relative_to(root)), "status": "inconclusive", "error": str(error)})
    return results


def render_nonvisual_html(results: list[dict]) -> str:
    columns = ("name", "functional", "accessibility", "screen_reader", "status", "error")
    rows = "".join("<tr>" + "".join("<td>" + html.escape(str(item.get(key, "não confirmado")))
                    + "</td>" for key in columns) + "</tr>" for item in results)
    return ("<section aria-labelledby='nonvisual-title'><h2 id='nonvisual-title'>Percursos não visuais</h2>"
            + ("<table><thead><tr><th>Percurso</th><th>Função</th><th>Teclado</th><th>Orca</th>"
               "<th>Resultado</th><th>Motivo</th></tr></thead><tbody>" + rows + "</tbody></table>"
               if results else "<p>Não há evidência de execução dos percursos profundos; eles são opcionais no smoke padrão.</p>")
            + "<p>" + LIMITS + "</p></section>")


def render_nonvisual_markdown(results: list[dict]) -> str:
    passed = sum(item.get("status") == "passed" for item in results)
    return ("\n### Percursos não visuais\n\n"
            + (f"{passed}/{len(results)} registros aprovados; resultados parciais não certificam acessibilidade.\n"
               if results else "Sem evidência de execução.\n") + "\n" + LIMITS + "\n")
