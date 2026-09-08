"""Camada Análise (Milestone 4) — onde a tentação de exagerar é maior.

As três tools daqui têm nomes que prometem juízo: *security*, *improvement*,
*test*. O plano macro fixou o limite de cada uma antes de existir código, e é
esse limite que separa a tool de um gerador de alarme:

- **`security_analyzer`** faz detecção de **padrão**, não de vulnerabilidade.
  Confirmar exige taint analysis — saber se entrada não sanitizada alcança um
  sink —, que é análise de fluxo de dados real, a mesma coisa que o Milestone 3
  declarou inviável em stdlib. Um padrão suspeito é motivo para um humano olhar,
  não um veredito. Por isso nenhum finding aqui chega a `HIGH`.

- **`improvement_analyzer`** reporta **métrica com o valor medido**, nunca
  juízo. "Este arquivo tem 400 linhas" é fato; "este arquivo é ruim" é opinião
  sobre a qual a tool não tem base. E os thresholds vão no retorno: threshold
  escondido faz a métrica parecer objetiva quando a linha de corte é arbitrária.

- **`test_analyzer`** é **estático**. Nunca executa a suíte do projeto-alvo —
  executar código arbitrário de um repositório que a tool acabou de apontar
  seria a pior decisão de segurança possível num servidor que roda na máquina
  do usuário. Convenção de nome é `name-pattern`/`MEDIUM`: um arquivo chamado
  `test_x.py` sugere teste, não prova que testa algo.
"""
from __future__ import annotations

import re
from pathlib import Path

from .errors import ToolError
from .findings import findings_output_schema, make_evidence, make_finding
from .scanning import MAX_FINDINGS, iter_project_files, read_text, validated

# Cada padrão é uma pista, não um veredito. O rótulo descreve o que foi VISTO,
# não o que foi concluído — `eval` com entrada de fora é perigoso, `eval` de uma
# constante não é, e a regex não distingue os dois.
SECURITY_PATTERNS = (
    ("execução dinâmica de código", re.compile(r"\b(?:eval|exec)\s*\(")),
    ("execução de comando de sistema", re.compile(
        r"\b(?:os\.system|os\.popen|subprocess\.\w+)\s*\(")),
    ("shell habilitado em subprocess", re.compile(r"shell\s*=\s*True")),
    ("desserialização de dados não confiáveis", re.compile(r"\b(?:pickle|marshal)\.loads?\s*\(")),
    ("possível credencial literal no código", re.compile(
        r"(?:^|[^\w.])[\w.]*(?:password|passwd|secret|api_?key|token|private_key)"
        r"\s*[=:]\s*['\"]?[^\s'\"]{6,}",
        re.IGNORECASE)),
    # Exige vizinhança de SQL de verdade. Sem isso, `def update(self, d):
    # return self.total + 1` casava — e a claim afirmava "consulta SQL" onde
    # não havia SQL nenhum. O hedge "padrão de" cobre incerteza sobre risco;
    # não cobre nomear um construto que a regex não observou.
    ("concatenação em consulta SQL", re.compile(
        r"(?:SELECT|INSERT\s+INTO|UPDATE|DELETE)\b[^\n]*?"
        r"\b(?:FROM|WHERE|INTO|SET|VALUES)\b[^\n]*?"
        r"(?:\+|%s|%\(|\.format\(|\{)", re.IGNORECASE)),
    ("verificação de certificado desabilitada", re.compile(r"verify\s*=\s*False")),
)

SECURITY_LIMITATIONS = (
    "esta tool NÃO confirma vulnerabilidade — ela detecta PADRÃO. Confirmar "
    "exigiria taint analysis (saber se entrada não sanitizada alcança o sink), "
    "que é análise de fluxo de dados real e está fora do que a stdlib permite",
    "nenhum finding chega a HIGH por construção: padrão suspeito é motivo para "
    "um humano olhar, não veredito",
    "heurística de texto: não distingue código de comentário, de string "
    "literal nem de teste. Um `eval` citado num comentário é reportado, e a "
    "causa está declarada aqui em vez de filtrada silenciosamente — filtrar "
    "daria a falsa impressão de que a tool entende contexto",
    "ausência de finding NÃO significa código seguro: a lista de padrões é "
    "fixa e cobre um punhado de casos conhecidos",
)

LONG_FILE_LINES = 400
LONG_LINE_CHARS = 120
MARKER_PATTERN = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")

