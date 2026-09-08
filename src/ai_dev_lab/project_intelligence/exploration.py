"""Camada Exploração (Milestone 1): tools de retrieval puro sobre a árvore do
projeto — `project_info` e `list_files`. Sem envelope de `findings`/
`confidence`: estas tools são a evidência, não uma inferência sobre ela.
"""
from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from .errors import ToolError
from .paths import resolve_within

MAX_FILES_SCANNED = 20_000
MAX_FILE_SIZE_FOR_LINE_COUNT = 5 * 1024 * 1024
BINARY_SNIFF_BYTES = 8192

# Teto de UMA resposta `read_file` serializada numa linha stdio — orçamento
# diferente de `MAX_FILE_SIZE_FOR_LINE_COUNT`, que é "quanto ler para contar
# linhas ao varrer 20.000 arquivos". Valor de julgamento, não medição.
MAX_FILE_SIZE_FOR_READ = 1024 * 1024

# Teto de matches de UMA resposta `search_code`, e teto do trecho de linha
# devolvido por match. O segundo existe porque um arquivo minificado tem
# linhas de milhares de caracteres — sem corte, um match só estouraria a
# resposta inteira. Valores de julgamento, não medição.
MAX_SEARCH_RESULTS = 200
MAX_MATCH_LINE_LENGTH = 500

# `search_code` compila o padrão do cliente com `re`. Um padrão
# patológico (`(a+)+$`) tem custo exponencial — o dano fica limitado pelo
# teto de tamanho de arquivo e pelo de matches, não eliminado. Declarado
# no retorno em vez de escondido.
SEARCH_SCOPE_LIMITATIONS = (
    "o padrão é uma regex Python (`re`), não a sintaxe do grep",
    "regex patológica pode ser custosa — o limite de tamanho de arquivo e "
    "o de resultados contêm o dano, não o eliminam",
    "arquivos binários e acima do limite de tamanho não são pesquisados",
)

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

def _handle_read_file(project_root, arguments):
    relative_path = arguments.get("relative_path")
    if not isinstance(relative_path, str) or not relative_path:
        raise ToolError("relative_path é obrigatório e deve ser uma string não vazia")

    resolved = resolve_within(project_root, relative_path)

    if not os.path.exists(resolved):
        raise ToolError("arquivo não encontrado")
    elif os.path.isdir(resolved):
        raise ToolError("caminho é um diretório")
    elif not os.path.isfile(resolved):
        raise ToolError("não é um arquivo regular")

    # TOCTOU, camada 2: `resolved` já veio resolvido de `resolve_within`
    # (camada 1), mas a janela entre aquele `.resolve()` e este `open()`
    # continua existindo. `O_NOFOLLOW` fecha só o componente final — não
    # protege componentes intermediários trocados no meio do caminho.
    try:
        fd = os.open(str(resolved), os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as handle:
            raw = handle.read(MAX_FILE_SIZE_FOR_READ + 1)
    except PermissionError:
        raise ToolError("sem permissão de leitura") from None
    except OSError:
        raise ToolError("não foi possível abrir o arquivo") from None

    # Sniff sempre, antes de decidir truncar: um binário maior que o teto
    # precisa reportar "binário", não "truncado". Aplicado aos bytes já
    # lidos pelo fd — nunca reabrindo por path (`_is_binary`), o que
    # reintroduziria a janela TOCTOU que a camada 2 acabou de fechar.
    if b"\x00" in raw[:BINARY_SNIFF_BYTES]:
        raise ToolError("arquivo binário, não é possível ler como texto")

    truncated = len(raw) > MAX_FILE_SIZE_FOR_READ
    if truncated:
        raw = raw[:MAX_FILE_SIZE_FOR_READ]
        content = raw.decode("utf-8", errors="ignore")
    else:
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise ToolError("conteúdo não é UTF-8 válido") from None

    return {
        "content": content,
        "line_count": len(content.splitlines()),
        "truncated": truncated,
    }


READ_FILE_INPUT_SCHEMA = {
    "type": "object",
    "properties": {"relative_path": {"type": "string", "minLength": 1}},
    "required": ["relative_path"],
    "additionalProperties": False,
}

READ_FILE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "content": {"type": "string"},
        "line_count": {"type": "integer"},
        "truncated": {"type": "boolean"},
    },
    "required": ["content", "line_count", "truncated"],
    "additionalProperties": False,
}



