import tempfile
import unittest
from pathlib import Path

from ai_dev_lab.project_intelligence.config import (
    ConfigError,
    build_context,
    resolve_allowed_parents,
)
from ai_dev_lab.project_intelligence.errors import ToolError
from ai_dev_lab.project_intelligence.paths import resolve_requested_root
from ai_dev_lab.project_intelligence.protocol import dispatch
from ai_dev_lab.project_intelligence.registry import TOOL_REGISTRY


def _repository(path):
    """Cria um diretório que passa pela porta de repositório."""
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()
    return path


class AllowedParentsConfigTests(unittest.TestCase):

    def test_no_allow_parent_means_only_the_default_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(resolve_allowed_parents([], Path(tmp)), [])

    def test_allow_parent_is_repeatable(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            parents = resolve_allowed_parents(["--allow-parent", a, "--allow-parent", b], Path(a))

            self.assertEqual(len(parents), 2)

    def test_allow_parent_that_does_not_exist_is_a_config_error(self):
        with self.assertRaises(ConfigError):
            resolve_allowed_parents(["--allow-parent", "/nao/existe/xyz"], Path("/tmp"))

    def test_allow_parent_that_is_a_file_is_a_config_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "f.txt"
            target.write_text("x\n")

            with self.assertRaises(ConfigError):
                resolve_allowed_parents(["--allow-parent", str(target)], Path(tmp))

    def test_context_carries_the_allowed_parents(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = build_context(Path(tmp), [Path(tmp)])

            self.assertEqual(context["allowed_parents"], [Path(tmp)])


class RequestedRootConfinementTests(unittest.TestCase):
    """`read_file` devolve conteúdo de arquivo. Esta é a fronteira."""

    def _context(self, default, parents):
        return build_context(default, parents)

    def test_no_root_argument_uses_the_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()

            self.assertEqual(resolve_requested_root(self._context(root, []), None), root)

    def test_root_under_an_allowed_parent_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()
            _repository(parent / "repo")

            resolved = resolve_requested_root(
                self._context(parent, [parent]), str(parent / "repo")
            )

            self.assertEqual(resolved, parent / "repo")

    def test_root_outside_every_allowed_parent_is_refused(self):
        with tempfile.TemporaryDirectory() as allowed, tempfile.TemporaryDirectory() as outside:
            context = self._context(Path(allowed).resolve(), [Path(allowed).resolve()])

            with self.assertRaises(ToolError):
                resolve_requested_root(context, outside)

    def test_the_default_root_is_always_reachable_even_without_a_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()

            self.assertEqual(resolve_requested_root(self._context(root, []), str(root)), root)

    def test_symlink_escaping_an_allowed_parent_is_refused(self):
        with tempfile.TemporaryDirectory() as allowed, tempfile.TemporaryDirectory() as outside:
            parent = Path(allowed).resolve()
            (parent / "escape").symlink_to(outside)

            with self.assertRaises(ToolError):
                resolve_requested_root(self._context(parent, [parent]), str(parent / "escape"))

    def test_parent_traversal_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()
            (parent / "repo").mkdir()

            with self.assertRaises(ToolError):
                resolve_requested_root(
                    self._context(parent, [parent]), str(parent / "repo" / ".." / ".." / "..")
                )

    def test_root_that_is_not_a_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()
            (parent / "f.txt").write_text("x\n")

            with self.assertRaises(ToolError):
                resolve_requested_root(self._context(parent, [parent]), str(parent / "f.txt"))

    def test_tilde_in_a_requested_root_is_expanded(self):
        home = Path.home().resolve()
        context = self._context(home, [home])

        self.assertEqual(resolve_requested_root(context, "~"), home)

    def test_error_message_never_leaks_the_allowed_parents(self):
        with tempfile.TemporaryDirectory() as allowed, tempfile.TemporaryDirectory() as outside:
            parent = Path(allowed).resolve()
            try:
                resolve_requested_root(self._context(parent, [parent]), outside)
            except ToolError as error:
                self.assertNotIn(str(parent), str(error))


class EveryToolAcceptsARootArgumentTests(unittest.TestCase):
    """A costura previa isto: os 18 handlers não mudam, só o schema e o dispatch."""

    def test_every_tool_declares_the_optional_root_property(self):
        for name, spec in TOOL_REGISTRY.items():
            with self.subTest(tool=name):
                properties = spec["input_schema"]["properties"]
                self.assertIn("root", properties)
                self.assertNotIn("root", spec["input_schema"].get("required", []))

    def test_tools_call_honours_the_root_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()
            _repository(parent / "other")
            (parent / "other" / "only_here.py").write_text("x = 1\n")
            (parent / "default").mkdir()

            context = build_context(parent / "default", [parent])
            context["initialized"] = True

            response = dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "list_files", "arguments": {"root": str(parent / "other")}},
                },
                context,
            )

            files = response["result"]["structuredContent"]["files"]
            self.assertEqual(files, ["only_here.py"])

    def test_tools_call_without_root_still_uses_the_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()
            (parent / "default").mkdir()
            (parent / "default" / "in_default.py").write_text("x = 1\n")

            context = build_context(parent / "default", [parent])
            context["initialized"] = True

            response = dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "list_files", "arguments": {}},
                },
                context,
            )

            self.assertEqual(
                response["result"]["structuredContent"]["files"], ["in_default.py"]
            )

    def test_root_outside_the_allowance_becomes_a_structured_error(self):
        with tempfile.TemporaryDirectory() as allowed, tempfile.TemporaryDirectory() as outside:
            context = build_context(Path(allowed).resolve(), [Path(allowed).resolve()])
            context["initialized"] = True

            response = dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "read_file", "arguments": {"root": outside,
                                                                  "relative_path": "x"}},
                },
                context,
            )

            self.assertTrue(response["result"]["isError"])


