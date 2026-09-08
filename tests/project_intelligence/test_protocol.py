import io
import json
import logging
import os
import shutil
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_dev_lab.project_intelligence import exploration, protocol
from ai_dev_lab.project_intelligence.protocol import (
    SUPPORTED_PROTOCOL_VERSION,
    dispatch,
    serve_stdio,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "fake_project"


def make_context(project_root=None, initialized=False):
    return {
        "roots": {"default": project_root or FIXTURE_ROOT},
        "initialized": initialized,
    }


class TestInitialize(unittest.TestCase):

    def test_returns_standard_mcp_payload(self):
        context = make_context()
        request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}

        response = dispatch(request, context)

        self.assertEqual(response["jsonrpc"], "2.0")
        self.assertEqual(response["id"], 1)
        result = response["result"]
        self.assertEqual(result["protocolVersion"], SUPPORTED_PROTOCOL_VERSION)
        self.assertEqual(result["capabilities"], {"tools": {}})
        self.assertEqual(result["serverInfo"], {"name": "project-intel", "version": "0.1.0"})

    def test_ignores_project_root_sent_in_payload(self):
        # Regressão: projectRoot é configuração de servidor, nunca campo de
        # `initialize`. Um cliente mal-intencionado ou desatualizado que mande
        # um `projectRoot` no payload não pode influenciar o servidor.
        context = make_context()
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"projectRoot": "/tmp/nao-deveria-ser-lido"},
        }

        response = dispatch(request, context)

        self.assertEqual(response["result"]["protocolVersion"], SUPPORTED_PROTOCOL_VERSION)
        self.assertEqual(context["roots"]["default"], FIXTURE_ROOT)

    def test_marks_context_as_initialized(self):
        context = make_context()
        request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}

        dispatch(request, context)

        self.assertTrue(context["initialized"])


class TestProtocolErrors(unittest.TestCase):

    def test_unknown_method_returns_method_not_found(self):
        context = make_context(initialized=True)
        request = {"jsonrpc": "2.0", "id": 2, "method": "does/not/exist"}

        response = dispatch(request, context)

        self.assertEqual(response["error"]["code"], -32601)
        self.assertEqual(response["id"], 2)

    def test_missing_method_returns_invalid_request(self):
        context = make_context(initialized=True)
        request = {"jsonrpc": "2.0", "id": 3}

        response = dispatch(request, context)

        self.assertEqual(response["error"]["code"], -32600)

    def test_missing_jsonrpc_returns_invalid_request(self):
        context = make_context(initialized=True)
        request = {"id": 4, "method": "tools/list"}

        response = dispatch(request, context)

        self.assertEqual(response["error"]["code"], -32600)

    def test_notification_without_id_returns_none(self):
        context = make_context(initialized=True)
        request = {"jsonrpc": "2.0", "method": "tools/list"}

        response = dispatch(request, context)

        self.assertIsNone(response)

    def test_tools_call_before_initialize_returns_invalid_request(self):
        context = make_context(initialized=False)
        request = {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "project_info"}}

        response = dispatch(request, context)

        self.assertEqual(response["error"]["code"], -32600)

    def test_tools_list_before_initialize_returns_invalid_request(self):
        context = make_context(initialized=False)
        request = {"jsonrpc": "2.0", "id": 6, "method": "tools/list"}

        response = dispatch(request, context)

        self.assertEqual(response["error"]["code"], -32600)


