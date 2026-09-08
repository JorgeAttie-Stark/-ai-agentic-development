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
