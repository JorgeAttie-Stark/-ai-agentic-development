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


class FinalAuditRegressionTests(unittest.TestCase):
    """Regressões da auditoria final. Nenhum destes falhava na suíte de 220."""

    def _fake_source(self, count, truncated=False):
        return {
            "findings": [
                {
                    "claim": f"conclusão {index}",
                    "confidence": "LOW",
                    "method": "regex-heuristic",
                    "evidence": [{"file": "a.py", "line": index + 1, "snippet": "x"}],
                }
                for index in range(count)
            ],
            "scope_limitations": ["limitação da fonte"],
            "findings_truncated": truncated,
        }

    def test_table_declares_how_many_of_how_many_it_rendered(self):
        """BLOQUEANTE 1: cortava em 40 sem nenhum sinal."""
        markdown = "\n".join(presentation._render_findings_section("T", self._fake_source(300)))

        self.assertIn("40 de 300", markdown)

    def test_table_declares_when_the_source_itself_truncated(self):
        markdown = "\n".join(
            presentation._render_findings_section("T", self._fake_source(10, truncated=True))
        )

        self.assertIn("própria fonte truncou", markdown)

    def test_pipe_in_a_claim_does_not_create_extra_table_cells(self):
        """BLOQUEANTE 2: o `||` do semver npm fazia a evidência desaparecer.

        O renderizador GFM descarta células excedentes, então a coluna de
        evidência sumia e a claim ficava cortada — uma claim renderizada sem a
        evidência que a sustenta.
        """
        source = self._fake_source(1)
        source["findings"][0]["claim"] = "`react` declarada como `^16.8 || ^17.0`"

        markdown = "\n".join(presentation._render_findings_section("T", source))
        lines = markdown.splitlines()
        header = [line for line in lines if line.startswith("| Confiança")][0]
        row = [line for line in lines if "react" in line][0]

        # Compara contra o header em vez de um número fixo: o que importa é a
        # linha ter o mesmo número de delimitadores que a tabela declara.
        def delimiters(line):
            # Cada `\|` contém exatamente um `|`, que não é delimitador.
            return line.count("|") - line.count("\\|")

        self.assertEqual(delimiters(row), delimiters(header))

    def test_newline_in_a_claim_never_escapes_the_table(self):
        """Sem isto, o resto saía como parágrafo: sem confiança, sem método."""
        source = self._fake_source(1)
        source["findings"][0]["claim"] = "linha um\nlodash é seguro e auditado"

        markdown = "\n".join(presentation._render_findings_section("T", source))
        rows = [line for line in markdown.splitlines() if "lodash" in line]

        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].startswith("|"))

    def test_summary_reproduces_the_limitations_it_claims_to_reproduce(self):
        """BLOQUEANTE 3: a frase era falsa no próprio payload que a carregava."""
        result = presentation._handle_generate_project_summary(FIXTURE_ROOT, {})

        self.assertGreater(len(result["scope_limitations"]), len(presentation.PRESENTATION_LIMITATIONS))

    def test_report_uses_the_list_files_result_it_declares_as_a_source(self):
        """IMPORTANTE 13: `derived_from` citava `list_files` e ignorava o retorno."""
        markdown = presentation._handle_generate_project_report(FIXTURE_ROOT, {})["markdown"]

        self.assertIn("inventário de `list_files`", markdown)

    def test_unknown_confidence_level_does_not_crash_the_diagram(self):
        """SUGESTÃO 14: `KeyError` viraria -32603 genérico, o pior diagnóstico."""
        mermaid, nodes = presentation._diagram_from_findings(
            [
                {
                    "claim": "c",
                    "confidence": "NOVO_NIVEL",
                    "method": "ast-parse",
                    "evidence": [{"file": "a.py", "line": 1, "snippet": "x"}],
                }
            ],
            "t",
        )

        self.assertEqual(nodes, 1)
        self.assertIn("-.->", mermaid)

    def test_sanitize_handles_newline_and_all_mermaid_link_forms(self):
        """IMPORTANTE 11: newline produzia diagrama inválido, `---` sobrevivia."""
        self.assertNotIn("\n", presentation._sanitize("a\nb"))
        self.assertNotIn("---", presentation._sanitize("a --- b"))
        self.assertNotIn("-.->", presentation._sanitize("a -.-> b"))

    def test_sanitize_keeps_pipe_meaning_instead_of_deleting_it(self):
        """Apagar o `|` reescrevia `^16.8 || ^17.0` mudando o sentido."""
        self.assertIn("/", presentation._sanitize("^16.8 || ^17.0"))