IMPROVEMENT_LIMITATIONS = (
    "esta tool reporta MÉTRICA com o valor medido, nunca juízo de qualidade. "
    "Não existe base para afirmar que um arquivo longo é ruim — arquivo longo "
    "é um fato, e o que fazer com ele é decisão de quem conhece o domínio",
    "os thresholds vão no retorno em `thresholds`: linha de corte escondida "
    "faz a métrica parecer objetiva quando ela é arbitrária",
    "métrica estrutural apenas — nada aqui mede corretude, desempenho real "
    "nem adequação de design",
)

# Convenções de nome de arquivo de teste, por ecossistema. Casar aqui é
# `name-pattern`: sugere teste, não prova que o arquivo testa algo.
TEST_FILE_PATTERNS = (
    re.compile(r"^test_.*\.py$"),
    re.compile(r".*_test\.(?:py|go)$"),
    re.compile(r".*\.(?:spec|test)\.(?:js|jsx|ts|tsx)$"),
    re.compile(r"^.*Test\.java$"),
    re.compile(r"^.*_spec\.rb$"),
)

SOURCE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".rb", ".php", ".cs", ".rs",
}

TEST_LIMITATIONS = (
    "análise ESTÁTICA: a suíte do projeto-alvo nunca é executada. Executar "
    "código arbitrário de um repositório apontado pelo cliente seria a pior "
    "decisão de segurança possível num servidor que roda na máquina do usuário",
    "a razão teste/fonte é APROXIMADA: conta arquivos, não cobertura. Um "
    "arquivo de teste vazio conta igual a um com cem casos",
    "identificação por convenção de nome, por ecossistema conhecido: "
    "confiança MEDIUM. Um arquivo chamado `test_x.py` sugere teste; não prova "
    "que ele testa algo",
    "convenção fora da lista (nome customizado, diretório próprio sem prefixo) "
    "é invisível — `test_files_found: 0` pode significar convenção diferente, "
    "não ausência de teste",
)


# O valor à direita de um `=` num padrão de credencial é o segredo. Devolvê-lo
# no snippet o manda para o contexto do modelo e para qualquer log do cliente.
# `file:line` já basta para o humano conferir — existe `read_file`.
_SECRET_VALUE = re.compile(r"([=:]\s*['\"]?)[^\s'\"]{6,}")


def _redact(label, line):
    stripped = line.strip()
    if "credencial" in label:
        return _SECRET_VALUE.sub(r"\1***", stripped)
    return stripped


def _line_findings(project_root, patterns, claim_for, method):
    """Varre linha a linha aplicando pares (rótulo, regex).

    Compartilhado por `security` e pelos marcadores de `improvement`: os dois
    fazem a mesma coisa — achar linha que casa padrão e citá-la — e diferem só
    na redação da claim.
    """
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

            produced = []
            for line_number, line in enumerate(text.splitlines(), start=1):
                for label, matcher in patterns:
                    if matcher.search(line):
                        produced.append(
                            make_finding(
                                claim_for(label, relative_file, line_number),
                                method,
                                [make_evidence(relative_file, line_number, _redact(label, line))],
                            )
                        )

            if len(findings) + len(produced) > MAX_FINDINGS:
                findings_truncated = True
                files_skipped_by_cap.append(relative_file)
                continue

            findings.extend(produced)
            files_scanned += 1
    except OSError as error:
        raise ToolError("não foi possível varrer o diretório do projeto") from error

    return findings, files_scanned, files_skipped_by_cap, findings_truncated, counters


def _handle_security_analyzer(project_root, arguments):
    """Detecção de padrão. Ver o docstring do módulo: não confirma vulnerabilidade."""
    findings, files_scanned, skipped, truncated, counters = _line_findings(
        project_root,
        SECURITY_PATTERNS,
        # "padrão de X" e nunca "vulnerabilidade de X": a claim descreve o que
        # foi visto, não o que foi concluído.
        lambda label, file, line: f"padrão de {label} em `{file}` linha {line}",
        "regex-heuristic",
    )

    return {
        "findings": validated(findings),
        "files_scanned": files_scanned,
        "files_skipped_by_cap": skipped,
        "findings_truncated": truncated,
        "unreadable_entries_skipped": counters["unreadable_entries_skipped"],
        "scope_limitations": list(SECURITY_LIMITATIONS),
    }


SECURITY_OUTPUT_SCHEMA = findings_output_schema(
    {
        "files_scanned": {"type": "integer"},
        "files_skipped_by_cap": {"type": "array", "items": {"type": "string"}},
        "findings_truncated": {"type": "boolean"},
        "unreadable_entries_skipped": {"type": "integer"},
    }
)


