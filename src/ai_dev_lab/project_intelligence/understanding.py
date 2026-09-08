"""Camada Entendimento (Milestone 2): as primeiras tools que *afirmam* algo.

A diferença em relação à Camada Exploração não é de tamanho, é de natureza.
`list_files` relata o que existe; `architecture_explainer` conclui algo sobre o
que existe. Toda conclusão aqui passa por `findings.make_finding`, que amarra a
confiança ao método e recusa claim sem evidência.

A regra que governa este módulo: **onde não há evidência, a tool reporta
ausência, não um palpite.** Uma lista de findings vazia com uma limitação
declarada é uma resposta melhor que uma inferência fraca apresentada como
descoberta.
"""
from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path

from .errors import ToolError
from .exploration import (
    MAX_FILE_SIZE_FOR_LINE_COUNT,
    _load_gitignore_patterns,
    _matches_any_gitignore_pattern,
    _prune_gitignore_dirs,
    _walk_pruned,
)
from .findings import findings_output_schema, make_evidence, make_finding

MAX_TREE_DEPTH = 8
MAX_FINDINGS = 300

# Vocabulário arquitetural comum. Casar um nome aqui é evidência de *convenção*,
# nunca de estrutura real de dependência — por isso o método é `name-pattern`
# e a confiança fica capada em MEDIUM. Provar direção de dependência exigiria
# grafo de import real, que é outra tool.
ARCHITECTURE_VOCABULARY = {
    "handlers": "camada de tratamento de requisição",
    "controllers": "camada de tratamento de requisição",
    "routes": "definição de rotas",
    "views": "camada de apresentação",
    "services": "camada de serviço",
    "models": "camada de modelo de dados",
    "entities": "camada de modelo de dados",
    "repositories": "camada de acesso a dados",
    "gateways": "camada de acesso a recurso externo",
    "domain": "camada de domínio",
    "usecases": "camada de casos de uso",
    "middlewares": "camada de middleware",
    "utils": "utilitários compartilhados",
    "lib": "biblioteca interna",
    "tests": "suíte de testes",
    "migrations": "migrações de schema",
}

# Heurística de estrutura para linguagens sem parser na stdlib. Regex sobre
# texto não entende escopo, comentário nem string — falso positivo é esperado,
# e é por isso que o método é `regex-heuristic` e a confiança é LOW.
STRUCTURE_HEURISTICS = (
    ("função", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)")),
    ("função", re.compile(r"^\s*(?:public|private|protected)?\s*func\s+(\w+)")),
    ("classe", re.compile(r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)")),
    ("interface", re.compile(r"^\s*(?:export\s+)?interface\s+(\w+)")),
)

HEURISTIC_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".rb", ".php", ".cs"}


def _relative_posix(path, project_root):
    return Path(path).relative_to(project_root).as_posix()


def _iter_project_files(project_root, counters):
    """Arquivos regulares da raiz, com `.git` e `.gitignore` de topo aplicados.

    Reusa integralmente o mecanismo de poda da Camada Exploração — nenhuma
    lógica de `.gitignore` é reimplementada aqui.
    """
    patterns = _load_gitignore_patterns(project_root) or []

    for dirpath, dirnames, filenames in _walk_pruned(project_root, counters):
        if patterns:
            _prune_gitignore_dirs(dirnames, dirpath, project_root, patterns)

        for filename in filenames:
            relative_file = _relative_posix(Path(dirpath, filename), project_root)
            if patterns and _matches_any_gitignore_pattern(patterns, filename, relative_file):
                continue

            file_path = os.path.join(dirpath, filename)
            # `isfile` antes de qualquer `open()` — FIFO sem writer não bloqueia.
            if not os.path.isfile(file_path):
                counters["unreadable_entries_skipped"] += 1
                continue

            yield file_path, relative_file


def _read_text(file_path):
    """Texto do arquivo, ou `None` se binário ou grande demais para analisar."""
    try:
        if os.path.getsize(file_path) > MAX_FILE_SIZE_FOR_LINE_COUNT:
            return None
        with open(file_path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return None

    if b"\x00" in raw[:8192]:
        return None
    return raw.decode("utf-8", errors="ignore")


def _handle_project_map(project_root, arguments):
    """Árvore de diretórios com contagem de arquivos. Factual, sem findings.

    Não emite envelope de propósito: uma árvore é estrutura observada, do mesmo
    tipo que `list_files` devolve. Não há claim a sustentar.
    """
    counters = {"unreadable_entries_skipped": 0}
    nodes = {}
    tree_truncated = False

    try:
        for dirpath, dirnames, filenames in _walk_pruned(project_root, counters):
            relative_dir = _relative_posix(dirpath, project_root)
            depth = 0 if relative_dir == "." else len(Path(relative_dir).parts)
            if relative_dir == ".":
                relative_dir = ""

            if depth >= MAX_TREE_DEPTH:
                tree_truncated = True
                dirnames[:] = []

            nodes[relative_dir] = {
                "path": relative_dir,
                "file_count": len(filenames),
                "children": [],
            }
    except OSError as error:
        raise ToolError("não foi possível varrer o diretório do projeto") from error

    for path, node in sorted(nodes.items()):
        if not path:
            continue
        parent = Path(path).parent.as_posix()
        parent = "" if parent == "." else parent
        if parent in nodes:
            nodes[parent]["children"].append(node)

    return {
        "tree": nodes.get("", {"path": "", "file_count": 0, "children": []}),
        "total_directories": len(nodes),
        "tree_truncated": tree_truncated,
        "unreadable_entries_skipped": counters["unreadable_entries_skipped"],
    }


PROJECT_MAP_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "tree": {"type": "object"},
        "total_directories": {"type": "integer"},
        "tree_truncated": {"type": "boolean"},
        "unreadable_entries_skipped": {"type": "integer"},
    },
    "required": ["tree", "total_directories", "tree_truncated", "unreadable_entries_skipped"],
    "additionalProperties": False,
}


