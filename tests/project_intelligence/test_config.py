import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_dev_lab.project_intelligence.config import ConfigError, build_context, resolve_project_root


class TestResolveProjectRoot(unittest.TestCase):

    def test_defaults_to_cwd_when_no_root_argument(self):
        with tempfile.TemporaryDirectory() as cwd:
            resolved = resolve_project_root([], cwd)
            self.assertEqual(resolved, Path(cwd).resolve())

    def test_rejects_cwd_that_does_not_exist(self):
        missing = "/no/such/directory/for/ai-dev-lab-tests"
        with self.assertRaises(ConfigError):
            resolve_project_root([], missing)

    def test_rejects_cwd_that_is_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "not_a_directory.txt"
            file_path.write_text("content")
            with self.assertRaises(ConfigError):
                resolve_project_root([], str(file_path))

    def test_root_argument_resolves_to_given_path(self):
        with tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryDirectory() as root:
            resolved = resolve_project_root(["--root", root], cwd)
            self.assertEqual(resolved, Path(root).resolve())

    def test_root_argument_takes_precedence_over_cwd(self):
        with tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryDirectory() as root:
            resolved = resolve_project_root(["--root", root], cwd)
            self.assertNotEqual(resolved, Path(cwd).resolve())
            self.assertEqual(resolved, Path(root).resolve())

    def test_rejects_root_argument_that_does_not_exist(self):
        with tempfile.TemporaryDirectory() as cwd:
            missing = "/no/such/directory/for/ai-dev-lab-tests"
            with self.assertRaises(ConfigError):
                resolve_project_root(["--root", missing], cwd)

    def test_rejects_root_argument_that_is_a_file(self):
        with tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "not_a_directory.txt"
            file_path.write_text("content")
            with self.assertRaises(ConfigError):
                resolve_project_root(["--root", str(file_path)], cwd)

    def test_root_argument_expands_tilde(self):
        # Regressão: `Path(cwd, raw_root).expanduser()` nunca expande, porque
        # depois do join o primeiro componente do path deixa de ser `~`.
        # `--root ~/projeto` é exatamente o formato que o Claude Desktop
        # escreve em `claude_desktop_config.json`, sem shell para expandir.
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as cwd:
            target = Path(home) / "meu_projeto"
            target.mkdir()
            with patch.dict(os.environ, {"HOME": home}):
                resolved = resolve_project_root(["--root", "~/meu_projeto"], cwd)
            self.assertEqual(resolved, target.resolve())

    def test_root_argument_with_nonexistent_user_raises_config_error(self):
        # Regressão: `Path.expanduser()` levanta `RuntimeError` (não
        # `ConfigError`) quando `~usuario` não corresponde a nenhum usuário
        # do sistema. `--root` vem de `claude_desktop_config.json` escrito à
        # mão, sem shell validando nada — um typo aqui não pode escapar como
        # traceback cru; tem que virar a mesma mensagem de operador das
        # outras falhas de configuração.
        with tempfile.TemporaryDirectory() as cwd:
            with self.assertRaises(ConfigError):
                resolve_project_root(["--root", "~usuario_inexistente_zz/projeto"], cwd)

    def test_relative_root_argument_resolves_to_absolute(self):
        with tempfile.TemporaryDirectory() as cwd:
            nested = Path(cwd) / "nested_target"
            nested.mkdir()
            resolved = resolve_project_root(["--root", "nested_target"], cwd)
            self.assertTrue(resolved.is_absolute())
            self.assertEqual(resolved, nested.resolve())


class TestBuildContext(unittest.TestCase):

    def test_context_exposes_root_under_roots_default(self):
        with tempfile.TemporaryDirectory() as root:
            project_root = Path(root).resolve()
            context = build_context(project_root)
            self.assertEqual(context["roots"]["default"], project_root)

    def test_context_starts_uninitialized(self):
        with tempfile.TemporaryDirectory() as root:
            context = build_context(Path(root).resolve())
            self.assertFalse(context["initialized"])


if __name__ == "__main__":
    unittest.main()
