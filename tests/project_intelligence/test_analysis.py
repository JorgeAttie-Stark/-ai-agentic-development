import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_dev_lab.project_intelligence import analysis
from ai_dev_lab.project_intelligence.findings import validate_finding


def _security(root):
    return analysis._handle_security_analyzer(Path(root), {})


def _improvement(root):
    return analysis._handle_improvement_analyzer(Path(root), {})


def _tests(root):
    return analysis._handle_test_analyzer(Path(root), {})


class SecurityNeverClaimsConfirmedVulnerabilityTests(unittest.TestCase):
    """O plano é explícito: v1 é detecção de PADRÃO, não vulnerabilidade."""

    def test_claim_says_pattern_not_vulnerability(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("eval(user_input)\n")

            result = _security(root)

            self.assertTrue(result["findings"])
            for finding in result["findings"]:
                claim = finding["claim"].lower()
                self.assertIn("padrão", claim)
                self.assertNotIn("vulnerabilidade", claim)
                self.assertNotIn("exploráv", claim)

    def test_confidence_is_never_high(self):
        """Padrão suspeito não é fato verificado — HIGH exigiria taint analysis."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("eval(x)\nos.system(cmd)\npassword = 'hunter2'\n")

            result = _security(root)

            for finding in result["findings"]:
                validate_finding(finding)
                self.assertNotEqual(finding["confidence"], "HIGH")

    def test_scope_limitations_deny_being_a_vulnerability_scanner(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = _security(tmp)

        joined = " ".join(result["scope_limitations"]).lower()
        self.assertIn("não confirma vulnerabilidade", joined)
        self.assertIn("taint", joined)

    def test_evidence_carries_the_literal_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("x = 1\neval(danger)\n")

            result = _security(root)
            evidence = result["findings"][0]["evidence"][0]

            self.assertEqual(evidence["line"], 2)
            self.assertIn("eval", evidence["snippet"])

    def test_false_positive_in_comment_is_still_reported_but_declared(self):
        """A heurística não distingue comentário — e a limitação diz isso.

        Reportar e declarar é honesto; filtrar silenciosamente daria a falsa
        impressão de que a tool entende contexto.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("# nunca use eval(x) aqui\n")

            result = _security(root)
            joined = " ".join(result["scope_limitations"]).lower()

            self.assertTrue(result["findings"])
            self.assertIn("comentário", joined)

    def test_clean_code_yields_no_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("def add(a, b):\n    return a + b\n")

            self.assertEqual(_security(root)["findings"], [])

    def test_never_executes_target_code(self):
        """Um import no alvo não pode rodar. A tool é estática."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "EXECUTED"
            (root / "evil.py").write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('x')\n"
            )

            _security(root)

            self.assertFalse(marker.exists())


class ImprovementReportsMetricsNotJudgementTests(unittest.TestCase):
    """"Isto é ruim" é juízo. "Este arquivo tem N linhas" é métrica."""

    def test_claim_states_the_metric_never_a_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "big.py").write_text("x = 1\n" * 400)

            with patch.object(analysis, "LONG_FILE_LINES", 100):
                result = _improvement(root)

            self.assertTrue(result["findings"])
            for finding in result["findings"]:
                claim = finding["claim"].lower()
                self.assertNotIn("ruim", claim)
                self.assertNotIn("deveria", claim)
                self.assertNotIn("melhor", claim)

    def test_thresholds_are_declared_in_the_response(self):
        """Um threshold escondido faz a métrica parecer objetiva."""
        with tempfile.TemporaryDirectory() as tmp:
            result = _improvement(tmp)

        self.assertIn("thresholds", result)
        self.assertIn("long_file_lines", result["thresholds"])

    def test_long_file_finding_names_the_measured_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "big.py").write_text("x = 1\n" * 250)

            with patch.object(analysis, "LONG_FILE_LINES", 100):
                result = _improvement(root)
            long_files = [f for f in result["findings"] if "linhas" in f["claim"]]

            self.assertIn("250", long_files[0]["claim"])

    def test_todo_markers_are_counted_with_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("# TODO: arrumar\nx = 1\n# FIXME: aqui\n")

            result = _improvement(root)
            markers = [f for f in result["findings"] if "TODO" in f["claim"] or "FIXME" in f["claim"]]

            self.assertEqual(len(markers), 2)
            for finding in markers:
                self.assertTrue(finding["evidence"][0]["snippet"])

    def test_small_clean_project_yields_no_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("def add(a, b):\n    return a + b\n")

            self.assertEqual(_improvement(root)["findings"], [])


class TestAnalyzerIsStaticTests(unittest.TestCase):
    """O plano proíbe executar código do projeto-alvo."""

    def test_never_runs_the_target_suite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "RAN"
            (root / "test_evil.py").write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('x')\n"
            )

            _tests(root)

            self.assertFalse(marker.exists())

    def test_identifies_test_files_by_convention(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test_a.py").write_text("def test_x():\n    assert True\n")
            (root / "b_test.py").write_text("def test_y():\n    assert True\n")
            (root / "c.spec.js").write_text("it('works', () => expect(1).toBe(1))\n")
            (root / "main.py").write_text("x = 1\n")

            result = _tests(root)

            self.assertEqual(result["test_files_found"], 3)
            self.assertEqual(result["source_files_found"], 1)

    def test_ratio_is_reported_as_approximate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test_a.py").write_text("def test_x():\n    assert True\n")
            (root / "main.py").write_text("x = 1\n")

            result = _tests(root)
            joined = " ".join(result["scope_limitations"]).lower()

            self.assertIn("aproxima", joined)

    def test_convention_match_is_medium_never_high(self):
        """Nome de arquivo é convenção, não verificação de que testa algo."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test_a.py").write_text("def test_x():\n    assert True\n")

            result = _tests(root)

            self.assertTrue(result["findings"])
            for finding in result["findings"]:
                validate_finding(finding)
                self.assertEqual(finding["confidence"], "MEDIUM")

    def test_project_without_tests_reports_absence_explicitly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.py").write_text("x = 1\n")

            result = _tests(root)

            self.assertEqual(result["test_files_found"], 0)
            self.assertEqual(result["findings"], [])
            self.assertTrue(result["scope_limitations"])


