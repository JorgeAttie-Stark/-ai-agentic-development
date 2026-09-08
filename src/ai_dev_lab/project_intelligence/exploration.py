"""Camada Exploração (Milestone 1): tools de retrieval puro sobre a árvore do
projeto — `project_info` e `list_files`. Sem envelope de `findings`/
`confidence`: estas tools são a evidência, não uma inferência sobre ela.
"""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from .errors import ToolError

MAX_FILES_SCANNED = 20_000
MAX_FILE_SIZE_FOR_LINE_COUNT = 5 * 1024 * 1024
BINARY_SNIFF_BYTES = 8192

KNOWN_MANIFESTS = (
    "package.json",
    "requirements.txt",
    "pyproject.toml",
    "setup.py",
    "Pipfile",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "Gemfile",
    "composer.json",
)

# `list_files` respeita só o `.gitignore` de topo, via glob simples
# (`fnmatch`) — não a spec completa do Git. Declarado aqui em vez de
# escondido: fica no retorno sempre que `gitignore_applied` é `true`.
GITIGNORE_SCOPE_LIMITATIONS = (
    "apenas o .gitignore de topo é considerado, arquivos aninhados são ignorados",
    "padrões de negação (!padrão) são ignorados",
    "casamento via fnmatch (glob simples), não a spec completa do Git — inclui "
    "'*' cruzando '/' em padrões que contêm '/'",
)


def _is_binary(file_path):
    with open(file_path, "rb") as handle:
        chunk = handle.read(BINARY_SNIFF_BYTES)
    return b"\x00" in chunk


def _make_walk_error_handler(project_root, counters):
    """Só a raiz do projeto é fatal — um subdiretório inacessível (permissão,
    symlink quebrado, socket, ...) é degradação esperada de uma árvore
    arbitrária, não motivo para abortar a varredura inteira.
    """
    project_root_str = str(project_root)

    def _handle_walk_error(error):
        if error.filename == project_root_str:
            raise error
        counters["unreadable_entries_skipped"] += 1

    return _handle_walk_error


def _walk_pruned(project_root, counters):
    """`os.walk` sobre `project_root`, podando `.git` e sinalizando entrada
    ilegível via `counters` em vez de abortar a varredura inteira.
    """
    for dirpath, dirnames, filenames in os.walk(
        project_root,
        onerror=_make_walk_error_handler(project_root, counters),
        followlinks=False,
    ):
        if ".git" in dirnames:
            dirnames.remove(".git")
        yield dirpath, dirnames, filenames


def _handle_project_info(project_root, arguments):
    files_by_extension = {}
    total_files = 0
    total_lines = 0
    binary_files_skipped = 0
    large_files_skipped = 0
    scan_truncated = False
    counters = {"unreadable_entries_skipped": 0}

    try:
        for dirpath, dirnames, filenames in _walk_pruned(project_root, counters):
            for filename in filenames:
                if total_files >= MAX_FILES_SCANNED:
                    scan_truncated = True
                    break

                file_path = os.path.join(dirpath, filename)
                extension = Path(filename).suffix
                files_by_extension[extension] = files_by_extension.get(extension, 0) + 1
                total_files += 1

                # `os.path.isfile` nunca chama `open()` — FIFO sem writer não
                # bloqueia aqui. O `try/except OSError` abaixo não protegeria
                # contra o hang, porque esperar um writer não é um `OSError`.
                if not os.path.isfile(file_path):
                    counters["unreadable_entries_skipped"] += 1
                    continue

                # Um arquivo por vez: symlink quebrado, permissão negada ou
                # socket não pode abortar a varredura inteira, só o arquivo.
                try:
                    file_size = os.path.getsize(file_path)
                    if file_size > MAX_FILE_SIZE_FOR_LINE_COUNT:
                        large_files_skipped += 1
                        continue

                    if _is_binary(file_path):
                        binary_files_skipped += 1
                        continue

                    with open(file_path, "r", encoding="utf-8", errors="ignore") as handle:
                        total_lines += sum(1 for _ in handle)
                except OSError:
                    counters["unreadable_entries_skipped"] += 1

            if scan_truncated:
                break
    except OSError as error:
        raise ToolError("não foi possível varrer o diretório do projeto") from error

    manifests_present = [
        name for name in KNOWN_MANIFESTS if os.path.isfile(os.path.join(project_root, name))
    ]

    return {
        "files_by_extension": files_by_extension,
        "total_files": total_files,
        "total_lines": total_lines,
        "manifests_present": manifests_present,
        "binary_files_skipped": binary_files_skipped,
        "large_files_skipped": large_files_skipped,
        "unreadable_entries_skipped": counters["unreadable_entries_skipped"],
        "scan_truncated": scan_truncated,
    }


PROJECT_INFO_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "files_by_extension": {"type": "object", "additionalProperties": {"type": "integer"}},
        "total_files": {"type": "integer"},
        "total_lines": {"type": "integer"},
        "manifests_present": {"type": "array", "items": {"type": "string"}},
        "binary_files_skipped": {"type": "integer"},
        "large_files_skipped": {"type": "integer"},
        "unreadable_entries_skipped": {"type": "integer"},
        "scan_truncated": {"type": "boolean"},
    },
    "required": [
        "files_by_extension",
        "total_files",
        "total_lines",
        "manifests_present",
        "binary_files_skipped",
        "large_files_skipped",
        "unreadable_entries_skipped",
        "scan_truncated",
    ],
    "additionalProperties": False,
}


