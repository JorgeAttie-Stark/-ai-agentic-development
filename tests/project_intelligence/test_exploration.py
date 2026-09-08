import errno
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_dev_lab.project_intelligence import exploration
from ai_dev_lab.project_intelligence.errors import ToolError
from ai_dev_lab.project_intelligence.exploration import _handle_list_files, _handle_read_file

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "fake_project"


def _call_list_files(root):
    return _handle_list_files(Path(root), {})


def _call_read_file(root, relative_path):
    return _handle_read_file(Path(root), {"relative_path": relative_path})


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


class ReadFileTests(unittest.TestCase):

    def test_reads_fixture_file_content(self):
        expected = (FIXTURE_ROOT / "main.py").read_text()

        result = _call_read_file(FIXTURE_ROOT, "main.py")

        self.assertEqual(result["content"], expected)
        self.assertEqual(result["line_count"], len(expected.splitlines()))
        self.assertFalse(result["truncated"])

    def test_rejects_path_outside_project_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            with self.assertRaises(ToolError) as ctx:
                _call_read_file(root, "../../etc/passwd")

            self.assertNotIn(str(root.resolve()), str(ctx.exception))

    def test_rejects_absolute_path_even_when_inside_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "file.txt").write_text("conteudo\n")
            absolute_but_inside = str(root / "file.txt")

            with self.assertRaises(ToolError):
                _call_read_file(root, absolute_but_inside)

    def test_rejects_symlink_escaping_project_root(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            root = Path(tmp)
            outside_target = Path(other) / "secret.txt"
            outside_target.write_text("segredo\n")
            (root / "escape.txt").symlink_to(outside_target)

            with self.assertRaises(ToolError):
                _call_read_file(root, "escape.txt")

    def test_rejects_directory_with_message_distinct_from_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "subdir").mkdir()

            with self.assertRaises(ToolError) as directory_ctx:
                _call_read_file(root, "subdir")
            with self.assertRaises(ToolError) as missing_ctx:
                _call_read_file(root, "does_not_exist.txt")

            self.assertNotEqual(str(directory_ctx.exception), str(missing_ctx.exception))

    def test_rejects_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            with self.assertRaises(ToolError):
                _call_read_file(root, "does_not_exist.txt")

    def test_rejects_non_utf8_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "latin1.txt").write_bytes("café".encode("latin-1"))

            with self.assertRaises(ToolError):
                _call_read_file(root, "latin1.txt")

    def test_rejects_binary_content_with_message_distinct_from_non_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "binary.dat").write_bytes(b"\x00\x01\x02binary")
            (root / "latin1.txt").write_bytes("café".encode("latin-1"))

            with self.assertRaises(ToolError) as binary_ctx:
                _call_read_file(root, "binary.dat")
            with self.assertRaises(ToolError) as non_utf8_ctx:
                _call_read_file(root, "latin1.txt")

            self.assertNotEqual(str(binary_ctx.exception), str(non_utf8_ctx.exception))

    def test_fifo_without_writer_raises_without_blocking(self):
        # Regressão do Milestone 0: o guard `os.path.isfile` evita qualquer
        # `open()` sobre a entrada, então esta chamada precisa retornar — se
        # a regressão voltar, este teste trava (timeout do runner) em vez de
        # falhar por asserção.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            os.mkfifo(root / "pipe")

            with self.assertRaises(ToolError):
                _call_read_file(root, "pipe")

    def test_rejects_missing_relative_path_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ToolError):
                _handle_read_file(Path(tmp), {})

    def test_rejects_non_string_relative_path_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ToolError):
                _handle_read_file(Path(tmp), {"relative_path": 123})

    def test_rejects_empty_relative_path_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ToolError):
                _handle_read_file(Path(tmp), {"relative_path": ""})

    def test_truncates_content_over_max_size_and_flags_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "big.txt").write_bytes(b"a" * 20)

            with patch.object(exploration, "MAX_FILE_SIZE_FOR_READ", 10):
                result = _call_read_file(root, "big.txt")

            self.assertTrue(result["truncated"])
            self.assertEqual(result["content"], "a" * 10)

    def test_line_count_multi_line_and_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "multi.txt").write_text("linha1\nlinha2\nlinha3")
            (root / "empty.txt").write_text("")

            multi_result = _call_read_file(root, "multi.txt")
            empty_result = _call_read_file(root, "empty.txt")

            self.assertEqual(multi_result["line_count"], 3)
            self.assertEqual(empty_result["line_count"], 0)

    def test_permission_denied_raises_without_leaking_absolute_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            locked = root / "locked.txt"
            locked.write_text("segredo\n")
            os.chmod(locked, 0o000)

            try:
                with self.assertRaises(ToolError) as ctx:
                    _call_read_file(root, "locked.txt")
            finally:
                os.chmod(locked, 0o644)

            self.assertNotIn(str(locked.resolve()), str(ctx.exception))
            self.assertNotIn(str(root.resolve()), str(ctx.exception))

    def test_eloop_from_open_is_converted_to_generic_tool_error(self):
        # `O_NOFOLLOW` só levanta `ELOOP` se o componente final virar symlink
        # entre `resolve_within` e `os.open` — corrida genuína, não
        # reproduzível sem flakiness. Este teste prova a conversão feita
        # pelo código (`OSError` -> `ToolError` genérico), não a corrida real.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "file.txt").write_text("conteudo\n")

            with patch(
                "os.open",
                side_effect=OSError(errno.ELOOP, "Too many levels of symbolic links"),
            ):
                with self.assertRaises(ToolError) as ctx:
                    _call_read_file(root, "file.txt")

            self.assertNotIn(str(root.resolve()), str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