def _compile_search_pattern(arguments):
    pattern = arguments.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        raise ToolError("pattern é obrigatório e deve ser uma string não vazia")

    flags = 0 if arguments.get("case_sensitive") else re.IGNORECASE
    try:
        return re.compile(pattern, flags)
    except re.error:
        # Mensagem constante: a de `re.error` cita o padrão do cliente, o que
        # não vaza path, mas o resto do módulo não interpola exceção e não
        # vale abrir precedente por um caso só.
        raise ToolError("pattern não é uma regex válida") from None


def _read_text_for_search(file_path):
    """Devolve o texto do arquivo, ou `None` se ele não deve ser pesquisado.

    Lê o arquivo inteiro (limitado por `MAX_FILE_SIZE_FOR_LINE_COUNT`) em vez
    de linha a linha de propósito: um `.min.js` de uma única linha derrota a
    leitura incremental, então o teto por tamanho é a única proteção de
    memória que funciona nos dois formatos. O sniff de binário roda sobre os
    bytes já lidos — nunca reabrindo por path.
    """
    with open(file_path, "rb") as handle:
        raw = handle.read()

    if b"\x00" in raw[:BINARY_SNIFF_BYTES]:
        return None
    return raw.decode("utf-8", errors="ignore")


def _handle_search_code(project_root, arguments):
    matcher = _compile_search_pattern(arguments)

    counters = {"unreadable_entries_skipped": 0}
    patterns = _load_gitignore_patterns(project_root)
    gitignore_applied = patterns is not None
    if patterns is None:
        patterns = []

    matches = []
    files_scanned = 0
    binary_files_skipped = 0
    large_files_skipped = 0
    truncated = False

    try:
        for dirpath, dirnames, filenames in _walk_pruned(project_root, counters):
            if patterns:
                _prune_gitignore_dirs(dirnames, dirpath, project_root, patterns)

            for filename in filenames:
                if len(matches) >= MAX_SEARCH_RESULTS:
                    truncated = True
                    break

                relative_file = Path(dirpath, filename).relative_to(project_root).as_posix()
                if patterns and _matches_any_gitignore_pattern(
                    patterns, filename, relative_file
                ):
                    continue

                file_path = os.path.join(dirpath, filename)
                # `os.path.isfile` antes de qualquer `open()` — FIFO sem
                # writer não bloqueia aqui.
                if not os.path.isfile(file_path):
                    counters["unreadable_entries_skipped"] += 1
                    continue

                try:
                    if os.path.getsize(file_path) > MAX_FILE_SIZE_FOR_LINE_COUNT:
                        large_files_skipped += 1
                        continue

                    text = _read_text_for_search(file_path)
                except OSError:
                    counters["unreadable_entries_skipped"] += 1
                    continue

                if text is None:
                    binary_files_skipped += 1
                    continue

                files_scanned += 1
                for line_number, line in enumerate(text.splitlines(), start=1):
                    if len(matches) >= MAX_SEARCH_RESULTS:
                        truncated = True
                        break
                    if matcher.search(line):
                        matches.append(
                            {
                                "file": relative_file,
                                "line_number": line_number,
                                "line": line[:MAX_MATCH_LINE_LENGTH],
                            }
                        )

            if truncated:
                break
    except OSError as error:
        raise ToolError("não foi possível varrer o diretório do projeto") from error

    matches.sort(key=lambda match: (match["file"], match["line_number"]))

    scope_limitations = list(SEARCH_SCOPE_LIMITATIONS)
    if gitignore_applied:
        scope_limitations.extend(GITIGNORE_SCOPE_LIMITATIONS)

    return {
        "matches": matches,
        "total_matches": len(matches),
        "files_scanned": files_scanned,
        "truncated": truncated,
        "binary_files_skipped": binary_files_skipped,
        "large_files_skipped": large_files_skipped,
        "unreadable_entries_skipped": counters["unreadable_entries_skipped"],
        "gitignore_applied": gitignore_applied,
        "scope_limitations": scope_limitations,
    }


SEARCH_CODE_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string", "minLength": 1},
        "case_sensitive": {"type": "boolean"},
    },
    "required": ["pattern"],
    "additionalProperties": False,
}

SEARCH_CODE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "line_number": {"type": "integer"},
                    "line": {"type": "string"},
                },
                "required": ["file", "line_number", "line"],
                "additionalProperties": False,
            },
        },
        "total_matches": {"type": "integer"},
        "files_scanned": {"type": "integer"},
        "truncated": {"type": "boolean"},
        "binary_files_skipped": {"type": "integer"},
        "large_files_skipped": {"type": "integer"},
        "unreadable_entries_skipped": {"type": "integer"},
        "gitignore_applied": {"type": "boolean"},
        "scope_limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "matches",
        "total_matches",
        "files_scanned",
        "truncated",
        "binary_files_skipped",
        "large_files_skipped",
        "unreadable_entries_skipped",
        "gitignore_applied",
        "scope_limitations",
    ],
    "additionalProperties": False,
}