ARCHITECTURE_LIMITATIONS = (
    "conclui a partir de NOMES de diretório, não de grafo de import — nome de "
    "pasta sugere convenção, não prova direção de dependência",
    "confiança capada em MEDIUM: provar a arquitetura exigiria análise de "
    "import real, que esta tool não faz",
    "diretório fora do vocabulário conhecido não gera finding — ausência de "
    "finding significa ausência de evidência, não ausência de arquitetura",
)


def _handle_architecture_explainer(project_root, arguments):
    """Relata padrões de nome de diretório que sugerem camadas.

    Nunca conclui o estilo arquitetural como fato. Toda claim é redigida como
    sugestão, e a confiança é estruturalmente MEDIUM porque o método é
    `name-pattern` — não há caminho de código que produza HIGH aqui.
    """
    counters = {"unreadable_entries_skipped": 0}
    seen = {}

    try:
        for dirpath, dirnames, filenames in _walk_pruned(project_root, counters):
            for dirname in dirnames:
                role = ARCHITECTURE_VOCABULARY.get(dirname.lower())
                if not role or dirname.lower() in seen:
                    continue
                seen[dirname.lower()] = (
                    role,
                    _relative_posix(Path(dirpath, dirname), project_root),
                )
    except OSError as error:
        raise ToolError("não foi possível varrer o diretório do projeto") from error

    findings = []
    for name in sorted(seen):
        role, relative_dir = seen[name]
        findings.append(
            make_finding(
                f"o diretório `{relative_dir}` sugere {role}",
                "name-pattern",
                [make_evidence(relative_dir)],
            )
        )

    return {
        "findings": findings[:MAX_FINDINGS],
        "directories_matched": len(seen),
        "scope_limitations": list(ARCHITECTURE_LIMITATIONS),
    }


ARCHITECTURE_EXPLAINER_OUTPUT_SCHEMA = findings_output_schema(
    {"directories_matched": {"type": "integer"}}
)


STRUCTURE_LIMITATIONS = (
    "Python é analisado com `ast` da stdlib — parsing real, confiança HIGH",
    "outras linguagens usam regex sobre texto, que não entende escopo, "
    "comentário nem string: confiança LOW e falso positivo esperado",
    "arquivo Python com erro de sintaxe é contado como não-parseável, nunca "
    "analisado por heurística como substituto",
)


def _python_structure_findings(text, relative_file):
    """Estrutura de um módulo Python via `ast`. Erro de sintaxe propaga."""
    tree = ast.parse(text)
    lines = text.splitlines()
    findings = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            kind = "classe"
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "função"
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            kind = "import"
        else:
            continue

        name = getattr(node, "name", None)
        if kind == "import":
            claim = f"`{relative_file}` declara um import na linha {node.lineno}"
        else:
            claim = f"`{relative_file}` define a {kind} `{name}`"

        snippet = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else None
        findings.append(
            make_finding(claim, "ast-parse", [make_evidence(relative_file, node.lineno, snippet)])
        )

    return findings


def _heuristic_structure_findings(text, relative_file):
    findings = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for kind, matcher in STRUCTURE_HEURISTICS:
            match = matcher.match(line)
            if not match:
                continue
            findings.append(
                make_finding(
                    f"`{relative_file}` parece definir a {kind} `{match.group(1)}`",
                    "regex-heuristic",
                    [make_evidence(relative_file, line_number, line.strip())],
                )
            )
    return findings


