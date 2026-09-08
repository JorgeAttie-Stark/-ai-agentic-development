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
import re
from pathlib import Path

from .errors import ToolError
from .findings import findings_output_schema, make_evidence, make_finding
from .scanning import MAX_FINDINGS, iter_project_files, read_text, validated

CALL_GRAPH_LIMITATIONS = (
    "esta tool NÃO é análise de fluxo de dados — fluxo real exige CFG e "
    "análise semântica, inviável em stdlib puro e agnóstico de linguagem. "
    "O que ela devolve é um grafo de CHAMADAS",
    "somente arquivos Python são analisados: é a única linguagem com parser "
    "real na stdlib. Arquivo de outra linguagem não é analisado nem estimado",
    "uma aresta prova que existe uma chamada com aquele NOME naquela linha; "
    "não prova a qual função ela resolve — o nome pode estar sombreado, "
    "importado, ser método de qualquer objeto, ou reatribuído em runtime",
    "a origem da aresta é o escopo LEXICAL onde a chamada aparece. Chamada dentro de lambda ou comprehension sai com origem anônima, porque quem a invoca é outro alguém — talvez nunca",
    "chamada dinâmica (`getattr`, `eval`, despacho por dict) é invisível",
    "quando o teto corta, os arquivos são visitados em ordem alfabética de caminho — a seleção é determinística e reprodutível, mas não prioriza relevância: num repositório grande, `tests/` pode consumir o orçamento antes de `src/`",
    "o teto de findings pula o ARQUIVO inteiro e o nomeia em `files_skipped_by_cap`: nunca devolve visão parcial de um arquivo, e nunca estoura o teto. Um repositório grande recebe um subconjunto de arquivos, explicitamente listado",
)


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


def _call_line(node):
    """Linha do NOME chamado, não do início da expressão.

    `ast.Call.lineno` aponta o começo da expressão de chamada. Em cadeia
    quebrada em linhas — `client\n.session\n.post(url)` — isso faz a evidência
    apontar para uma linha que não contém o nome que a claim afirma, e quem
    fosse conferir não confirmaria.
    """
    return getattr(node.func, "end_lineno", None) or node.lineno


# Escopos que Python cria e que NÃO são a função contenedora. Uma chamada
# dentro de um deles não é feita pela função que o contém lexicalmente: a
# lambda é invocada por outro alguém, talvez nunca; a comprehension tem escopo
# próprio. Atribuir a chamada à função de fora produziria aresta falsa.
_NESTED_SCOPES = (ast.Lambda, ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp)


def _walk_calls(node, scope, out):
    """Coleta chamadas carregando o escopo pela ÁRVORE, não por faixa de linhas.

    Faixa de linhas não é escopo, e a diferença não é acadêmica:

    - `def charge(gateway=build_live_gateway())` — o default é avaliado uma vez,
      na definição, no escopo de FORA. `charge` nunca chama `build_live_gateway`.
      Por faixa de linhas a chamada caía dentro de `charge`, porque `lineno` do
      `def` abre a faixa.
    - `button.on_click(lambda: transfer_funds(x))` — quem chama `transfer_funds`
      é a lambda. Por faixa de linhas a aresta saía como se a função
      registradora chamasse, com confiança HIGH.

    O despacho é sobre o próprio nó, não sobre os filhos: `args` e
    `decorator_list` precisam ser visitados com o escopo de fora, e o `body`
    com o escopo de dentro — o que só é possível decidindo ao entrar no nó.
    """
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        # Assinatura e decoradores rodam no escopo de fora, não no da função.
        for outer in node.decorator_list:
            _walk_calls(outer, scope, out)
        if not isinstance(node, ast.ClassDef):
            _walk_calls(node.args, scope, out)

        # Qualifica: `Alpha.process` e `Beta.process` são nós distintos do
        # grafo, não um nó fundido chamado `process`.
        inner = f"{scope}.{node.name}" if scope else node.name
        for stmt in node.body:
            _walk_calls(stmt, inner, out)
        return

    if isinstance(node, _NESTED_SCOPES):
        # Quem invoca a lambda ou consome o gerador é outro alguém, talvez
        # nunca. Atribuir à função contenedora produziria aresta falsa.
        for child in ast.iter_child_nodes(node):
            _walk_calls(child, None, out)
        return

    if isinstance(node, ast.Call):
        out.append((node, scope))

    for child in ast.iter_child_nodes(node):
        _walk_calls(child, scope, out)


