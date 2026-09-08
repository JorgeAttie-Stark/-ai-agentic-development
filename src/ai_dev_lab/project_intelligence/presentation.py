"""Camadas Visualização e Documentação (Milestone 5) — serialização, não análise.

A regra que define este módulo: **nenhuma conclusão nova nasce aqui.** As quatro
tools consomem o que as camadas anteriores produziram e reapresentam. Se uma
delas precisasse decidir algo sobre o projeto, o lugar dessa decisão seria a
camada de análise, não a de apresentação.

Duas consequências práticas:

- **`derived_from` é obrigatório** em todo retorno. Quem lê um diagrama ou um
  relatório precisa saber de qual tool o dado veio, senão o documento se torna
  uma afirmação sem procedência.
- **A confiança viaja com a claim.** Um `finding` `LOW` renderizado sem o rótulo
  vira fato no texto. No Mermaid isso é aresta tracejada; no Markdown é o nível
  escrito ao lado. Perder a confiança na renderização desfaria todo o trabalho
  de M2 a M4.

`scope_limitations` das fontes são propagadas em vez de resumidas: um relatório
que omite as limitações do que o alimentou é menos honesto que as tools que ele
consome.
"""
from __future__ import annotations

import re

from .errors import ToolError
from .exploration import _handle_list_files, _handle_project_info
from .inference import _handle_data_flow_analyzer
from .understanding import _handle_architecture_explainer, _handle_dependency_analyzer

MAX_DIAGRAM_NODES = 60

# Aresta sólida só para HIGH. Tracejada para o resto — a incerteza precisa ser
# visível no próprio desenho, não só numa legenda que ninguém lê.
EDGE_BY_CONFIDENCE = {"HIGH": "-->", "MEDIUM": "-.->", "LOW": "-.->"}

PRESENTATION_LIMITATIONS = (
    "esta tool NÃO produz análise: ela serializa o que outras tools "
    "produziram. `derived_from` diz quais",
    "as limitações das tools de origem continuam valendo e estão reproduzidas "
    "abaixo — um documento que as omite é menos honesto que as tools que ele "
    "consome",
)

DIAGRAM_LIMITATIONS = PRESENTATION_LIMITATIONS + (
    "aresta sólida representa confiança HIGH; tracejada representa MEDIUM ou "
    "LOW. Um diagrama todo tracejado é um diagrama de suposições",
    "o diagrama é truncado em um número fixo de nós: um grafo grande vira "
    "ilegível antes de virar caro",
)


def _sanitize(label):
    """Remove o que quebraria a sintaxe do Mermaid.

    Um nome com `[`, `"` ou `-->` produziria um diagrama sintaticamente inválido
    — que o cliente renderiza como erro, ou pior, como outro grafo.
    """
    return re.sub(r'[\[\]{}()"<>|]', "", label).replace("-->", "").strip() or "?"


def _node_id(index):
    return f"n{index}"


def _diagram_from_findings(findings, title):
    """Um nó por evidência, uma aresta por claim, com o traço da confiança."""
    lines = [f"flowchart TD", f'    root["{_sanitize(title)}"]']
    nodes = 0

    for index, finding in enumerate(findings[:MAX_DIAGRAM_NODES]):
        node = _node_id(index)
        label = _sanitize(finding["claim"])
        arrow = EDGE_BY_CONFIDENCE[finding["confidence"]]
        lines.append(f'    {node}["{label}"]')
        lines.append(f'    root {arrow}|{finding["confidence"]}| {node}')
        nodes += 1

    if not nodes:
        lines.append('    empty["nenhuma evidência disponível"]')
        lines.append("    root --> empty")

    return "\n".join(lines), nodes


DIAGRAM_SOURCES = {
    "architecture": (_handle_architecture_explainer, "architecture_explainer"),
    "dependencies": (_handle_dependency_analyzer, "dependency_analyzer"),
    "call_graph": (_handle_data_flow_analyzer, "data_flow_analyzer"),
    "security": (None, "security_analyzer"),
}


def _handle_generate_mermaid(project_root, arguments):
    """Serializa findings de uma tool de análise em Mermaid. Zero análise nova."""
    diagram = arguments.get("diagram")
    if not isinstance(diagram, str) or diagram not in DIAGRAM_SOURCES:
        raise ToolError(
            "diagram é obrigatório e deve ser um de: "
            + ", ".join(sorted(DIAGRAM_SOURCES))
        )

    handler, source_name = DIAGRAM_SOURCES[diagram]
    if handler is None:
        # `security` é resolvida por import tardio para não criar dependência
        # de `presentation` sobre `analysis` no topo do módulo.
        from .analysis import _handle_security_analyzer

        handler = _handle_security_analyzer

    source = handler(project_root, {})
    mermaid, nodes = _diagram_from_findings(source["findings"], diagram)

    return {
        "mermaid": mermaid,
        "nodes": nodes,
        "diagram": diagram,
        "derived_from": [source_name],
        "truncated": len(source["findings"]) > MAX_DIAGRAM_NODES,
        # Limitações da fonte viajam junto: o diagrama não é mais confiável que
        # o dado que o alimentou.
        "scope_limitations": list(DIAGRAM_LIMITATIONS) + list(source["scope_limitations"]),
    }