class TestToolsList(unittest.TestCase):

    def test_lists_the_registered_tool_catalog_with_camel_case_schema(self):
        context = make_context(initialized=True)
        request = {"jsonrpc": "2.0", "id": 7, "method": "tools/list"}

        response = dispatch(request, context)

        tools = response["result"]["tools"]
        # Conjunto de nomes, não contagem: pega adição *e* remoção, e obriga
        # uma tool nova a ser mudança deliberada do catálogo, não efeito
        # colateral silencioso.
        self.assertEqual(
            {tool["name"] for tool in tools},
            {
                # Camada Exploração — retrieval pura
                "project_info",
                "list_files",
                "read_file",
                "search_code",
                "project_profile",
                # Camada Entendimento — envelope de findings/confidence
                "project_map",
                "architecture_explainer",
                "code_structure_analyzer",
                "dependency_analyzer",
                # Camada Inferência — a fronteira epistemológica
                "data_flow_analyzer",
                "business_rules_analyzer",
            },
        )
        for tool in tools:
            with self.subTest(tool=tool["name"]):
                self.assertIn("inputSchema", tool)
                self.assertNotIn("input_schema", tool)

    def test_project_info_declares_output_schema(self):
        # Acompanha `structuredContent` em `tools/call` — sem `outputSchema`
        # declarado, um cliente que valide contra a spec não tem como
        # verificar o formato do dado estruturado que a tool devolve.
        context = make_context(initialized=True)
        request = {"jsonrpc": "2.0", "id": 71, "method": "tools/list"}

        response = dispatch(request, context)

        schema = response["result"]["tools"][0]["outputSchema"]
        self.assertEqual(schema["type"], "object")
        self.assertIn("total_files", schema["properties"])

    def test_project_info_schema_has_no_root_id_property(self):
        # DoD do plano: raiz é resolvida por parâmetro do servidor, nunca
        # exposta como campo que o cliente precise preencher na chamada.
        context = make_context(initialized=True)
        request = {"jsonrpc": "2.0", "id": 70, "method": "tools/list"}

        response = dispatch(request, context)

        schema = response["result"]["tools"][0]["inputSchema"]
        self.assertNotIn("root_id", schema.get("properties", {}))

    def test_tool_without_output_schema_is_still_listed(self):
        # Regressão: `outputSchema` é opcional pela spec 2025-06-18 (ex.:
        # `read_file` do Milestone 1, que devolve texto puro). Uma tool sem
        # a chave no registry não pode levantar `KeyError` e apagar o
        # servidor inteiro da lista de tools.
        extra_tool = {
            "description": "tool sem output_schema",
            "input_schema": {"type": "object", "properties": {}},
            "handler": lambda project_root, arguments: {},
        }
        context = make_context(initialized=True)
        request = {"jsonrpc": "2.0", "id": 72, "method": "tools/list"}

        with patch.dict(protocol.TOOL_REGISTRY, {"no_schema_tool": extra_tool}):
            response = dispatch(request, context)

        tools = {tool["name"]: tool for tool in response["result"]["tools"]}
        self.assertIn("no_schema_tool", tools)
        self.assertNotIn("outputSchema", tools["no_schema_tool"])

    def test_project_info_output_schema_unchanged_on_wire(self):
        # Contraprova: `project_info` já declara `output_schema` — a
        # inclusão condicional não pode alterar o wire dela.
        context = make_context(initialized=True)
        request = {"jsonrpc": "2.0", "id": 73, "method": "tools/list"}

        response = dispatch(request, context)

        tools = {tool["name"]: tool for tool in response["result"]["tools"]}
        self.assertIn("outputSchema", tools["project_info"])
        self.assertEqual(tools["project_info"]["outputSchema"]["type"], "object")

    def test_list_files_schema_has_empty_input_schema_without_root_id(self):
        context = make_context(initialized=True)
        request = {"jsonrpc": "2.0", "id": 74, "method": "tools/list"}

        response = dispatch(request, context)

        tools = {tool["name"]: tool for tool in response["result"]["tools"]}
        schema = tools["list_files"]["inputSchema"]
        self.assertEqual(
            schema, {"type": "object", "properties": {}, "additionalProperties": False}
        )
        self.assertNotIn("root_id", schema["properties"])

    def test_list_files_declares_output_schema(self):
        context = make_context(initialized=True)
        request = {"jsonrpc": "2.0", "id": 75, "method": "tools/list"}

        response = dispatch(request, context)

        tools = {tool["name"]: tool for tool in response["result"]["tools"]}
        schema = tools["list_files"]["outputSchema"]
        self.assertEqual(schema["type"], "object")
        self.assertIn("total_files", schema["properties"])
        self.assertIn("files", schema["properties"])

    def test_read_file_declares_output_schema(self):
        context = make_context(initialized=True)
        request = {"jsonrpc": "2.0", "id": 76, "method": "tools/list"}

        response = dispatch(request, context)

        tools = {tool["name"]: tool for tool in response["result"]["tools"]}
        schema = tools["read_file"]["outputSchema"]
        self.assertEqual(schema["type"], "object")
        self.assertIn("content", schema["properties"])
        self.assertIn("line_count", schema["properties"])
        self.assertIn("truncated", schema["properties"])

    def test_read_file_declares_input_schema_requiring_relative_path(self):
        context = make_context(initialized=True)
        request = {"jsonrpc": "2.0", "id": 77, "method": "tools/list"}

        response = dispatch(request, context)

        tools = {tool["name"]: tool for tool in response["result"]["tools"]}
        schema = tools["read_file"]["inputSchema"]
        self.assertIn("relative_path", schema["properties"])
        self.assertIn("relative_path", schema["required"])


