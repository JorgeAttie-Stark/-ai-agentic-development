import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from ai_dev_lab.project_intelligence import __main__ as main_module
from ai_dev_lab.project_intelligence import protocol


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