MERMAID_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "mermaid": {"type": "string"},
        "nodes": {"type": "integer"},
        "diagram": {"type": "string"},
        "derived_from": {"type": "array", "items": {"type": "string"}},
        "truncated": {"type": "boolean"},
        "scope_limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["mermaid", "nodes", "diagram", "derived_from", "truncated", "scope_limitations"],
    "additionalProperties": False,
}

MERMAID_INPUT_SCHEMA = {
    "type": "object",
    "properties": {"diagram": {"type": "string", "enum": sorted(DIAGRAM_SOURCES)}},
    "required": ["diagram"],
    "additionalProperties": False,
}


def _render_findings_section(title, source):
    """Seção de Markdown com a confiança ao lado de CADA claim.

    Sem o rótulo, uma claim `LOW` lida como fato — e é aí que o trabalho de
    amarrar confiança a método se perderia na renderização.
    """
    lines = [f"### {title}", ""]

    if not source["findings"]:
        lines += ["Nenhuma evidência disponível para esta seção.", ""]
    else:
        lines += ["| Confiança | Método | Conclusão | Evidência |", "|---|---|---|---|"]
        for finding in source["findings"][:40]:
            evidence = finding["evidence"][0]
            where = evidence["file"]
            if evidence["line"]:
                where = f"{where}:{evidence['line']}"
            lines.append(
                f"| `{finding['confidence']}` | `{finding['method']}` | "
                f"{finding['claim']} | `{where}` |"
            )
        lines.append("")

    lines += ["**Limitações desta seção:**", ""]
    lines += [f"- {limitation}" for limitation in source["scope_limitations"]]
    lines.append("")
    return lines


def _handle_generate_project_report(project_root, arguments):
    """Relatório completo. Consome, formata, propaga limitações. Não conclui."""
    info = _handle_project_info(project_root, {})
    listing = _handle_list_files(project_root, {})
    architecture = _handle_architecture_explainer(project_root, {})
    dependencies = _handle_dependency_analyzer(project_root, {})

    lines = [
        "# Relatório do projeto",
        "",
        "> Documento gerado por serialização de tools de análise. Nenhuma "
        "conclusão nasce aqui: cada seção nomeia sua fonte, e cada afirmação "
        "carrega a confiança e o método que a produziram.",
        "",
        "## Inventário",
        "",
        f"- arquivos: **{info['total_files']}**",
        f"- linhas: **{info['total_lines']}**",
        f"- manifestos na raiz: {', '.join(info['manifests_present']) or 'nenhum'}",
        f"- arquivos ilegíveis pulados: {info['unreadable_entries_skipped']}",
        f"- varredura truncada: {'sim' if info['scan_truncated'] else 'não'}",
        "",
        "*Fonte: `project_info` e `list_files` — retrieval pura, sem inferência.*",
        "",
        "## Conclusões inferidas",
        "",
    ]
    lines += _render_findings_section("Arquitetura", architecture)
    lines += _render_findings_section("Dependências", dependencies)
    lines += ["## Limitações gerais", ""]
    lines += [f"- {limitation}" for limitation in PRESENTATION_LIMITATIONS]

    return {
        "markdown": "\n".join(lines),
        "derived_from": [
            "project_info",
            "list_files",
            "architecture_explainer",
            "dependency_analyzer",
        ],
        "scope_limitations": list(PRESENTATION_LIMITATIONS),
    }


def _handle_generate_architecture_documentation(project_root, arguments):
    """Documento de arquitetura. Declara ausência quando não há evidência."""
    architecture = _handle_architecture_explainer(project_root, {})
    dependencies = _handle_dependency_analyzer(project_root, {})

    lines = [
        "# Arquitetura observada",
        "",
        "> Este documento descreve **o que foi observado**, com a confiança de "
        "cada observação. Onde não há evidência, ele declara ausência em vez de "
        "preencher com suposição.",
        "",
    ]
    lines += _render_findings_section("Padrões de estrutura", architecture)
    lines += _render_findings_section("Dependências declaradas", dependencies)

    return {
        "markdown": "\n".join(lines),
        "derived_from": ["architecture_explainer", "dependency_analyzer"],
        "scope_limitations": list(PRESENTATION_LIMITATIONS),
    }


def _handle_generate_project_summary(project_root, arguments):
    """Resumo curto. Mesmas fontes, menos texto — nenhuma síntese nova."""
    info = _handle_project_info(project_root, {})
    architecture = _handle_architecture_explainer(project_root, {})

    confidences = {}
    for finding in architecture["findings"]:
        confidences[finding["confidence"]] = confidences.get(finding["confidence"], 0) + 1
    breakdown = ", ".join(f"{level}: {count}" for level, count in sorted(confidences.items()))

    lines = [
        "# Resumo do projeto",
        "",
        f"- **{info['total_files']}** arquivos, **{info['total_lines']}** linhas",
        f"- manifestos: {', '.join(info['manifests_present']) or 'nenhum'}",
        f"- conclusões de arquitetura: {breakdown or 'nenhuma evidência'}",
        "",
        "*Fontes: `project_info`, `architecture_explainer`. Nenhuma conclusão "
        "nova foi produzida na geração deste resumo.*",
    ]

    return {
        "markdown": "\n".join(lines),
        "derived_from": ["project_info", "architecture_explainer"],
        "scope_limitations": list(PRESENTATION_LIMITATIONS),
    }


DOCUMENT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "markdown": {"type": "string"},
        "derived_from": {"type": "array", "items": {"type": "string"}},
        "scope_limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["markdown", "derived_from", "scope_limitations"],
    "additionalProperties": False,
}
