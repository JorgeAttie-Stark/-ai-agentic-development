import tempfile
import unittest
from pathlib import Path

from ai_dev_lab.project_intelligence.paths import resolve_within


class ResolveWithinTests(unittest.TestCase):

    def test_allows_file_inside_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            result = resolve_within(root, "src/index.js")

            self.assertEqual(result, root / "src/index.js")

    def test_allows_parent_reference_that_stays_inside(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            result = resolve_within(root, "src/../tests/test.py")

            self.assertEqual(result, root / "tests/test.py")

    def test_rejects_path_outside_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            with self.assertRaises(ValueError):
                resolve_within(root, "../../etc/passwd")