class TestToolsCall(unittest.TestCase):

    def test_unknown_tool_name_returns_invalid_params(self):
        context = make_context(initialized=True)
        request = {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {"name": "does_not_exist", "arguments": {}},
        }

        response = dispatch(request, context)

        self.assertEqual(response["error"]["code"], -32602)

    def test_non_object_arguments_returns_invalid_params(self):
        context = make_context(initialized=True)
        request = {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {"name": "project_info", "arguments": "not-an-object"},
        }

        response = dispatch(request, context)

        self.assertEqual(response["error"]["code"], -32602)

    def test_project_info_returns_exact_counts_for_fixture(self):
        context = make_context(project_root=FIXTURE_ROOT, initialized=True)
        request = {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {"name": "project_info", "arguments": {}},
        }

        response = dispatch(request, context)

        result = response["result"]
        content = result["structuredContent"]
        self.assertEqual(content["total_files"], 5)
        self.assertEqual(content["total_lines"], 19)
        self.assertEqual(
            content["files_by_extension"],
            {".py": 2, ".js": 1, ".json": 1, ".bin": 1},
        )
        self.assertEqual(content["manifests_present"], ["package.json"])
        self.assertEqual(content["binary_files_skipped"], 1)
        self.assertEqual(content["large_files_skipped"], 0)
        self.assertEqual(content["unreadable_entries_skipped"], 0)
        self.assertFalse(content["scan_truncated"])

    def test_project_info_wraps_result_in_call_tool_result_envelope(self):
        # Spec 2025-06-18: `result` de `tools/call` é um `CallToolResult` —
        # `content` é obrigatório e é o que o modelo efetivamente lê. Sem
        # isso, o Python SDK rejeita a resposta e o TS SDK entrega
        # `content: []` ao modelo (ver finding do reviewer).
        context = make_context(project_root=FIXTURE_ROOT, initialized=True)
        request = {
            "jsonrpc": "2.0",
            "id": 43,
            "method": "tools/call",
            "params": {"name": "project_info", "arguments": {}},
        }

        response = dispatch(request, context)

        result = response["result"]
        self.assertIn("content", result)
        self.assertEqual(result["content"][0]["type"], "text")
        parsed_text = json.loads(result["content"][0]["text"])
        self.assertEqual(parsed_text, result["structuredContent"])
        self.assertFalse(result["isError"])

    def test_project_info_marks_scan_truncated_when_files_exceed_max(self):
        # Fixture tem 5 arquivos; teto baixo via monkeypatch força o
        # truncamento sem criar 20 000 arquivos reais (Risks do plano).
        context = make_context(project_root=FIXTURE_ROOT, initialized=True)
        request = {
            "jsonrpc": "2.0",
            "id": 40,
            "method": "tools/call",
            "params": {"name": "project_info", "arguments": {}},
        }

        with patch.object(exploration, "MAX_FILES_SCANNED", 2):
            response = dispatch(request, context)

        content = response["result"]["structuredContent"]
        self.assertTrue(content["scan_truncated"])
        self.assertEqual(content["total_files"], 2)

    def test_project_info_does_not_truncate_when_under_max_files(self):
        # Contraprova: com o teto real (bem acima de 5 arquivos), a fixture
        # não é truncada — trava o comportamento padrão do teto.
        context = make_context(project_root=FIXTURE_ROOT, initialized=True)
        request = {
            "jsonrpc": "2.0",
            "id": 41,
            "method": "tools/call",
            "params": {"name": "project_info", "arguments": {}},
        }

        response = dispatch(request, context)

        self.assertFalse(response["result"]["structuredContent"]["scan_truncated"])

    def test_project_info_skips_files_over_size_cap(self):
        # Teto de 0 byte força todo arquivo não vazio da fixture a ser
        # tratado como grande demais para contagem de linhas — inclusive o
        # binário, que por isso nunca chega a ser aberto para sniff.
        context = make_context(project_root=FIXTURE_ROOT, initialized=True)
        request = {
            "jsonrpc": "2.0",
            "id": 42,
            "method": "tools/call",
            "params": {"name": "project_info", "arguments": {}},
        }

        with patch.object(exploration, "MAX_FILE_SIZE_FOR_LINE_COUNT", 0):
            response = dispatch(request, context)

        content = response["result"]["structuredContent"]
        self.assertEqual(content["large_files_skipped"], 5)
        self.assertEqual(content["total_lines"], 0)
        self.assertEqual(content["binary_files_skipped"], 0)
        self.assertEqual(content["total_files"], 5)

    def test_project_info_on_empty_directory_returns_zeroed_counters(self):
        with tempfile.TemporaryDirectory() as empty_dir:
            context = make_context(project_root=Path(empty_dir), initialized=True)
            request = {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {"name": "project_info", "arguments": {}},
            }

            response = dispatch(request, context)

            content = response["result"]["structuredContent"]
            self.assertEqual(content["total_files"], 0)
            self.assertEqual(content["total_lines"], 0)
            self.assertEqual(content["manifests_present"], [])

    def test_project_info_ignores_git_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
            (root / "real.py").write_text("x = 1\n")

            context = make_context(project_root=root, initialized=True)
            request = {
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {"name": "project_info", "arguments": {}},
            }

            response = dispatch(request, context)

            content = response["result"]["structuredContent"]
            self.assertEqual(content["total_files"], 1)
            self.assertEqual(content["files_by_extension"], {".py": 1})

    def test_project_info_missing_root_returns_internal_error_without_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "will_be_deleted"
            root.mkdir()
            context = make_context(project_root=root, initialized=True)
            shutil.rmtree(root)

            request = {
                "jsonrpc": "2.0",
                "id": 13,
                "method": "tools/call",
                "params": {"name": "project_info", "arguments": {}},
            }

            response = dispatch(request, context)

            self.assertEqual(response["error"]["code"], -32603)
            self.assertNotIn(str(root), response["error"]["message"])

    def test_list_files_returns_exact_result_for_fixture(self):
        context = make_context(project_root=FIXTURE_ROOT, initialized=True)
        request = {
            "jsonrpc": "2.0",
            "id": 80,
            "method": "tools/call",
            "params": {"name": "list_files", "arguments": {}},
        }

        response = dispatch(request, context)

        content = response["result"]["structuredContent"]
        self.assertEqual(
            content["files"],
            ["app.js", "data.bin", "main.py", "nested/util.py", "package.json"],
        )
        self.assertEqual(content["total_files"], 5)
        self.assertFalse(content["scan_truncated"])
        self.assertEqual(content["unreadable_entries_skipped"], 0)
        self.assertFalse(content["gitignore_applied"])
        self.assertEqual(content["scope_limitations"], [])

    def test_list_files_wraps_result_in_call_tool_result_envelope(self):
        context = make_context(project_root=FIXTURE_ROOT, initialized=True)
        request = {
            "jsonrpc": "2.0",
            "id": 81,
            "method": "tools/call",
            "params": {"name": "list_files", "arguments": {}},
        }

        response = dispatch(request, context)

        result = response["result"]
        self.assertIn("content", result)
        self.assertEqual(result["content"][0]["type"], "text")
        parsed_text = json.loads(result["content"][0]["text"])
        self.assertEqual(parsed_text, result["structuredContent"])
        self.assertFalse(result["isError"])

    def test_list_files_missing_root_returns_internal_error_without_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "will_be_deleted"
            root.mkdir()
            context = make_context(project_root=root, initialized=True)
            shutil.rmtree(root)

            request = {
                "jsonrpc": "2.0",
                "id": 82,
                "method": "tools/call",
                "params": {"name": "list_files", "arguments": {}},
            }

            response = dispatch(request, context)

            self.assertEqual(response["error"]["code"], -32603)
            self.assertNotIn(str(root), response["error"]["message"])

    def test_read_file_returns_exact_content_for_fixture_file(self):
        context = make_context(project_root=FIXTURE_ROOT, initialized=True)
        request = {
            "jsonrpc": "2.0",
            "id": 90,
            "method": "tools/call",
            "params": {"name": "read_file", "arguments": {"relative_path": "main.py"}},
        }

        response = dispatch(request, context)

        content = response["result"]["structuredContent"]
        self.assertEqual(content["content"], (FIXTURE_ROOT / "main.py").read_text())
        self.assertFalse(content["truncated"])

    def test_read_file_wraps_result_in_call_tool_result_envelope(self):
        context = make_context(project_root=FIXTURE_ROOT, initialized=True)
        request = {
            "jsonrpc": "2.0",
            "id": 91,
            "method": "tools/call",
            "params": {"name": "read_file", "arguments": {"relative_path": "main.py"}},
        }

        response = dispatch(request, context)

        result = response["result"]
        self.assertIn("content", result)
        self.assertEqual(result["content"][0]["type"], "text")
        parsed_text = json.loads(result["content"][0]["text"])
        self.assertEqual(parsed_text, result["structuredContent"])
        self.assertFalse(result["isError"])

    def test_read_file_missing_argument_returns_structured_error(self):
        context = make_context(project_root=FIXTURE_ROOT, initialized=True)
        request = {
            "jsonrpc": "2.0",
            "id": 92,
            "method": "tools/call",
            "params": {"name": "read_file", "arguments": {}},
        }

        response = dispatch(request, context)

        self.assertEqual(response["error"]["code"], -32603)

    def test_read_file_invalid_argument_type_returns_structured_error(self):
        context = make_context(project_root=FIXTURE_ROOT, initialized=True)
        request = {
            "jsonrpc": "2.0",
            "id": 93,
            "method": "tools/call",
            "params": {"name": "read_file", "arguments": {"relative_path": 123}},
        }

        response = dispatch(request, context)

        self.assertEqual(response["error"]["code"], -32603)