def _top_extensions(files_by_extension):
    ranked = sorted(files_by_extension.items(), key=lambda item: (-item[1], item[0]))
    return [{"extension": extension, "count": count} for extension, count in ranked]


def _largest_directories(files):
    counts = {}
    for relative_file in files:
        parent = Path(relative_file).parent.as_posix()
        directory = "" if parent == "." else parent
        counts[directory] = counts.get(directory, 0) + 1

    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [{"directory": directory, "file_count": count} for directory, count in ranked]


def _handle_project_profile(project_root, arguments):
    """Visão consolidada, derivada das tools de exploração já existentes.

    Chama `_handle_project_info` e `_handle_list_files` em vez de varrer a
    árvore por conta própria. O custo é uma varredura a mais; o ganho é zero
    duplicação de lógica de poda, `.gitignore`, teto e degradação — que é o
    requisito, e onde um bug duplicado seria mais caro que a varredura extra.

    Retrieval pura, como as outras três: agrega e ordena fato observado, não
    infere nada. Por isso não carrega envelope de `findings`/`confidence`.
    """
    info = _handle_project_info(project_root, arguments)
    listing = _handle_list_files(project_root, arguments)

    depths = [len(Path(relative_file).parts) for relative_file in listing["files"]]

    scope_limitations = list(listing["scope_limitations"])
    scope_limitations.append(
        "derivado de project_info e list_files — duas varreduras da árvore, "
        "não uma; contagens podem divergir se o projeto mudar entre elas"
    )

    return {
        "total_files": info["total_files"],
        "total_lines": info["total_lines"],
        "manifests_present": info["manifests_present"],
        "top_extensions": _top_extensions(info["files_by_extension"]),
        "largest_directories": _largest_directories(listing["files"]),
        "max_depth": max(depths) if depths else 0,
        "derived_from": ["project_info", "list_files"],
        "scan_truncated": info["scan_truncated"] or listing["scan_truncated"],
        "scope_limitations": scope_limitations,
    }


PROJECT_PROFILE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "total_files": {"type": "integer"},
        "total_lines": {"type": "integer"},
        "manifests_present": {"type": "array", "items": {"type": "string"}},
        "top_extensions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "extension": {"type": "string"},
                    "count": {"type": "integer"},
                },
                "required": ["extension", "count"],
                "additionalProperties": False,
            },
        },
        "largest_directories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string"},
                    "file_count": {"type": "integer"},
                },
                "required": ["directory", "file_count"],
                "additionalProperties": False,
            },
        },
        "max_depth": {"type": "integer"},
        "derived_from": {"type": "array", "items": {"type": "string"}},
        "scan_truncated": {"type": "boolean"},
        "scope_limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "total_files",
        "total_lines",
        "manifests_present",
        "top_extensions",
        "largest_directories",
        "max_depth",
        "derived_from",
        "scan_truncated",
        "scope_limitations",
    ],
    "additionalProperties": False,
}


# Fonte única: `tools/list` serializa deste dict e `tools/call` despacha dele.
# Definido no fim do módulo porque cada entrada referencia o handler já
# definido acima — ordem de avaliação, não estilo.
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
    "read_file": {
        "description": "Lê o conteúdo de um arquivo de texto dentro da raiz do projeto.",
        "input_schema": READ_FILE_INPUT_SCHEMA,
        "output_schema": READ_FILE_OUTPUT_SCHEMA,
        "handler": _handle_read_file,
    },
    "search_code": {
        "description": (
            "Pesquisa uma regex nos arquivos de texto da raiz do projeto e devolve "
            "arquivo, número de linha e o trecho da linha que casou."
        ),
        "input_schema": SEARCH_CODE_INPUT_SCHEMA,
        "output_schema": SEARCH_CODE_OUTPUT_SCHEMA,
        "handler": _handle_search_code,
    },
    "project_profile": {
        "description": (
            "Visão consolidada do projeto, derivada de project_info e list_files: "
            "extensões mais comuns, maiores diretórios e profundidade máxima."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": PROJECT_PROFILE_OUTPUT_SCHEMA,
        "handler": _handle_project_profile,
    },
}
