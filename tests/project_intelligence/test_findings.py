import unittest

from ai_dev_lab.project_intelligence.errors import ToolError
from ai_dev_lab.project_intelligence.findings import (
    CONFIDENCE_BY_METHOD,
    make_evidence,
    make_finding,
    validate_finding,
)


class MakeEvidenceTests(unittest.TestCase):

    def test_builds_evidence_with_file_line_and_snippet(self):
        evidence = make_evidence("src/a.py", 12, "def f():")

        self.assertEqual(evidence, {"file": "src/a.py", "line": 12, "snippet": "def f():"})

    def test_line_and_snippet_are_optional(self):
        evidence = make_evidence("pyproject.toml")

        self.assertEqual(evidence, {"file": "pyproject.toml", "line": None, "snippet": None})

    def test_rejects_absolute_path(self):
        with self.assertRaises(ToolError):
            make_evidence("/Users/someone/project/a.py")

    def test_truncates_long_snippet(self):
        evidence = make_evidence("a.py", 1, "x" * 5000)

        self.assertLess(len(evidence["snippet"]), 5000)


class MakeFindingTests(unittest.TestCase):

    def test_confidence_is_derived_from_method_not_passed_in(self):
        for method, expected in CONFIDENCE_BY_METHOD.items():
            with self.subTest(method=method):
                finding = make_finding("uma claim", method, [make_evidence("a.py")])
                self.assertEqual(finding["confidence"], expected)

    def test_rejects_unknown_method(self):
        with self.assertRaises(ToolError):
            make_finding("uma claim", "vibes", [make_evidence("a.py")])

    def test_rejects_claim_without_evidence(self):
        """A invariante central do projeto: nenhuma claim sem evidência."""
        for evidence in ([], None):
            with self.subTest(evidence=evidence):
                with self.assertRaises(ToolError):
                    make_finding("uma claim", "manifest-read", evidence)

    def test_rejects_empty_claim(self):
        with self.assertRaises(ToolError):
            make_finding("", "manifest-read", [make_evidence("a.py")])

    def test_finding_has_exactly_the_contract_keys(self):
        finding = make_finding("uma claim", "ast-parse", [make_evidence("a.py", 1, "x")])

        self.assertEqual(set(finding), {"claim", "confidence", "method", "evidence"})


class ConfidenceLadderTests(unittest.TestCase):

    def test_parsing_methods_are_high_and_heuristics_are_not(self):
        self.assertEqual(CONFIDENCE_BY_METHOD["manifest-read"], "HIGH")
        self.assertEqual(CONFIDENCE_BY_METHOD["ast-parse"], "HIGH")
        self.assertEqual(CONFIDENCE_BY_METHOD["name-pattern"], "MEDIUM")
        self.assertEqual(CONFIDENCE_BY_METHOD["regex-heuristic"], "LOW")

    def test_no_method_maps_to_a_confidence_outside_the_ladder(self):
        self.assertTrue(set(CONFIDENCE_BY_METHOD.values()) <= {"HIGH", "MEDIUM", "LOW"})


class ValidateFindingTests(unittest.TestCase):

    def test_accepts_a_well_formed_finding(self):
        validate_finding(make_finding("c", "ast-parse", [make_evidence("a.py")]))

    def test_rejects_hand_built_finding_that_breaks_the_ladder(self):
        """Guarda contra alguém montar o dict à mão e inflar a confiança."""
        forged = {
            "claim": "arquitetura em camadas",
            "confidence": "HIGH",
            "method": "name-pattern",
            "evidence": [make_evidence("handlers/a.py")],
        }

        with self.assertRaises(ToolError):
            validate_finding(forged)

    def test_rejects_finding_with_empty_evidence_list(self):
        forged = {
            "claim": "c",
            "confidence": "HIGH",
            "method": "ast-parse",
            "evidence": [],
        }

        with self.assertRaises(ToolError):
            validate_finding(forged)


