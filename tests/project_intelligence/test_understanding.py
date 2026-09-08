import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_dev_lab.project_intelligence import understanding
from ai_dev_lab.project_intelligence.errors import ToolError
from ai_dev_lab.project_intelligence.findings import validate_finding

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "fake_project"


def _every_finding_is_valid(test, result):
    test.assertTrue(result["findings"], "esperava ao menos um finding")
    for finding in result["findings"]:
        validate_finding(finding)


class ProjectMapTests(unittest.TestCase):

    def test_returns_tree_of_directories_with_file_counts(self):
        result = understanding._handle_project_map(FIXTURE_ROOT, {})

        self.assertIn("tree", result)
        self.assertEqual(result["tree"]["path"], "")
        self.assertGreater(result["tree"]["file_count"], 0)

    def test_is_factual_and_emits_no_findings(self):
        """`project_map` é estrutura observada, não inferência — sem envelope."""
        result = understanding._handle_project_map(FIXTURE_ROOT, {})

        self.assertNotIn("findings", result)

    def test_nested_directories_appear_as_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a" / "b").mkdir(parents=True)
            (root / "a" / "b" / "x.py").write_text("x\n")

            tree = understanding._handle_project_map(root, {})["tree"]
            self.assertEqual([c["path"] for c in tree["children"]], ["a"])
            self.assertEqual([c["path"] for c in tree["children"][0]["children"]], ["a/b"])

    def test_depth_cap_truncates_and_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a" / "b" / "c").mkdir(parents=True)
            (root / "a" / "b" / "c" / "x.py").write_text("x\n")

            with patch.object(understanding, "MAX_TREE_DEPTH", 1):
                result = understanding._handle_project_map(root, {})

            self.assertTrue(result["tree_truncated"])


class ArchitectureExplainerTests(unittest.TestCase):

    def test_directory_vocabulary_match_is_medium_never_high(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("handlers", "models", "services"):
                (root / name).mkdir()
                (root / name / "x.py").write_text("x\n")

            result = understanding._handle_architecture_explainer(root, {})

            _every_finding_is_valid(self, result)
            for finding in result["findings"]:
                self.assertEqual(finding["confidence"], "MEDIUM")
                self.assertEqual(finding["method"], "name-pattern")

    def test_claim_never_states_the_architecture_as_fact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "handlers").mkdir()
            (root / "handlers" / "x.py").write_text("x\n")

            result = understanding._handle_architecture_explainer(root, {})

            for finding in result["findings"]:
                claim = finding["claim"].lower()
                self.assertIn("sugere", claim)

    def test_no_vocabulary_match_reports_absence_not_a_guess(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "zzz").mkdir()
            (root / "zzz" / "x.py").write_text("x\n")

            result = understanding._handle_architecture_explainer(root, {})

            self.assertEqual(result["findings"], [])
            self.assertTrue(result["scope_limitations"])

    def test_every_finding_points_at_a_real_directory(self):
        result = understanding._handle_architecture_explainer(FIXTURE_ROOT, {})

        for finding in result["findings"]:
            for evidence in finding["evidence"]:
                self.assertTrue((FIXTURE_ROOT / evidence["file"]).exists())


class CodeStructureAnalyzerTests(unittest.TestCase):

    def test_python_uses_ast_and_is_high_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m.py").write_text("import os\n\n\nclass A:\n    def f(self):\n        pass\n")

            result = understanding._handle_code_structure_analyzer(root, {})

            _every_finding_is_valid(self, result)
            methods = {f["method"] for f in result["findings"]}
            self.assertEqual(methods, {"ast-parse"})
            self.assertTrue(all(f["confidence"] == "HIGH" for f in result["findings"]))

    def test_python_findings_carry_the_real_line_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m.py").write_text("\n\nclass Alvo:\n    pass\n")

            result = understanding._handle_code_structure_analyzer(root, {})
            classes = [f for f in result["findings"] if "Alvo" in f["claim"]]

            self.assertEqual(classes[0]["evidence"][0]["line"], 3)

    def test_non_python_uses_heuristic_and_is_low_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.js").write_text("function greet() {}\n")

            result = understanding._handle_code_structure_analyzer(root, {})

            _every_finding_is_valid(self, result)
            self.assertTrue(all(f["method"] == "regex-heuristic" for f in result["findings"]))
            self.assertTrue(all(f["confidence"] == "LOW" for f in result["findings"]))

    def test_unparseable_python_is_reported_not_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "broken.py").write_text("def (((\n")

            result = understanding._handle_code_structure_analyzer(root, {})

            self.assertEqual(result["findings"], [])
            self.assertEqual(result["files_unparseable"], 1)