def _handle_code_structure_analyzer(project_root, arguments):
    """Classes, funções e imports — `ast` para Python, heurística para o resto.

    O fork é o ponto central: a mesma pergunta produz confiança diferente
    conforme o método disponível. Heurística nunca é apresentada como fato, e
    Python com erro de sintaxe é contado como não-parseável em vez de cair na
    heurística — cair na heurística seria degradar a confiança sem avisar.
    """
    counters = {"unreadable_entries_skipped": 0}
    findings = []
    files_analyzed = 0
    files_unparseable = 0

    try:
        for file_path, relative_file in _iter_project_files(project_root, counters):
            if len(findings) >= MAX_FINDINGS:
                break

            extension = Path(relative_file).suffix
            if extension != ".py" and extension not in HEURISTIC_EXTENSIONS:
                continue

            text = _read_text(file_path)
            if text is None:
                counters["unreadable_entries_skipped"] += 1
                continue

            if extension == ".py":
                try:
                    findings.extend(_python_structure_findings(text, relative_file))
                except SyntaxError:
                    files_unparseable += 1
                    continue
            else:
                findings.extend(_heuristic_structure_findings(text, relative_file))

            files_analyzed += 1
    except OSError as error:
        raise ToolError("não foi possível varrer o diretório do projeto") from error

    return {
        "findings": findings[:MAX_FINDINGS],
        "files_analyzed": files_analyzed,
        "files_unparseable": files_unparseable,
        "scope_limitations": list(STRUCTURE_LIMITATIONS),
    }


CODE_STRUCTURE_OUTPUT_SCHEMA = findings_output_schema(
    {"files_analyzed": {"type": "integer"}, "files_unparseable": {"type": "integer"}}
)


DEPENDENCY_LIMITATIONS = (
    "`package.json` e `requirements.txt` são parseados de verdade: confiança HIGH",
    "`pyproject.toml` é extraído por regex — Python 3.9 não tem `tomllib` na "
    "stdlib, e adicionar dependência para ler dependência foi recusado: "
    "confiança LOW",
    "somente manifestos na RAIZ são lidos; workspaces e monorepos com "
    "manifesto aninhado não são cobertos",
    "apenas dependências DECLARADAS — import no código sem entrada no "
    "manifesto não é reportado",
)

# `dependencies = [...]` de um pyproject.toml, sem parser TOML. Não cobre
# array multilinha nem `[tool.poetry.dependencies]` — a limitação é declarada
# em vez de disfarçada com uma regex mais ambiciosa e mais frágil.
PYPROJECT_DEPENDENCIES = re.compile(r"dependencies\s*=\s*\[([^\]]*)\]", re.DOTALL)
PYPROJECT_ENTRY = re.compile(r'["\']([A-Za-z0-9._-]+)')
REQUIREMENT_NAME = re.compile(r"^([A-Za-z0-9._-]+)")


def _package_json_findings(text, relative_file):
    data = json.loads(text)
    findings = []
    for section in ("dependencies", "devDependencies"):
        entries = data.get(section)
        if not isinstance(entries, dict):
            continue
        for name, version in sorted(entries.items()):
            findings.append(
                make_finding(
                    f"`{name}` está declarada em {section} como `{version}`",
                    "manifest-read",
                    [make_evidence(relative_file, None, f'"{name}": "{version}"')],
                )
            )
    return findings


def _requirements_findings(text, relative_file):
    findings = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-"):
            continue
        match = REQUIREMENT_NAME.match(stripped)
        if not match:
            continue
        findings.append(
            make_finding(
                f"`{match.group(1)}` está declarada em requirements.txt",
                "manifest-read",
                [make_evidence(relative_file, line_number, stripped)],
            )
        )
    return findings


def _pyproject_findings(text, relative_file):
    findings = []
    block = PYPROJECT_DEPENDENCIES.search(text)
    if not block:
        return findings

    for name in PYPROJECT_ENTRY.findall(block.group(1)):
        findings.append(
            make_finding(
                f"`{name}` parece declarada em pyproject.toml",
                "regex-heuristic",
                [make_evidence(relative_file, None, name)],
            )
        )
    return findings


MANIFEST_PARSERS = {
    "package.json": _package_json_findings,
    "requirements.txt": _requirements_findings,
    "pyproject.toml": _pyproject_findings,
}


def _handle_dependency_analyzer(project_root, arguments):
    """Dependências DECLARADAS nos manifestos da raiz.

    Só o que está escrito num manifesto. Import no código sem entrada
    correspondente não é reportado — inferir a dependência a partir do import
    seria inventar uma declaração que o projeto não fez.
    """
    findings = []
    manifests_found = []
    manifests_unparseable = []

    for name in sorted(MANIFEST_PARSERS):
        manifest_path = os.path.join(project_root, name)
        if not os.path.isfile(manifest_path):
            continue

        manifests_found.append(name)
        text = _read_text(manifest_path)
        if text is None:
            manifests_unparseable.append(name)
            continue

        try:
            findings.extend(MANIFEST_PARSERS[name](text, name))
        except (ValueError, TypeError):
            # Manifesto malformado é reportado como não-parseável. Cair numa
            # regex de resgate produziria dependências que ninguém declarou.
            manifests_unparseable.append(name)

    return {
        "findings": findings[:MAX_FINDINGS],
        "manifests_found": manifests_found,
        "manifests_unparseable": manifests_unparseable,
        "scope_limitations": list(DEPENDENCY_LIMITATIONS),
    }


DEPENDENCY_OUTPUT_SCHEMA = findings_output_schema(
    {
        "manifests_found": {"type": "array", "items": {"type": "string"}},
        "manifests_unparseable": {"type": "array", "items": {"type": "string"}},
    }
)