class EvidenceInvariantRegressionTests(unittest.TestCase):
    """IMPORTANTE 9: as invariantes eram mais fracas que o docstring afirmava.

    Todos estes casos eram ACEITOS antes. O reviewer mostrou que `make_evidence`
    não era chokepoint — um dict cru com path absoluto atravessava
    `make_finding` sem checagem — e que `validate_finding` não olhava item de
    evidência nenhum.
    """

    def test_string_as_evidence_is_rejected(self):
        """`list("abc")` viraria três itens de evidência de um caractere."""
        with self.assertRaises(ToolError):
            make_finding("c", "ast-parse", "abc")

    def test_raw_dict_without_file_is_rejected(self):
        with self.assertRaises(ToolError):
            make_finding("c", "ast-parse", [{}])

    def test_raw_dict_with_absolute_path_is_rejected(self):
        with self.assertRaises(ToolError):
            make_finding(
                "c",
                "ast-parse",
                [{"file": "/Users/alguem/.ssh/id_rsa", "line": 1, "snippet": "k"}],
            )

    def test_path_with_parent_traversal_is_rejected(self):
        with self.assertRaises(ToolError):
            make_finding(
                "c", "ast-parse", [{"file": "../../etc/passwd", "line": 1, "snippet": "x"}]
            )

    def test_validate_finding_checks_evidence_items_too(self):
        forged = {
            "claim": "c",
            "confidence": "HIGH",
            "method": "ast-parse",
            "evidence": [{"file": "/etc/passwd", "line": 1, "snippet": "x"}],
        }

        with self.assertRaises(ToolError):
            validate_finding(forged)

    def test_validate_finding_rejects_empty_claim(self):
        forged = {
            "claim": "",
            "confidence": "HIGH",
            "method": "ast-parse",
            "evidence": [make_evidence("a.py")],
        }

        with self.assertRaises(ToolError):
            validate_finding(forged)


class UnknownFieldRegressionTests(unittest.TestCase):
    """IMPORTANTE 4: a impossibilidade estrutural era teste, não código.

    `validate_finding` checava chave FALTANDO, nunca chave SOBRANDO. Uma tool
    futura acrescentava `interpretation` e passava — e a garantia de que
    `business_rules_analyzer` não descreve a regra voltava a depender de um
    teste que só cobria aquela tool.
    """

    def test_finding_with_unknown_field_is_rejected(self):
        finding = make_finding("c", "ast-parse", [make_evidence("a.py")])
        finding["interpretation"] = "valores acima do limite são rejeitados"

        with self.assertRaises(ToolError):
            validate_finding(finding)

    def test_evidence_item_with_unknown_field_is_rejected(self):
        finding = make_finding("c", "ast-parse", [make_evidence("a.py")])
        finding["evidence"][0]["rule"] = "descrição enfiada aqui"

        with self.assertRaises(ToolError):
            validate_finding(finding)


class CapSemanticsAreUniformTests(unittest.TestCase):
    """O teto tem a MESMA semântica em toda tool que emite findings.

    Este teste existe porque a inconsistência real aconteceu: eu corrigi a
    semântica do teto no `inference.py` quando o reviewer apontou, e não voltei
    para aplicar em `understanding.py`. As 6 tools do Milestone 2 ficaram com o
    comportamento antigo — teto como piso mole, `files_skipped_by_cap` como
    contagem — e nada na suíte percebeu.

    Só apareceu quando eu exercitei as 18 tools pelo processo real de stdio e
    comparei os números: 336 findings numa tool com teto declarado de 300.
    """

    def _findings_tools(self):
        from ai_dev_lab.project_intelligence.registry import TOOL_REGISTRY

        return {
            name: spec
            for name, spec in TOOL_REGISTRY.items()
            if "findings" in spec["output_schema"].get("properties", {})
        }

    def test_no_tool_exceeds_the_shared_cap(self):
        from pathlib import Path as P

        from ai_dev_lab.project_intelligence.scanning import MAX_FINDINGS

        root = P(__file__).parent.parent.parent
        for name, spec in self._findings_tools().items():
            with self.subTest(tool=name):
                result = spec["handler"](root, {})
                self.assertLessEqual(len(result["findings"]), MAX_FINDINGS)

    def test_files_skipped_by_cap_is_always_a_list_of_names(self):
        from pathlib import Path as P

        root = P(__file__).parent.parent.parent
        for name, spec in self._findings_tools().items():
            skipped = spec["handler"](root, {}).get("files_skipped_by_cap")
            if skipped is None:
                continue
            with self.subTest(tool=name):
                self.assertIsInstance(skipped, list)
                self.assertTrue(all(isinstance(item, str) for item in skipped))
