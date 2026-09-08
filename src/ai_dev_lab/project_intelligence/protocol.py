"""Servidor MCP sobre stdio: JSON-RPC 2.0 newline-delimited.

Escopo do Milestone 0: `initialize`, `tools/list`, `tools/call` para uma
única tool real (`project_info`). Ver docs/plan-project-intelligence-mcp.md,
seção "Proposed Architecture", para o desenho completo.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "project-intel", "version": "0.1.0"}

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


class ToolError(Exception):
    """Falha esperada de execução de uma tool — mensagem já é segura para o cliente."""


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


def _handle_project_info(project_root, arguments):
    files_by_extension = {}
    total_files = 0
    total_lines = 0
    binary_files_skipped = 0
    large_files_skipped = 0
    scan_truncated = False
    counters = {"unreadable_entries_skipped": 0}

    try:
        for dirpath, dirnames, filenames in os.walk(
            project_root,
            onerror=_make_walk_error_handler(project_root, counters),
            followlinks=False,
        ):
            if ".git" in dirnames:
                dirnames.remove(".git")

            for filename in filenames:
                if total_files >= MAX_FILES_SCANNED:
                    scan_truncated = True
                    break

                file_path = os.path.join(dirpath, filename)
                extension = Path(filename).suffix
                files_by_extension[extension] = files_by_extension.get(extension, 0) + 1
                total_files += 1

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

TOOL_REGISTRY = {
    "project_info": {
        "description": "Contagem de arquivos, linhas e manifestos conhecidos na raiz do projeto.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": PROJECT_INFO_OUTPUT_SCHEMA,
        "handler": _handle_project_info,
    },
}


def _error_response(request_id, code, message):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _success_response(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _handle_initialize(request_id, context):
    context["initialized"] = True
    return _success_response(
        request_id,
        {
            "protocolVersion": SUPPORTED_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        },
    )


def _describe_tool(name, spec):
    # `outputSchema` é opcional pela spec 2025-06-18 (ex.: uma tool que
    # devolve texto puro, sem dado estruturado). Indexação direta faria uma
    # tool sem a chave no registry levantar `KeyError` aqui — dentro do
    # list comprehension de `_handle_tools_list` — que o `except Exception`
    # de `serve_stdio` converte em erro genérico, apagando *todas* as tools
    # da resposta por causa de uma só.
    description = {
        "name": name,
        "description": spec["description"],
        "inputSchema": spec["input_schema"],
    }
    output_schema = spec.get("output_schema")
    if output_schema is not None:
        description["outputSchema"] = output_schema
    return description


def _handle_tools_list(request_id):
    tools = [_describe_tool(name, spec) for name, spec in TOOL_REGISTRY.items()]
    return _success_response(request_id, {"tools": tools})


def _handle_tools_call(request_id, params, context):
    if not isinstance(params, dict):
        return _error_response(request_id, -32602, "params deve ser um objeto")

    name = params.get("name")
    if name not in TOOL_REGISTRY:
        return _error_response(request_id, -32602, f"tool desconhecida: {name}")

    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        return _error_response(request_id, -32602, "arguments deve ser um objeto")

    project_root = context["roots"]["default"]
    handler = TOOL_REGISTRY[name]["handler"]

    try:
        result = handler(project_root, arguments)
    except ToolError as error:
        return _error_response(request_id, -32603, str(error))

    # `CallToolResult` da spec 2025-06-18: `content` é obrigatório — é o que
    # o modelo efetivamente lê. `structuredContent` espelha o mesmo dado para
    # clientes que sabem validar contra `outputSchema` (ver TOOL_REGISTRY).
    payload = {
        "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
        "structuredContent": result,
        "isError": False,
    }
    return _success_response(request_id, payload)


def dispatch(request, context):
    """Roteia uma requisição JSON-RPC já decodificada. Retorna `None` para notificações."""
    request_id = request.get("id") if isinstance(request, dict) else None
    is_notification = not isinstance(request, dict) or "id" not in request

    if not isinstance(request, dict) or "jsonrpc" not in request or "method" not in request:
        if is_notification:
            return None
        return _error_response(request_id, -32600, "requisição inválida")

    method = request["method"]
    params = request.get("params", {})

    if method == "initialize":
        response = _handle_initialize(request_id, context)
        return None if is_notification else response

    if method in ("tools/list", "tools/call") and not context.get("initialized", False):
        response = _error_response(request_id, -32600, "initialize ainda não foi concluído")
        return None if is_notification else response

    if method == "tools/list":
        response = _handle_tools_list(request_id)
    elif method == "tools/call":
        response = _handle_tools_call(request_id, params, context)
    else:
        response = _error_response(request_id, -32601, f"método desconhecido: {method}")

    return None if is_notification else response


def _write_response(output_stream, response):
    output_stream.write(json.dumps(response) + "\n")
    # Sem flush explícito, um pipe real pode reter a resposta até o processo
    # terminar — não aparece em testes com io.StringIO, só em stdio real.
    output_stream.flush()


def serve_stdio(input_stream, output_stream, context):
    """Loop principal: uma requisição JSON-RPC por linha até o stream fechar."""
    for line in input_stream:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            _write_response(output_stream, _error_response(None, -32700, "JSON inválido"))
            continue

        # Único `except Exception:` do código: um bug real dentro de um
        # handler não pode derrubar o processo nem corromper o framing stdio.
        # Erros esperados (ToolError) já foram tratados dentro de dispatch();
        # o que chega aqui é sempre inesperado.
        try:
            response = dispatch(request, context)
        except Exception:
            logger.exception("erro inesperado ao processar requisição")
            request_id = request.get("id") if isinstance(request, dict) else None
            response = _error_response(request_id, -32603, "erro interno do servidor")

        if response is not None:
            _write_response(output_stream, response)