class TestProjectInfoDegradesOnUnreadableEntries(unittest.TestCase):
    """Uma árvore arbitrária tem entradas ilegíveis com frequência (symlink
    pendurado, permissão, socket, corrida com watcher/build). Uma tool de
    inventário deve contabilizar e seguir, nunca abortar por uma entrada.
    """

    def _call_project_info(self, root, request_id):
        context = make_context(project_root=root, initialized=True)
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": "project_info", "arguments": {}},
        }
        return dispatch(request, context)

    def test_broken_symlink_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "real.py").write_text("x = 1\n")
            (root / "broken_link.py").symlink_to(root / "does_not_exist.py")

            response = self._call_project_info(root, 60)

            content = response["result"]["structuredContent"]
            self.assertEqual(content["total_files"], 2)
            self.assertEqual(content["unreadable_entries_skipped"], 1)

    def test_unreadable_subdirectory_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "real.py").write_text("x = 1\n")
            locked = root / "locked"
            locked.mkdir()
            (locked / "hidden.py").write_text("y = 2\n")
            os.chmod(locked, 0o000)

            try:
                response = self._call_project_info(root, 61)
            finally:
                os.chmod(locked, 0o755)

            content = response["result"]["structuredContent"]
            self.assertEqual(content["total_files"], 1)
            self.assertEqual(content["unreadable_entries_skipped"], 1)

    def test_unreadable_file_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "real.py").write_text("x = 1\n")
            locked_file = root / "locked.py"
            locked_file.write_text("y = 2\n")
            os.chmod(locked_file, 0o000)

            try:
                response = self._call_project_info(root, 62)
            finally:
                os.chmod(locked_file, 0o644)

            content = response["result"]["structuredContent"]
            self.assertEqual(content["total_files"], 2)
            self.assertEqual(content["unreadable_entries_skipped"], 1)

    def test_unix_socket_in_tree_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "real.py").write_text("x = 1\n")
            sock_path = root / "s.sock"
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.bind(str(sock_path))
                response = self._call_project_info(root, 63)
            finally:
                sock.close()

            content = response["result"]["structuredContent"]
            self.assertEqual(content["total_files"], 2)
            self.assertEqual(content["unreadable_entries_skipped"], 1)