def _call_edges(text, relative_file):
    tree = ast.parse(text)
    lines = text.splitlines()
    collected = []
    _walk_calls(tree, None, collected)

    findings = []
    for node, scope in collected:
        target = _called_name(node)
        if target is None:
            continue

        line = _call_line(node)
        origin = f"`{scope}`" if scope else "um escopo anônimo ou o corpo do módulo"
        snippet = lines[line - 1].strip() if line <= len(lines) else None

        findings.append(
            make_finding(
                # Para no site da chamada: "chama `x`", nunca "chama a função
                # `x` definida em ...". O `ast` não prova a resolução.
                f"em `{relative_file}`, {origin} chama `{target}`",
                "ast-parse",
                [make_evidence(relative_file, line, snippet)],
            )
        )

    return findings


def _handle_data_flow_analyzer(project_root, arguments):
    """Grafo de chamadas de Python. Ver o docstring do módulo: não é fluxo de dados."""
    counters = {"unreadable_entries_skipped": 0}
    findings = []
    python_files_analyzed = 0
    files_unparseable = 0
    # Lista, não contagem: o consumidor precisa saber QUAIS arquivos ficaram
    # fora, senão não tem como perceber que `src/` inteiro foi omitido.
    files_skipped_by_cap = []
    findings_truncated = False

    try:
        for file_path, relative_file in iter_project_files(project_root, counters):
            if Path(relative_file).suffix != ".py":
                continue

            text = read_text(file_path)
            if text is None:
                counters["unreadable_entries_skipped"] += 1
                continue

            try:
                produced = _call_edges(text, relative_file)
            except (SyntaxError, ValueError, RecursionError, MemoryError):
                files_unparseable += 1
                continue

            # O teto é um teto, não um piso mole. A alternativa honesta ao
            # corte no meio do arquivo não é deixar estourar — é pular o
            # arquivo inteiro e nomeá-lo, que é o que já se fazia para os
            # arquivos depois do limite.
            if len(findings) + len(produced) > MAX_FINDINGS:
                findings_truncated = True
                files_skipped_by_cap.append(relative_file)
                continue

            findings.extend(produced)
            python_files_analyzed += 1
    except OSError as error:
        raise ToolError("não foi possível varrer o diretório do projeto") from error

    return {
        "findings": validated(findings),
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
        "files_skipped_by_cap": {"type": "array", "items": {"type": "string"}},
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
    "o vocabulário de domínio é uma lista fixa em português e inglês: identificador em outro idioma natural (alemão, japonês) é invisível, e nesse caso `findings` vazio NÃO significa ausência de regra",
    "heurística de texto: não distingue código de comentário nem de string literal — é a causa dominante de falso positivo na prática",
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
    files_skipped_by_cap = []
    findings_truncated = False

    try:
        for file_path, relative_file in iter_project_files(project_root, counters):
            text = read_text(file_path)
            if text is None:
                counters["unreadable_entries_skipped"] += 1
                continue

            candidates = list(_rule_candidate_lines(text))
            if len(findings) + len(candidates) > MAX_FINDINGS:
                findings_truncated = True
                files_skipped_by_cap.append(relative_file)
                continue

            files_scanned += 1
            for line_number, snippet in candidates:
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

    return {
        "findings": validated(findings),
        "files_scanned": files_scanned,
        "files_skipped_by_cap": files_skipped_by_cap,
        "findings_truncated": findings_truncated,
        "unreadable_entries_skipped": counters["unreadable_entries_skipped"],
        "scope_limitations": list(BUSINESS_RULES_LIMITATIONS),
    }


BUSINESS_RULES_OUTPUT_SCHEMA = findings_output_schema(
    {
        "files_scanned": {"type": "integer"},
        "files_skipped_by_cap": {"type": "array", "items": {"type": "string"}},
        "findings_truncated": {"type": "boolean"},
        "unreadable_entries_skipped": {"type": "integer"},
    }
)
