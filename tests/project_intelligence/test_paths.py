import tempfile
import unittest
from pathlib import Path

from ai_dev_lab.project_intelligence.errors import ToolError
from ai_dev_lab.project_intelligence.paths import resolve_within


class ResolveWithinTests(unittest.TestCase):

    def test_allows_file_inside_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            result = resolve_within(root, "src/index.js")

            self.assertEqual(result, root.resolve() / "src/index.js")

    def test_allows_parent_reference_that_stays_inside(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            result = resolve_within(root, "src/../tests/test.py")

            self.assertEqual(result, root.resolve() / "tests/test.py")

    def test_rejects_path_outside_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            with self.assertRaises(ToolError):
                resolve_within(root, "../../etc/passwd")

    def test_rejects_absolute_path_even_when_inside_project_root(self):
        # `root / absoluto` descarta `root` (comportamento do pathlib) — sem
        # esta checagem independente, um caminho absoluto que caia dentro da
        # raiz passaria pelo containment check por acidente.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            absolute_but_inside = str(root / "src/index.js")

            with self.assertRaises(ToolError):
                resolve_within(root, absolute_but_inside)

    def test_rejects_symlink_pointing_outside_project_root(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            root = Path(tmp)
            outside_target = Path(other) / "secret.txt"
            outside_target.write_text("segredo\n")
            (root / "escape.txt").symlink_to(outside_target)

            with self.assertRaises(ToolError):
                resolve_within(root, "escape.txt")

    def test_resolves_symlink_to_its_real_path_when_inside_project_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_file = root / "real.txt"
            real_file.write_text("conteudo\n")
            link = root / "link.txt"
            link.symlink_to(real_file)

            result = resolve_within(root, "link.txt")

            self.assertEqual(result, real_file.resolve())


if __name__ == "__main__":
    unittest.main()
