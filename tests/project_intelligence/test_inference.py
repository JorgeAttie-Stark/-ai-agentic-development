import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_dev_lab.project_intelligence import inference
from ai_dev_lab.project_intelligence.findings import validate_finding


def _call_call_graph(root, **kwargs):
    return inference._handle_data_flow_analyzer(Path(root), dict(kwargs))


def _call_business_rules(root, **kwargs):
    return inference._handle_business_rules_analyzer(Path(root), dict(kwargs))


class CallGraphHonestyTests(unittest.TestCase):
    """O plano rescopou esta tool: call graph Python-only, nunca "data flow"."""

    def test_scope_limitations_deny_being_a_data_flow_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _call_call_graph(tmp)

        joined = " ".join(result["scope_limitations"]).lower()
        self.assertIn("não é análise de fluxo de dados", joined)
        self.assertIn("python", joined)

    def test_claim_is_about_the_call_site_not_about_resolution(self):
        """`ast` prova que existe uma chamada chamada X na linha N.

        Não prova a QUAL função ela resolve — o nome pode estar sombreado,
        importado, ou ser método de qualquer objeto. A claim precisa parar no
        que a evidência sustenta.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m.py").write_text("def caller():\n    helper()\n")

            result = _call_call_graph(root)
            claims = " ".join(f["claim"] for f in result["findings"])

            self.assertIn("chama", claims)
            for finding in result["findings"]:
                self.assertNotIn("resolve", finding["claim"].lower())
                self.assertNotIn("definida em", finding["claim"].lower())

    def test_edges_come_from_ast_and_are_high(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m.py").write_text("def a():\n    b()\n\ndef b():\n    pass\n")

            result = _call_call_graph(root)

            self.assertTrue(result["findings"])
            for finding in result["findings"]:
                validate_finding(finding)
                self.assertEqual(finding["method"], "ast-parse")
                self.assertEqual(finding["confidence"], "HIGH")

    def test_evidence_carries_the_real_call_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m.py").write_text("def a():\n    pass\n\n\ndef b():\n    a()\n")

            result = _call_call_graph(root)
            edge = [f for f in result["findings"] if "`b`" in f["claim"]]

            self.assertEqual(edge[0]["evidence"][0]["line"], 6)

    def test_non_python_files_are_reported_as_out_of_scope_not_analyzed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.js").write_text("function f() { g(); }\n")

            result = _call_call_graph(root)

            self.assertEqual(result["findings"], [])
            self.assertEqual(result["python_files_analyzed"], 0)

    def test_unparseable_python_is_counted_not_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "broken.py").write_text("def (((\n")

            result = _call_call_graph(root)

            self.assertEqual(result["findings"], [])
            self.assertEqual(result["files_unparseable"], 1)

    def test_gitignored_trees_are_pruned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitignore").write_text("vendor/\n")
            (root / "vendor").mkdir()
            (root / "vendor" / "dep.py").write_text("def x():\n    y()\n")
            (root / "own.py").write_text("def a():\n    b()\n")

            result = _call_call_graph(root)
            files = {f["evidence"][0]["file"] for f in result["findings"]}

            self.assertEqual(files, {"own.py"})

    def test_truncation_is_flagged_when_a_file_is_skipped_by_the_cap(self):
        """O corte é em fronteira de arquivo, então a flag exige >= 2 arquivos.

        Com um arquivo só, ele termina inteiro e nada foi omitido — `False` é a
        resposta correta, não uma falha. Ver a limitação de arquivo único
        registrada em `CALL_GRAPH_LIMITATIONS`.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = "".join(f"    f{n}()\n" for n in range(10))
            for index in range(3):
                (root / f"m{index}.py").write_text(f"def caller():\n{body}")

            with patch.object(inference, "MAX_FINDINGS", 5):
                result = _call_call_graph(root)

            self.assertTrue(result["findings_truncated"])
            self.assertGreater(result["files_skipped_by_cap"], 0)

    def test_single_large_file_is_never_cut_mid_file(self):
        """Consequência aceita: `MAX_FINDINGS` é piso mole, não teto duro."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = "".join(f"    f{n}()\n" for n in range(30))
            (root / "only.py").write_text(f"def caller():\n{body}")

            with patch.object(inference, "MAX_FINDINGS", 5):
                result = _call_call_graph(root)

            self.assertEqual(len(result["findings"]), 30)
            self.assertFalse(result["findings_truncated"])


class BusinessRulesStructuralImpossibilityTests(unittest.TestCase):
    """O requisito central: a tool NÃO PODE descrever a regra.

    Não é uma instrução no prompt — é ausência de campo onde a descrição
    caberia. Estes testes existem para que essa ausência não seja "consertada"
    por alguém achando que falta informação.
    """

    def test_no_field_in_the_output_could_hold_a_rule_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "billing.py").write_text(
                "def cobrar(valor):\n"
                "    if valor > 1000:\n"
                "        raise ValueError('limite')\n"
            )

            result = _call_business_rules(root)

            self.assertTrue(result["findings"])
            for finding in result["findings"]:
                self.assertEqual(
                    set(finding), {"claim", "confidence", "method", "evidence"}
                )
                for evidence in finding["evidence"]:
                    self.assertEqual(set(evidence), {"file", "line", "snippet"})

    def test_claim_points_at_a_location_and_never_states_a_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "billing.py").write_text(
                "def cobrar(valor):\n"
                "    if valor > 1000:\n"
                "        raise ValueError('limite excedido')\n"
            )

            result = _call_business_rules(root)

            for finding in result["findings"]:
                claim = finding["claim"].lower()
                self.assertIn("candidato", claim)
                # A claim não pode reproduzir o conteúdo da condição: isso
                # seria descrever a regra, não apontar o local.
                self.assertNotIn("1000", claim)
                self.assertNotIn("limite", claim)

    def test_snippet_is_the_literal_source_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = "def cobrar(valor):\n    if valor > 1000:\n        raise ValueError('x')\n"
            (root / "billing.py").write_text(source)

            result = _call_business_rules(root)
            lines = source.splitlines()

            for finding in result["findings"]:
                evidence = finding["evidence"][0]
                self.assertEqual(evidence["snippet"], lines[evidence["line"] - 1].strip())

    def test_confidence_is_always_low(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "billing.py").write_text(
                "def cobrar(valor):\n    if valor > 1000:\n        raise ValueError('x')\n"
            )

            result = _call_business_rules(root)

            self.assertTrue(result["findings"])
            for finding in result["findings"]:
                validate_finding(finding)
                self.assertEqual(finding["confidence"], "LOW")
                self.assertEqual(finding["method"], "regex-heuristic")

    def test_scope_limitations_say_the_tool_does_not_interpret(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _call_business_rules(tmp)

        joined = " ".join(result["scope_limitations"]).lower()
        self.assertIn("não descreve", joined)
        self.assertIn("interpretação", joined)

    def test_code_without_domain_signal_yields_no_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "plain.py").write_text("x = 1\ny = 2\nprint(x + y)\n")

            result = _call_business_rules(root)

            self.assertEqual(result["findings"], [])

    def test_works_on_non_python_files_too(self):
        """Localizar candidato é agnóstico: não depende de parser."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "billing.js").write_text(
                "function charge(amount) {\n  if (amount > 1000) throw new Error('x')\n}\n"
            )

            result = _call_business_rules(root)

            self.assertTrue(result["findings"])
            self.assertEqual(result["findings"][0]["evidence"][0]["file"], "billing.js")

    def test_gitignored_trees_are_pruned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitignore").write_text("vendor/\n")
            (root / "vendor").mkdir()
            (root / "vendor" / "dep.py").write_text(
                "def cobrar(v):\n    if v > 1:\n        raise ValueError('x')\n"
            )

            result = _call_business_rules(root)

            self.assertEqual(result["findings"], [])