class FinalAuditRegressionTests(unittest.TestCase):
    """Regressões da auditoria final."""

    def _labels(self, line):
        return [label for label, matcher in analysis.SECURITY_PATTERNS if matcher.search(line)]

    def test_sql_pattern_requires_actual_sql_neighbourhood(self):
        """BLOQUEANTE 4: `def update(self, d): return self.total + 1` casava.

        A claim afirmava "consulta SQL" onde não havia SQL nenhum. `LOW` cobre
        incerteza sobre risco; não cobre descrever errado o que foi visto.
        """
        for benign in (
            "def update(self, data): return self.total + 1",
            'requests.delete(url + "/items")',
            "# Update: crescimento de 5% no trimestre",
            'cache.delete(f"user:{uid}")',
        ):
            with self.subTest(line=benign):
                self.assertNotIn("consulta SQL", " ".join(self._labels(benign)))

    def test_sql_pattern_still_catches_real_concatenation(self):
        self.assertIn(
            "concatenação em consulta SQL",
            self._labels('cursor.execute("SELECT * FROM users WHERE id=" + uid)'),
        )

    def test_credential_pattern_catches_prefixed_names(self):
        """IMPORTANTE 5: o `\\b` encostava em `_` e perdia 5 de 6 grafias."""
        for line in (
            'access_token = "ghp_abcdefghij"',
            'client_secret = "s3cr3t-value"',
            'db_password = "hunter2hunter2"',
            "DATABASE_PASSWORD=supersecret123",
        ):
            with self.subTest(line=line):
                self.assertIn("possível credencial literal no código", self._labels(line))

    def test_os_popen_is_detected(self):
        self.assertIn("execução de comando de sistema", self._labels('os.popen("ls " + d)'))

    def test_secret_value_is_redacted_in_the_evidence(self):
        """IMPORTANTE 6: o snippet devolvia o segredo para o contexto do modelo."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cfg.py").write_text('api_key = "sk-live-REAL-SECRET-VALUE"\n')

            result = _security(root)
            snippet = result["findings"][0]["evidence"][0]["snippet"]

            self.assertNotIn("REAL-SECRET", snippet)
            self.assertIn("api_key", snippet)

    def test_long_line_with_a_marker_reports_both_metrics(self):
        """IMPORTANTE 7: o `elif` descartava a métrica de linha longa."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("# TODO " + "x" * 200 + "\n")

            claims = " ".join(f["claim"] for f in _improvement(root)["findings"])

            self.assertIn("TODO", claims)
            self.assertIn("caracteres", claims)

    def test_line_counting_is_reported_as_a_measurement_not_a_pattern(self):
        """IMPORTANTE 8: contagem exata vinha rotulada como `name-pattern`."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "big.py").write_text("x = 1\n" * 500)

            with patch.object(analysis, "LONG_FILE_LINES", 100):
                result = _improvement(root)
            long_file = [f for f in result["findings"] if "linhas" in f["claim"]][0]

            self.assertEqual(long_file["method"], "line-count")
            self.assertEqual(long_file["confidence"], "HIGH")