class TestServeStdio(unittest.TestCase):

    def test_malformed_line_then_valid_line_both_handled(self):
        context = make_context(initialized=True)
        valid_request = {"jsonrpc": "2.0", "id": 20, "method": "tools/list"}
        input_stream = io.StringIO("not-json\n" + json.dumps(valid_request) + "\n")
        output_stream = io.StringIO()

        serve_stdio(input_stream, output_stream, context)

        lines = [line for line in output_stream.getvalue().splitlines() if line]
        self.assertEqual(len(lines), 2)

        first = json.loads(lines[0])
        self.assertEqual(first["error"]["code"], -32700)
        self.assertIsNone(first["id"])

        second = json.loads(lines[1])
        self.assertEqual(second["id"], 20)
        self.assertIn("result", second)

    def test_notification_writes_nothing(self):
        context = make_context(initialized=True)
        notification = {"jsonrpc": "2.0", "method": "tools/list"}
        input_stream = io.StringIO(json.dumps(notification) + "\n")
        output_stream = io.StringIO()

        serve_stdio(input_stream, output_stream, context)

        self.assertEqual(output_stream.getvalue(), "")

    def test_unexpected_exception_in_handler_is_caught_and_loop_continues(self):
        context = make_context(initialized=True)
        broken_request = {
            "jsonrpc": "2.0",
            "id": 21,
            "method": "tools/call",
            "params": {"name": "project_info", "arguments": {}},
        }
        # `roots["default"]` como None quebra o handler com TypeError (não é
        # OSError/PermissionError, logo não vira ToolError) — exercita o
        # `except Exception:` de serve_stdio, o único ponto de captura ampla.
        context["roots"]["default"] = None
        next_request = {"jsonrpc": "2.0", "id": 22, "method": "tools/list"}
        input_stream = io.StringIO(
            json.dumps(broken_request) + "\n" + json.dumps(next_request) + "\n"
        )
        output_stream = io.StringIO()

        with self.assertLogs(level="ERROR"):
            serve_stdio(input_stream, output_stream, context)

        lines = [line for line in output_stream.getvalue().splitlines() if line]
        self.assertEqual(len(lines), 2)

        first = json.loads(lines[0])
        self.assertEqual(first["error"]["code"], -32603)

        second = json.loads(lines[1])
        self.assertEqual(second["id"], 22)
        self.assertIn("result", second)


class _RecordingStream(io.StringIO):
    """Espiona a ordem de chamadas de `write`/`flush`.

    `io.StringIO` não distingue um stream com `flush()` explícito de um sem
    — só um espião como este evidencia a chamada (Risks do plano: sem
    `flush()`, um pipe real pode reter a resposta até o processo morrer).
    """

    def __init__(self):
        super().__init__()
        self.calls = []

    def write(self, data):
        self.calls.append("write")
        return super().write(data)

    def flush(self):
        self.calls.append("flush")
        return super().flush()


class TestServeStdioFlushing(unittest.TestCase):

    def test_flushes_after_every_response(self):
        context = make_context(initialized=True)
        first = {"jsonrpc": "2.0", "id": 50, "method": "tools/list"}
        second = {"jsonrpc": "2.0", "id": 51, "method": "tools/list"}
        input_stream = io.StringIO(json.dumps(first) + "\n" + json.dumps(second) + "\n")
        output_stream = _RecordingStream()

        serve_stdio(input_stream, output_stream, context)

        self.assertEqual(output_stream.calls, ["write", "flush", "write", "flush"])


if __name__ == "__main__":
    unittest.main()