def _handle_improvement_analyzer(project_root, arguments):
    """Métrica estrutural com o valor medido. Nunca juízo."""
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

            lines = text.splitlines()
            produced = []

            if len(lines) > LONG_FILE_LINES:
                produced.append(
                    make_finding(
                        f"`{relative_file}` tem {len(lines)} linhas, acima do "
                        f"limiar declarado de {LONG_FILE_LINES}",
                        "line-count",
                        [make_evidence(relative_file, 1, lines[0].strip() if lines else None)],
                    )
                )

            for line_number, line in enumerate(lines, start=1):
                marker = MARKER_PATTERN.search(line)
                if marker:
                    produced.append(
                        make_finding(
                            f"marcador `{marker.group(1)}` em `{relative_file}` "
                            f"linha {line_number}",
                            "regex-heuristic",
                            [make_evidence(relative_file, line_number, line.strip())],
                        )
                    )
                if len(line) > LONG_LINE_CHARS:
                    produced.append(
                        make_finding(
                            f"`{relative_file}` linha {line_number} tem "
                            f"{len(line)} caracteres, acima do limiar "
                            f"declarado de {LONG_LINE_CHARS}",
                            "line-count",
                            [make_evidence(relative_file, line_number, line.strip())],
                        )
                    )

            if len(findings) + len(produced) > MAX_FINDINGS:
                findings_truncated = True
                files_skipped_by_cap.append(relative_file)
                continue

            findings.extend(produced)
            files_scanned += 1
    except OSError as error:
        raise ToolError("não foi possível varrer o diretório do projeto") from error

    return {
        "findings": validated(findings),
        "files_scanned": files_scanned,
        "files_skipped_by_cap": files_skipped_by_cap,
        "findings_truncated": findings_truncated,
        "unreadable_entries_skipped": counters["unreadable_entries_skipped"],
        # Threshold no retorno: escondido, ele faz a métrica parecer objetiva.
        "thresholds": {
            "long_file_lines": LONG_FILE_LINES,
            "long_line_chars": LONG_LINE_CHARS,
        },
        "scope_limitations": list(IMPROVEMENT_LIMITATIONS),
    }


IMPROVEMENT_OUTPUT_SCHEMA = findings_output_schema(
    {
        "files_scanned": {"type": "integer"},
        "files_skipped_by_cap": {"type": "array", "items": {"type": "string"}},
        "findings_truncated": {"type": "boolean"},
        "unreadable_entries_skipped": {"type": "integer"},
        "thresholds": {"type": "object", "additionalProperties": {"type": "integer"}},
    }
)


def _is_test_file(name):
    return any(matcher.match(name) for matcher in TEST_FILE_PATTERNS)


def _handle_test_analyzer(project_root, arguments):
    """Presença e estrutura de testes, estaticamente. Nunca executa nada."""
    counters = {"unreadable_entries_skipped": 0}
    test_files = []
    source_files = 0

    try:
        for file_path, relative_file in iter_project_files(project_root, counters):
            name = Path(relative_file).name
            if _is_test_file(name):
                test_files.append(relative_file)
            elif Path(relative_file).suffix in SOURCE_EXTENSIONS:
                source_files += 1
    except OSError as error:
        raise ToolError("não foi possível varrer o diretório do projeto") from error

    findings = []
    for relative_file in test_files[:MAX_FINDINGS]:
        findings.append(
            make_finding(
                f"`{relative_file}` segue convenção de nome de arquivo de teste",
                "name-pattern",
                [make_evidence(relative_file)],
            )
        )

    ratio = round(len(test_files) / source_files, 2) if source_files else None

    return {
        "findings": validated(findings),
        "test_files_found": len(test_files),
        "source_files_found": source_files,
        "test_to_source_ratio": ratio,
        "findings_truncated": len(test_files) > MAX_FINDINGS,
        "unreadable_entries_skipped": counters["unreadable_entries_skipped"],
        "scope_limitations": list(TEST_LIMITATIONS),
    }


TEST_ANALYZER_OUTPUT_SCHEMA = findings_output_schema(
    {
        "test_files_found": {"type": "integer"},
        "source_files_found": {"type": "integer"},
        "test_to_source_ratio": {"type": ["number", "null"]},
        "findings_truncated": {"type": "boolean"},
        "unreadable_entries_skipped": {"type": "integer"},
    }
)