class RootMustBeARepositoryTests(unittest.TestCase):
    """"Qualquer repo que eu tenha acesso" é mais estreito que "qualquer arquivo".

    Um `--allow-parent $HOME` alcança `~/.ssh`, `~/.config/gh` e
    `~/.zsh_history`, e `read_file` é uma das tools. A porta de repositório
    faz o alcance coincidir com o pedido: `.git` presente ou nada.
    """

    def _context(self, default, parents):
        return build_context(default, parents)

    def test_directory_without_a_git_entry_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()
            (parent / ".ssh").mkdir()
            (parent / ".ssh" / "id_rsa").write_text("CHAVE PRIVADA\n")

            with self.assertRaises(ToolError):
                resolve_requested_root(self._context(parent, [parent]), str(parent / ".ssh"))

    def test_directory_with_a_git_directory_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()
            _repository(parent / "repo")

            resolved = resolve_requested_root(
                self._context(parent, [parent]), str(parent / "repo")
            )

            self.assertEqual(resolved, parent / "repo")

    def test_git_as_a_file_is_accepted_because_worktrees_look_like_that(self):
        """Worktree e submódulo têm `.git` como arquivo, não diretório."""
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()
            (parent / "wt").mkdir()
            (parent / "wt" / ".git").write_text("gitdir: /outro/lugar\n")

            resolved = resolve_requested_root(self._context(parent, [parent]), str(parent / "wt"))

            self.assertEqual(resolved, parent / "wt")

    def test_the_default_root_is_exempt_because_the_operator_named_it(self):
        """`--root` é decisão explícita de quem sobe o servidor, não do cliente."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()

            self.assertEqual(resolve_requested_root(self._context(root, []), str(root)), root)
            self.assertEqual(resolve_requested_root(self._context(root, []), None), root)

    def test_refusal_explains_the_repository_requirement(self):
        """Sem a razão, o cliente tenta o mesmo caminho de novo."""
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()
            (parent / "qualquer").mkdir()

            try:
                resolve_requested_root(self._context(parent, [parent]), str(parent / "qualquer"))
            except ToolError as error:
                self.assertIn("repositório", str(error).lower())

    def test_relative_root_is_told_to_use_an_absolute_path(self):
        """O cliente real mandou `app-web` e ouviu "não é um diretório"."""
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()

            with self.assertRaises(ToolError) as caught:
                resolve_requested_root(self._context(parent, [parent]), "app-web")

            self.assertIn("absoluto", str(caught.exception).lower())


class RepositoryDiscoveryTests(unittest.TestCase):
    """Sem descoberta, usar outra raiz depende do humano digitar o caminho.

    Foi o que travou o primeiro teste real: o cliente pediu "me passa o
    caminho absoluto do app-web" porque não tinha como saber.
    """

    def _call(self, default, parents):
        context = build_context(default, parents)
        context["initialized"] = True
        response = dispatch(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "list_repositories", "arguments": {}},
            },
            context,
        )
        return response["result"]["structuredContent"]

    def test_lists_a_repository_under_an_allowed_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()
            _repository(parent / "app-web")

            paths = [entry["path"] for entry in self._call(parent, [parent])["repositories"]]

            self.assertIn(str(parent / "app-web"), paths)

    def test_does_not_list_a_directory_that_is_not_a_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()
            (parent / ".ssh").mkdir()
            _repository(parent / "repo")

            names = [entry["name"] for entry in self._call(parent, [parent])["repositories"]]

            self.assertEqual(names, ["repo"])

    def test_does_not_descend_into_a_repository_it_already_found(self):
        """`node_modules` vendorizado tem `.git` dentro e não é repo do humano."""
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()
            _repository(parent / "outer")
            _repository(parent / "outer" / "node_modules" / "dep")

            names = [entry["name"] for entry in self._call(parent, [parent])["repositories"]]

            self.assertEqual(names, ["outer"])

    def test_finds_a_repository_nested_below_the_parent(self):
        """O app-web real está em `~/Desktop/Projects/app-web`, não em `~`."""
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()
            _repository(parent / "Desktop" / "Projects" / "app-web")

            names = [entry["name"] for entry in self._call(parent, [parent])["repositories"]]

            self.assertIn("app-web", names)

    def test_declares_what_it_searched_and_its_depth_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()

            result = self._call(parent, [parent])

            self.assertIn(str(parent), result["searched"])
            self.assertTrue(result["scope_limitations"])

    def test_emits_no_findings_because_it_concludes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()

            self.assertNotIn("findings", self._call(parent, [parent]))

    def test_the_default_root_is_listed_even_without_an_allowed_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _repository(Path(tmp).resolve() / "solo")

            paths = [entry["path"] for entry in self._call(root, [])["repositories"]]

            self.assertEqual(paths, [str(root)])


class ToolErrorsBelongInTheResultTests(unittest.TestCase):
    """A spec MCP separa erro de protocolo de erro de execução de tool.

    `-32603` é *Internal error*: o Claude Desktop mostrou "uma ferramenta
    falhou" para um argumento inválido, que lê como servidor quebrado.
    """

    def _dispatch(self, name, arguments, default, parents):
        context = build_context(default, parents)
        context["initialized"] = True
        return dispatch(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": name, "arguments": arguments}},
            context,
        )

    def test_a_tool_error_is_a_result_not_a_protocol_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()

            response = self._dispatch("project_info", {"root": "app-web"}, parent, [parent])

            self.assertNotIn("error", response)
            self.assertTrue(response["result"]["isError"])

    def test_the_reason_reaches_the_model_in_the_content_block(self):
        """`structuredContent` é opcional para o cliente; `content` é o que o modelo lê."""
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()

            response = self._dispatch("project_info", {"root": "app-web"}, parent, [parent])
            text = response["result"]["content"][0]["text"]

            self.assertIn("absoluto", text.lower())

    def test_a_successful_call_still_reports_isError_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()

            response = self._dispatch("project_info", {}, root, [])

            self.assertFalse(response["result"]["isError"])

    def test_an_unknown_tool_stays_a_protocol_error(self):
        """Aí a requisição em si é inválida — o protocolo é o lugar certo."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()

            response = self._dispatch("inventada", {}, root, [])

            self.assertEqual(response["error"]["code"], -32602)
