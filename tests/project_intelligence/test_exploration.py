import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_dev_lab.project_intelligence import exploration
from ai_dev_lab.project_intelligence.exploration import _handle_list_files


def _call_list_files(root):
    return _handle_list_files(Path(root), {})


class ListFilesGitPruningTests(unittest.TestCase):

    def test_git_directory_is_always_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
            (root / "real.py").write_text("x = 1\n")

            result = _call_list_files(root)

            self.assertEqual(result["files"], ["real.py"])
            self.assertEqual(result["total_files"], 1)


class ListFilesGitignoreTests(unittest.TestCase):

    def test_missing_gitignore_reports_not_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("x = 1\n")

            result = _call_list_files(root)

            self.assertFalse(result["gitignore_applied"])
            self.assertEqual(result["scope_limitations"], [])

    def test_pattern_without_slash_excludes_at_any_depth(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitignore").write_text("*.log\n")
            (root / "app.py").write_text("x = 1\n")
            (root / "debug.log").write_text("boom\n")
            nested = root / "nested"
            nested.mkdir()
            (nested / "deep.log").write_text("boom\n")

            result = _call_list_files(root)

            self.assertEqual(result["files"], [".gitignore", "app.py"])
            self.assertTrue(result["gitignore_applied"])
            self.assertEqual(result["scope_limitations"], list(exploration.GITIGNORE_SCOPE_LIMITATIONS))

    def test_pattern_with_slash_excludes_only_the_anchored_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitignore").write_text("src/notes.txt\n")
            (root / "notes.txt").write_text("keep\n")
            src = root / "src"
            src.mkdir()
            (src / "notes.txt").write_text("drop\n")
            other = root / "other"
            other.mkdir()
            (other / "notes.txt").write_text("keep too\n")

            result = _call_list_files(root)

            self.assertEqual(result["files"], [".gitignore", "notes.txt", "other/notes.txt"])

    def test_directory_pattern_prunes_subtree_without_visiting_it(self):
        # Prova de que a subárvore não é visitada: se `build/` tivesse sido
        # percorrida, o FIFO dentro dela teria sido contado em
        # `unreadable_entries_skipped` pelo guard de arquivo regular. Como a
        # poda acontece em `dirnames` antes do os.walk descer, a contagem
        # fica em zero.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitignore").write_text("build/\n")
            (root / "app.py").write_text("x = 1\n")
            build = root / "build"
            build.mkdir()
            os.mkfifo(build / "pipe")

            result = _call_list_files(root)

            self.assertEqual(result["files"], [".gitignore", "app.py"])
            self.assertEqual(result["unreadable_entries_skipped"], 0)

    def test_blank_lines_and_comments_have_no_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitignore").write_text("\n# comentário\n\n")
            (root / "app.py").write_text("x = 1\n")

            result = _call_list_files(root)

            self.assertEqual(result["files"], [".gitignore", "app.py"])
            self.assertTrue(result["gitignore_applied"])

    def test_negation_pattern_is_ignored_without_excluding_by_mistake(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitignore").write_text("!keep.py\n")
            (root / "keep.py").write_text("x = 1\n")

            result = _call_list_files(root)

            self.assertEqual(result["files"], [".gitignore", "keep.py"])


class ListFilesCapTests(unittest.TestCase):

    def test_cap_truncates_scan_and_reports_exact_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(5):
                (root / f"file{index}.py").write_text("x = 1\n")

            with patch.object(exploration, "MAX_FILES_SCANNED", 3):
                result = _call_list_files(root)

            self.assertTrue(result["scan_truncated"])
            self.assertEqual(result["total_files"], 3)


class ListFilesDegradesOnUnreadableEntriesTests(unittest.TestCase):

    def test_fifo_without_writer_is_skipped_and_call_returns(self):
        """Regressão do Milestone 0: abrir um FIFO sem writer em modo leitura
        bloqueia o processo indefinidamente. O guard `os.path.isfile` evita
        qualquer `open()` sobre a entrada, então esta chamada precisa
        retornar — se a regressão voltar, este teste trava (timeout do
        runner) em vez de falhar por asserção.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "real.py").write_text("x = 1\n")
            os.mkfifo(root / "pipe")

            result = _call_list_files(root)

            self.assertEqual(result["files"], ["real.py"])
            self.assertEqual(result["unreadable_entries_skipped"], 1)

    def test_unreadable_subdirectory_is_counted_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "real.py").write_text("x = 1\n")
            locked = root / "locked"
            locked.mkdir()
            (locked / "hidden.py").write_text("y = 2\n")
            os.chmod(locked, 0o000)

            try:
                result = _call_list_files(root)
            finally:
                os.chmod(locked, 0o755)

            self.assertEqual(result["files"], ["real.py"])
            self.assertEqual(result["unreadable_entries_skipped"], 1)


class ListFilesEmptyDirectoryTests(unittest.TestCase):

    def test_empty_directory_returns_no_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _call_list_files(Path(tmp))

            self.assertEqual(result["files"], [])
            self.assertEqual(result["total_files"], 0)


if __name__ == "__main__":
    unittest.main()
