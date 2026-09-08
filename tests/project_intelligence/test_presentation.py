import tempfile
import unittest
from pathlib import Path

from ai_dev_lab.project_intelligence import presentation
from ai_dev_lab.project_intelligence.errors import ToolError

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "fake_project"


def _mermaid(root, diagram):
    return presentation._handle_generate_mermaid(Path(root), {"diagram": diagram})


class MermaidIsPureSerializationTests(unittest.TestCase):
    """A tool NÃO cria análise. Ela serializa o que outra camada produziu."""

    def test_emits_no_findings_of_its_own(self):
        result = _mermaid(FIXTURE_ROOT, "architecture")

        self.assertNotIn("findings", result)

    def test_declares_which_tool_produced_the_data(self):
        """Rastreabilidade: quem lê o diagrama precisa saber de onde ele veio."""
        result = _mermaid(FIXTURE_ROOT, "architecture")

        self.assertIn("derived_from", result)
        self.assertTrue(result["derived_from"])

    def test_confidence_is_visible_in_the_diagram(self):
        """LOW/MEDIUM tracejado, HIGH sólido — a incerteza precisa aparecer."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "handlers").mkdir()
            (root / "handlers" / "x.py").write_text("x = 1\n")

            result = _mermaid(root, "architecture")

            self.assertIn("-.->", result["mermaid"])

    def test_high_confidence_uses_solid_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m.py").write_text("def a():\n    b()\n")

            result = _mermaid(root, "call_graph")

            self.assertIn("-->", result["mermaid"])
            self.assertNotIn("-.->", result["mermaid"])

    def test_output_starts_with_a_valid_mermaid_header(self):
        for diagram in ("architecture", "dependencies", "call_graph", "security"):
            with self.subTest(diagram=diagram):
                result = _mermaid(FIXTURE_ROOT, diagram)
                self.assertTrue(result["mermaid"].startswith("flowchart"))

    def test_unknown_diagram_type_is_rejected(self):
        with self.assertRaises(ToolError):
            _mermaid(FIXTURE_ROOT, "inventado")

    def test_missing_diagram_argument_is_rejected(self):
        with self.assertRaises(ToolError):
            presentation._handle_generate_mermaid(FIXTURE_ROOT, {})

    def test_node_labels_are_sanitized_against_mermaid_syntax(self):
        """Um nome com `[` ou `"` quebraria o diagrama silenciosamente."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m.py").write_text('def a():\n    obj["key"]()\n')

            result = _mermaid(root, "call_graph")

            for line in result["mermaid"].splitlines()[1:]:
                self.assertLessEqual(line.count('"'), 4)

    def test_empty_source_yields_a_diagram_with_a_declared_empty_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _mermaid(tmp, "call_graph")

            self.assertTrue(result["mermaid"].startswith("flowchart"))
            self.assertEqual(result["nodes"], 0)
            self.assertTrue(result["scope_limitations"])


class DocumentationConsumesNeverConcludesTests(unittest.TestCase):
    """As três tools de documentação renderizam. Não analisam."""

    def test_report_emits_no_findings_of_its_own(self):
        result = presentation._handle_generate_project_report(FIXTURE_ROOT, {})

        self.assertNotIn("findings", result)
        self.assertIn("markdown", result)

    def test_report_declares_every_source_tool(self):
        result = presentation._handle_generate_project_report(FIXTURE_ROOT, {})

        self.assertIn("project_info", result["derived_from"])
        self.assertIn("list_files", result["derived_from"])

    def test_report_carries_confidence_next_to_every_claim(self):
        """Uma claim sem a confiança ao lado vira fato no texto renderizado."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "handlers").mkdir()
            (root / "handlers" / "x.py").write_text("x = 1\n")

            markdown = presentation._handle_generate_project_report(root, {})["markdown"]

            self.assertIn("MEDIUM", markdown)

    def test_report_propagates_scope_limitations_of_the_sources(self):
        markdown = presentation._handle_generate_project_report(FIXTURE_ROOT, {})["markdown"]

        self.assertIn("Limitações", markdown)

    def test_architecture_doc_declares_absence_when_there_is_no_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "zzz").mkdir()
            (root / "zzz" / "x.py").write_text("x = 1\n")

            markdown = presentation._handle_generate_architecture_documentation(root, {})[
                "markdown"
            ]

            self.assertIn("nenhuma evidência", markdown.lower())

    def test_summary_is_shorter_than_the_full_report(self):
        summary = presentation._handle_generate_project_summary(FIXTURE_ROOT, {})["markdown"]
        report = presentation._handle_generate_project_report(FIXTURE_ROOT, {})["markdown"]

        self.assertLess(len(summary), len(report))

    def test_summary_still_declares_its_sources(self):
        result = presentation._handle_generate_project_summary(FIXTURE_ROOT, {})

        self.assertTrue(result["derived_from"])

    def test_no_documentation_tool_invents_a_conclusion_without_source(self):
        """Toda seção do markdown precisa vir de uma tool nomeada."""
        for handler in (
            presentation._handle_generate_project_report,
            presentation._handle_generate_architecture_documentation,
            presentation._handle_generate_project_summary,
        ):
            with self.subTest(handler=handler.__name__):
                result = handler(FIXTURE_ROOT, {})
                self.assertTrue(result["derived_from"])
                self.assertTrue(result["scope_limitations"])
