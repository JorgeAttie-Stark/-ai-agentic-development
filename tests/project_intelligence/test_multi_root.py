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
            (parent / "repo").mkdir()

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
            (parent / "other").mkdir()
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

            self.assertIn("error", response)
            self.assertEqual(response["error"]["code"], -32603)
