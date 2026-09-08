"""Servidor MCP sobre stdio: JSON-RPC 2.0 newline-delimited.

Transporte puro — dispatch de `initialize`, `tools/list`, `tools/call` e o
loop `serve_stdio`. As tools em si (`project_info`, `list_files`, Milestone 0
e 1) vivem em `exploration.py`; este módulo só roteia. Ver
docs/plan-project-intelligence-mcp.md, seção "Proposed Architecture", para o
desenho completo.
"""
from __future__ import annotations

import json
import logging

from .errors import ToolError
from .registry import TOOL_REGISTRY

logger = logging.getLogger(__name__)

SUPPORTED_PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "project-intel", "version": "0.1.0"}


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