def _load_gitignore_patterns(project_root):
    """Lê o `.gitignore` de topo, best-effort. `None` quando não existe ou
    não é arquivo regular — distinto de lista vazia, que significa "existe,
    mas só tem comentário/linha em branco" (`gitignore_applied` continua
    `true` nesse caso).
    """
    gitignore_path = os.path.join(project_root, ".gitignore")

    # `os.path.isfile` antes de qualquer `open()` — mesma guarda do FIFO em
    # `_handle_project_info`, agora sobre o `.gitignore` em si.
    if not os.path.isfile(gitignore_path):
        return None

    patterns = []
    with open(gitignore_path, "r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("!"):
                continue
            patterns.append(line)
    return patterns


def _gitignore_pattern_matches(pattern, name, relative_posix_path):
    # `/` final é tratado como padrão de nome comum: casa arquivo e
    # diretório com o mesmo nome. Descartar a entrada em vez de normalizar
    # geraria um padrão com barra sobrando que nunca casa nada — falso
    # silencioso, pior que a simplificação.
    if pattern.endswith("/"):
        pattern = pattern[:-1]

    if "/" in pattern:
        return fnmatch.fnmatch(relative_posix_path, pattern)
    return fnmatch.fnmatch(name, pattern)


def _matches_any_gitignore_pattern(patterns, name, relative_posix_path):
    return any(
        _gitignore_pattern_matches(pattern, name, relative_posix_path) for pattern in patterns
    )


def _prune_gitignore_dirs(dirnames, dirpath, project_root, patterns):
    """Remove de `dirnames` todo diretório que casa um padrão — mesma
    técnica usada para podar `.git`. Poda a subárvore inteira: nada dentro
    dela chega a ser visitado pelo `os.walk`.
    """
    kept = []
    for dirname in dirnames:
        relative_dir = Path(dirpath, dirname).relative_to(project_root).as_posix()
        if _matches_any_gitignore_pattern(patterns, dirname, relative_dir):
            continue
        kept.append(dirname)
    dirnames[:] = kept


def _handle_list_files(project_root, arguments):
    counters = {"unreadable_entries_skipped": 0}
    patterns = _load_gitignore_patterns(project_root)
    gitignore_applied = patterns is not None
    if patterns is None:
        patterns = []

    files = []
    visited = 0
    scan_truncated = False

    try:
        for dirpath, dirnames, filenames in _walk_pruned(project_root, counters):
            if patterns:
                _prune_gitignore_dirs(dirnames, dirpath, project_root, patterns)

            for filename in filenames:
                # Teto conta arquivo *visitado*, antes do filtro de
                # `.gitignore` — a mesma constante de `_handle_project_info`,
                # com a mesma semântica de "um item examinado por vez".
                if visited >= MAX_FILES_SCANNED:
                    scan_truncated = True
                    break
                visited += 1

                relative_file = Path(dirpath, filename).relative_to(project_root).as_posix()
                if patterns and _matches_any_gitignore_pattern(
                    patterns, filename, relative_file
                ):
                    continue

                file_path = os.path.join(dirpath, filename)
                if not os.path.isfile(file_path):
                    counters["unreadable_entries_skipped"] += 1
                    continue

                files.append(relative_file)

            if scan_truncated:
                break
    except OSError as error:
        raise ToolError("não foi possível varrer o diretório do projeto") from error

    files.sort()
    scope_limitations = list(GITIGNORE_SCOPE_LIMITATIONS) if gitignore_applied else []

    return {
        "files": files,
        "total_files": len(files),
        "scan_truncated": scan_truncated,
        "unreadable_entries_skipped": counters["unreadable_entries_skipped"],
        "gitignore_applied": gitignore_applied,
        "scope_limitations": scope_limitations,
    }


LIST_FILES_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "files": {"type": "array", "items": {"type": "string"}},
        "total_files": {"type": "integer"},
        "scan_truncated": {"type": "boolean"},
        "unreadable_entries_skipped": {"type": "integer"},
        "gitignore_applied": {"type": "boolean"},
        "scope_limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "files",
        "total_files",
        "scan_truncated",
        "unreadable_entries_skipped",
        "gitignore_applied",
        "scope_limitations",
    ],
    "additionalProperties": False,
}

TOOL_REGISTRY = {
    "project_info": {
        "description": "Contagem de arquivos, linhas e manifestos conhecidos na raiz do projeto.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": PROJECT_INFO_OUTPUT_SCHEMA,
        "handler": _handle_project_info,
    },
    "list_files": {
        "description": (
            "Lista os arquivos da raiz do projeto, ignorando `.git/` e respeitando "
            "best-effort um `.gitignore` de topo."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": LIST_FILES_OUTPUT_SCHEMA,
        "handler": _handle_list_files,
    },
}