class DependencyAnalyzerTests(unittest.TestCase):

    def test_package_json_is_manifest_read_and_high(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"dependencies": {"react": "^18.0.0"}}\n')

            result = understanding._handle_dependency_analyzer(root, {})

            _every_finding_is_valid(self, result)
            react = [f for f in result["findings"] if "react" in f["claim"]]
            self.assertEqual(react[0]["method"], "manifest-read")
            self.assertEqual(react[0]["confidence"], "HIGH")

    def test_requirements_txt_is_manifest_read_and_high(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "requirements.txt").write_text("# comentário\nflask==2.0.0\n\n-r outro.txt\n")

            result = understanding._handle_dependency_analyzer(root, {})

            claims = [f["claim"] for f in result["findings"]]
            self.assertTrue(any("flask" in c for c in claims))
            self.assertFalse(any("comentário" in c for c in claims))
            self.assertFalse(any("outro.txt" in c for c in claims))

    def test_pyproject_toml_is_regex_heuristic_and_low(self):
        """Python 3.9 não tem tomllib — extração por regex, confiança LOW."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "x"\ndependencies = ["httpx>=0.24", "click"]\n'
            )

            result = understanding._handle_dependency_analyzer(root, {})

            httpx = [f for f in result["findings"] if "httpx" in f["claim"]]
            self.assertEqual(httpx[0]["method"], "regex-heuristic")
            self.assertEqual(httpx[0]["confidence"], "LOW")

    def test_malformed_json_is_reported_not_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{ not json\n")

            result = understanding._handle_dependency_analyzer(root, {})

            self.assertEqual(result["findings"], [])
            self.assertIn("package.json", result["manifests_unparseable"])

    def test_no_manifest_reports_absence_not_zero_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = understanding._handle_dependency_analyzer(Path(tmp), {})

            self.assertEqual(result["findings"], [])
            self.assertEqual(result["manifests_found"], [])
            self.assertTrue(result["scope_limitations"])

    def test_never_invents_a_dependency_not_in_a_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"dependencies": {"only-this": "1.0.0"}}\n')
            (root / "app.js").write_text("import lodash from 'lodash'\n")

            result = understanding._handle_dependency_analyzer(root, {})
            claims = " ".join(f["claim"] for f in result["findings"])

            self.assertIn("only-this", claims)
            self.assertNotIn("lodash", claims)


class ReviewRegressionTests(unittest.TestCase):
    """Regressões dos achados do reviewer no fechamento do Milestone 2.

    Nenhum destes casos falhava na suíte anterior — todos passavam. É a classe
    de erro que teste não pega sozinho: afirmar mais do que a evidência
    sustenta.
    """

    def test_requirements_url_and_vcs_lines_are_not_dependencies(self):
        """BLOQUEANTE 1: a regex emitia `https` e `git` como pacote, com HIGH."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "requirements.txt").write_text(
                "git+https://github.com/psf/requests.git#egg=requests\n"
                "https://example.com/x.whl\n"
                "./local/pkg\n"
                "-e .\n"
                "flask==2.0\n"
                "httpx[cli]>=0.24\n"
            )

            result = understanding._handle_dependency_analyzer(root, {})
            names = {f["claim"].split("`")[1] for f in result["findings"]}

            self.assertEqual(names, {"flask", "httpx"})
            self.assertEqual(result["lines_unrecognized"], 4)

    def test_architecture_explainer_prunes_gitignored_trees(self):
        """BLOQUEANTE 2: concluía a arquitetura do projeto a partir de node_modules."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitignore").write_text("node_modules/\n")
            (root / "node_modules" / "express" / "lib" / "middlewares").mkdir(parents=True)
            (root / "src" / "services").mkdir(parents=True)

            result = understanding._handle_architecture_explainer(root, {})
            paths = [f["evidence"][0]["file"] for f in result["findings"]]

            self.assertEqual(paths, ["src/services"])
            self.assertTrue(result["gitignore_applied"])
            self.assertEqual(result["directories_matched"], 1)

    def test_architecture_explainer_counts_directories_not_vocabulary_words(self):
        """IMPORTANTE 5: agregava por palavra e descartava evidência disponível."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for parent in ("a", "b", "c"):
                (root / parent / "models").mkdir(parents=True)

            result = understanding._handle_architecture_explainer(root, {})

            self.assertEqual(result["directories_matched"], 3)
            self.assertEqual(len(result["findings"]), 3)

    def test_code_structure_truncation_is_flagged_and_cuts_at_file_boundary(self):
        """BLOQUEANTE 3: truncava em silêncio, e no meio do arquivo."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(3):
                (root / f"m{index}.py").write_text(
                    "".join(f"def f{n}():\n    pass\n" for n in range(5))
                )

            with patch.object(understanding, "MAX_FINDINGS", 6):
                result = understanding._handle_code_structure_analyzer(root, {})

            self.assertTrue(result["findings_truncated"])
            self.assertGreater(result["files_skipped_by_cap"], 0)

            # Nenhum arquivo aparece parcialmente: quem entra, entra inteiro.
            per_file = {}
            for finding in result["findings"]:
                name = finding["evidence"][0]["file"]
                per_file[name] = per_file.get(name, 0) + 1
            self.assertTrue(all(count == 5 for count in per_file.values()))

    def test_python_with_null_byte_beyond_sniff_is_counted_not_fatal(self):
        """BLOQUEANTE 4a: ValueError do ast.parse derrubava a tool inteira."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ok.py").write_text("def alive():\n    pass\n")
            (root / "nul.py").write_bytes(b"#" + b"a" * 9000 + b"\x00rest")

            result = understanding._handle_code_structure_analyzer(root, {})

            self.assertEqual(result["files_unparseable"], 1)
            self.assertTrue(any("alive" in f["claim"] for f in result["findings"]))

    def test_package_json_that_is_not_an_object_is_unparseable_not_fatal(self):
        """BLOQUEANTE 4b: AttributeError do .get num array derrubava a tool."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("[1, 2, 3]\n")

            result = understanding._handle_dependency_analyzer(root, {})

            self.assertEqual(result["manifests_unparseable"], ["package.json"])
            self.assertEqual(result["findings"], [])

    def test_project_map_prunes_gitignored_trees_like_list_files(self):
        """IMPORTANTE 8: duas tools davam "fatos observados" incompatíveis."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitignore").write_text("node_modules/\n")
            (root / "node_modules" / "x").mkdir(parents=True)
            (root / "src").mkdir()

            result = understanding._handle_project_map(root, {})
            paths = {node["path"] for node in result["tree"]["children"]}

            self.assertNotIn("node_modules", paths)
            self.assertTrue(result["gitignore_applied"])

    def test_counters_of_degradation_reach_the_response(self):
        """IMPORTANTE 6: eram calculados e descartados."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ok.py").write_text("def f():\n    pass\n")
            os.mkfifo(root / "pipe.py")

            structure = understanding._handle_code_structure_analyzer(root, {})
            architecture = understanding._handle_architecture_explainer(root, {})

            self.assertIn("unreadable_entries_skipped", structure)
            self.assertIn("unreadable_entries_skipped", architecture)
            self.assertGreaterEqual(structure["unreadable_entries_skipped"], 1)
