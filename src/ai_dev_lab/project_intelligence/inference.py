"""Camada de Inferência (Milestone 3) — a fronteira epistemológica do projeto.

O plano macro marcou este milestone como *"fronteira epistemológica mais
arriscada do projeto"* e **rescopou as duas tools antes de qualquer código
existir**. As duas restrições abaixo não são detalhes de implementação: são o
que separa a tool de um gerador de afirmações plausíveis.

**`data_flow_analyzer` não faz análise de fluxo de dados.** Fluxo de dados real
exige CFG e análise semântica — inviável em stdlib puro e agnóstico de
linguagem. O que é honestamente factível é um *call graph* de Python via `ast`,
best-effort. O nome da tool vem do roadmap; o retorno diz o que ela é.

E há uma distinção fina que governa a redação das claims: o `ast` prova que
**existe uma chamada com o nome X na linha N**. Ele não prova **a qual função
essa chamada resolve** — o nome pode estar sombreado, importado, ser método de
qualquer objeto, ou ser reatribuído em runtime. Por isso a claim para no site
da chamada e nunca afirma resolução.

**`business_rules_analyzer` não descreve a regra.** Extrair a regra é síntese
semântica, exatamente o que o requisito proíbe. A tool localiza *candidatos* e
devolve o trecho literal; a interpretação cabe a quem lê.

Isso é imposto por **ausência de campo**, não por instrução: no retorno não
existe lugar onde uma descrição de regra caberia. `claim` aponta o local,
`snippet` é a linha literal do arquivo. Não há `interpretation`, não há
`description`, não há `rule`. Se alguém quiser "melhorar" a tool descrevendo a
regra, precisa primeiro inventar um campo — e é aí que a revisão pega.
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path

from .errors import ToolError
from .findings import findings_output_schema, make_evidence, make_finding, validate_finding
from .understanding import _iter_project_files, _read_text

MAX_FINDINGS = 300

CALL_GRAPH_LIMITATIONS = (
    "esta tool NÃO é análise de fluxo de dados — fluxo real exige CFG e "
    "análise semântica, inviável em stdlib puro e agnóstico de linguagem. "
    "O que ela devolve é um grafo de CHAMADAS",
    "somente arquivos Python são analisados: é a única linguagem com parser "
    "real na stdlib. Arquivo de outra linguagem não é analisado nem estimado",
    "uma aresta prova que existe uma chamada com aquele NOME naquela linha; "
    "não prova a qual função ela resolve — o nome pode estar sombreado, "
    "importado, ser método de qualquer objeto, ou reatribuído em runtime",
    "chamada dinâmica (`getattr`, `eval`, despacho por dict) é invisível",
    "o teto de findings corta em fronteira de ARQUIVO, então um único arquivo grande é devolvido inteiro e o teto vira piso mole — corte no meio produziria visão parcial de arquivo sem avisar, que é pior",
)


def _enclosing_scope_name(tree):
    """Mapeia cada linha ao nome da função que a contém, quando há uma.

    Sem isso a aresta perderia a origem: `helper()` na linha 12 é chamado *de
    algum lugar*, e o lugar é o que torna a aresta útil.
    """
    scope_by_line = {}

    def _walk(node, current):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = child.name
                for line in range(child.lineno, getattr(child, "end_lineno", child.lineno) + 1):
                    scope_by_line[line] = name
                _walk(child, name)
            else:
                _walk(child, current)

    _walk(tree, None)
    return scope_by_line


def _called_name(node):
    """Nome textual do alvo da chamada, ou `None` se não for nomeável.

    `f()` devolve `f`; `obj.method()` devolve `method`. Uma chamada sobre
    expressão (`get_handler()()`) não tem nome textual e é descartada em vez de
    receber um rótulo inventado.
    """
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _call_edges(text, relative_file):
    tree = ast.parse(text)
    scope_by_line = _enclosing_scope_name(tree)
    lines = text.splitlines()
    findings = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        target = _called_name(node)
        if target is None:
            continue

        caller = scope_by_line.get(node.lineno)
        origin = f"`{caller}`" if caller else "o corpo do módulo"
        snippet = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else None

        findings.append(
            make_finding(
                # Para no site da chamada: "chama `x`", nunca "chama a função
                # `x` definida em ...". O `ast` não prova a resolução.
                f"em `{relative_file}`, {origin} chama `{target}`",
                "ast-parse",
                [make_evidence(relative_file, node.lineno, snippet)],
            )
        )

    return findings


def _handle_data_flow_analyzer(project_root, arguments):
    """Grafo de chamadas de Python. Ver o docstring do módulo: não é fluxo de dados."""
    counters = {"unreadable_entries_skipped": 0}
    findings = []
    python_files_analyzed = 0
    files_unparseable = 0
    files_skipped_by_cap = 0
    findings_truncated = False

    try:
        for file_path, relative_file in _iter_project_files(project_root, counters):
            if Path(relative_file).suffix != ".py":
                continue

            if len(findings) >= MAX_FINDINGS:
                findings_truncated = True
                files_skipped_by_cap += 1
                continue

            text = _read_text(file_path)
            if text is None:
                counters["unreadable_entries_skipped"] += 1
                continue

            try:
                findings.extend(_call_edges(text, relative_file))
            except (SyntaxError, ValueError, RecursionError, MemoryError):
                files_unparseable += 1
                continue

            python_files_analyzed += 1
    except OSError as error:
        raise ToolError("não foi possível varrer o diretório do projeto") from error

    for finding in findings:
        validate_finding(finding)

    return {
        "findings": findings,
        "python_files_analyzed": python_files_analyzed,
        "files_unparseable": files_unparseable,
        "files_skipped_by_cap": files_skipped_by_cap,
        "findings_truncated": findings_truncated,
        "unreadable_entries_skipped": counters["unreadable_entries_skipped"],
        "scope_limitations": list(CALL_GRAPH_LIMITATIONS),
    }


DATA_FLOW_OUTPUT_SCHEMA = findings_output_schema(
    {
        "python_files_analyzed": {"type": "integer"},
        "files_unparseable": {"type": "integer"},
        "files_skipped_by_cap": {"type": "integer"},
        "findings_truncated": {"type": "boolean"},
        "unreadable_entries_skipped": {"type": "integer"},
    }
)


BUSINESS_RULES_LIMITATIONS = (
    "esta tool NÃO descreve a regra de negócio — ela localiza candidatos e "
    "devolve o trecho literal. A interpretação cabe a quem lê o snippet",
    "não existe campo de descrição no retorno: apontar o local é o produto, "
    "não um passo intermediário para uma síntese que a tool não faz",
    "heurística de texto sobre condicional e validação próximas de vocabulário "
    "de domínio: confiança LOW e falso positivo esperado, não anomalia",
    "regra implícita, distribuída por vários arquivos ou expressa sem "
    "condicional é invisível — ausência de candidato não significa ausência "
    "de regra",
)

# Sinal de fronteira de decisão: onde o código rejeita, valida ou ramifica.
DECISION_SIGNALS = re.compile(
    r"\b(?:if|elif|unless|raise|throw|assert|reject|return\s+False)\b"
)

# Vocabulário que sugere domínio de negócio em vez de mecânica de programa.
# Casar aqui não é evidência de regra — é evidência de que vale um humano olhar.
DOMAIN_VOCABULARY = re.compile(
    r"\b(?:valor|preco|preço|total|saldo|limite|taxa|desconto|juros|imposto|"
    r"amount|price|balance|limit|fee|discount|tax|quota|credit|debit|"
    r"permissao|permissão|autoriza|permite|elegivel|elegível|valida|"
    r"permission|authoriz|allow|eligib|valid|approve|deny|"
    r"prazo|vencimento|expira|idade|status|nivel|nível|plano|"
    r"deadline|expir|age|tier|plan|quantidade|estoque|stock)\w*",
    re.IGNORECASE,
)


def _rule_candidate_lines(text):
    """Linhas que têm sinal de decisão E vocabulário de domínio.

    Exigir os dois juntos é o que separa `if valor > limite` de `if not path`.
    Um sinal só produziria ruído de mecânica de programa.
    """
    for line_number, line in enumerate(text.splitlines(), start=1):
        if DECISION_SIGNALS.search(line) and DOMAIN_VOCABULARY.search(line):
            yield line_number, line.strip()


def _handle_business_rules_analyzer(project_root, arguments):
    """Localiza candidatos a regra de negócio. Ver o docstring: não descreve."""
    counters = {"unreadable_entries_skipped": 0}
    findings = []
    files_scanned = 0
    files_skipped_by_cap = 0
    findings_truncated = False

    try:
        for file_path, relative_file in _iter_project_files(project_root, counters):
            if len(findings) >= MAX_FINDINGS:
                findings_truncated = True
                files_skipped_by_cap += 1
                continue

            text = _read_text(file_path)
            if text is None:
                counters["unreadable_entries_skipped"] += 1
                continue

            files_scanned += 1
            for line_number, snippet in _rule_candidate_lines(text):
                findings.append(
                    make_finding(
                        # A claim aponta. Ela não pode reproduzir o conteúdo da
                        # condição, porque reproduzir seria descrever a regra —
                        # e descrever é o que esta tool existe para não fazer.
                        f"`{relative_file}` linha {line_number} é candidato a "
                        f"conter regra de negócio",
                        "regex-heuristic",
                        [make_evidence(relative_file, line_number, snippet)],
                    )
                )
    except OSError as error:
        raise ToolError("não foi possível varrer o diretório do projeto") from error

    for finding in findings:
        validate_finding(finding)

    return {
        "findings": findings,
        "files_scanned": files_scanned,
        "files_skipped_by_cap": files_skipped_by_cap,
        "findings_truncated": findings_truncated,
        "unreadable_entries_skipped": counters["unreadable_entries_skipped"],
        "scope_limitations": list(BUSINESS_RULES_LIMITATIONS),
    }


BUSINESS_RULES_OUTPUT_SCHEMA = findings_output_schema(
    {
        "files_scanned": {"type": "integer"},
        "files_skipped_by_cap": {"type": "integer"},
        "findings_truncated": {"type": "boolean"},
        "unreadable_entries_skipped": {"type": "integer"},
    }
)
