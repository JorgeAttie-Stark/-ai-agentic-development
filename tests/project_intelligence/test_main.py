import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stderr
from unittest.mock import patch

from ai_dev_lab.project_intelligence import __main__ as main_module
from ai_dev_lab.project_intelligence import protocol
from ai_dev_lab.project_intelligence.__main__ import main


class TestMainEntrypoint(unittest.TestCase):

    def test_config_error_exits_with_status_one_and_never_starts_server(self):
        # `main()` é a única casca que traduz `ConfigError` em processo
        # encerrado — sem este teste, o handoff de config.py para o loop
        # stdio fica sem evidência (DoD item 1: __main__.py existe e faz
        # essa amarração).
        missing_root = "/no/such/directory/for/ai-dev-lab-tests"
        stderr = io.StringIO()

        with tempfile.TemporaryDirectory() as cwd:
            argv = ["project-intelligence", "--root", missing_root]
            with patch.object(sys, "argv", argv), \
                 patch("os.getcwd", return_value=cwd), \
                 patch.object(protocol, "serve_stdio") as mock_serve, \
                 redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as ctx:
                    main_module.main()

        self.assertEqual(ctx.exception.code, 1)
        mock_serve.assert_not_called()
        self.assertIn("project-intelligence:", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()


class MainHappyPathTests(unittest.TestCase):
    """O caminho de sucesso do entrypoint não tinha cobertura nenhuma.

    O único teste que existia forçava `ConfigError`, então saía por `sys.exit`
    antes de chegar a `build_context` — e um `NameError` na linha seguinte
    passou por 256 testes verdes. Um teste que só exercita o caminho de erro
    não cobre a casca.
    """

    def test_starts_the_server_with_a_context_built_from_the_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "repo").mkdir()

            with patch.object(protocol, "serve_stdio") as serve, patch.object(
                sys, "argv", ["prog", "--root", str(root / "repo"), "--allow-parent", str(root)]
            ), patch.object(os, "getcwd", return_value=str(root)):
                main()

            serve.assert_called_once()
            context = serve.call_args[0][2]
            self.assertEqual(context["roots"]["default"], root / "repo")
            self.assertEqual(context["allowed_parents"], [root])
            self.assertFalse(context["initialized"])

    def test_works_without_allow_parent(self):
        """Comportamento anterior preservado: sem `--allow-parent`, só a raiz."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()

            with patch.object(protocol, "serve_stdio") as serve, patch.object(
                sys, "argv", ["prog", "--root", str(root)]
            ), patch.object(os, "getcwd", return_value=str(root)):
                main()

            self.assertEqual(serve.call_args[0][2]["allowed_parents"], [])
