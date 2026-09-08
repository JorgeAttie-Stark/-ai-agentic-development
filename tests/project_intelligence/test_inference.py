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

    def test_cap_skips_whole_files_and_names_them(self):
        """O teto é teto: pula o arquivo inteiro e diz qual.

        A alternativa ao corte no meio do arquivo não é deixar estourar — é
        pular e nomear. Contagem não bastaria: o consumidor precisa saber
        QUAIS arquivos ficaram fora, senão não percebe que uma pasta inteira
        foi omitida.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = "".join(f"    f{n}()\n" for n in range(10))
            for index in range(3):
                (root / f"m{index}.py").write_text(f"def caller():\n{body}")

            with patch.object(inference, "MAX_FINDINGS", 15):
                result = _call_call_graph(root)

            self.assertTrue(result["findings_truncated"])
            self.assertTrue(result["files_skipped_by_cap"])
            self.assertTrue(
                all(name.endswith(".py") for name in result["files_skipped_by_cap"])
            )

    def test_cap_is_never_exceeded(self):
        """Regressão: o teto era piso mole e um repo comum o estourava.

        Medido antes da correção: 528 findings com MAX_FINDINGS=300, o grafo
        de 3 arquivos de teste, e zero findings sobre `src/`.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = "".join(f"    f{n}()\n" for n in range(20))
            for index in range(5):
                (root / f"m{index}.py").write_text(f"def caller():\n{body}")

            with patch.object(inference, "MAX_FINDINGS", 25):
                result = _call_call_graph(root)

            self.assertLessEqual(len(result["findings"]), 25)
            self.assertTrue(result["findings_truncated"])

    def test_file_is_never_returned_partially(self):
        """Nenhum arquivo aparece com parte dos seus findings."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = "".join(f"    f{n}()\n" for n in range(10))
            for index in range(4):
                (root / f"m{index}.py").write_text(f"def caller():\n{body}")

            with patch.object(inference, "MAX_FINDINGS", 25):
                result = _call_call_graph(root)

            per_file = {}
            for finding in result["findings"]:
                name = finding["evidence"][0]["file"]
                per_file[name] = per_file.get(name, 0) + 1
            self.assertTrue(all(count == 10 for count in per_file.values()))


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


class ReviewRegressionTests(unittest.TestCase):
    """Regressões dos achados do reviewer no Milestone 3.

    Nenhum destes casos falhava na suíte anterior. Os três BLOQUEANTE eram o
    `ast` sendo lido por posição de linha em vez de por árvore, e uma corrupção
    silenciosa da citação.
    """

    def test_call_inside_lambda_is_not_attributed_to_the_enclosing_function(self):
        """BLOQUEANTE 1: quem chama é a lambda, invocada por outro alguém."""
        edges = inference._call_edges(
            "def register():\n    button.on_click(lambda: transfer_funds(x))\n", "r.py"
        )
        transfer = [e for e in edges if "transfer_funds" in e["claim"]]

        self.assertNotIn("`register`", transfer[0]["claim"])
        self.assertIn("anônimo", transfer[0]["claim"])

    def test_default_argument_call_is_not_attributed_to_the_function(self):
        """BLOQUEANTE 1: o default roda na definição, no escopo de FORA.

        `charge` nunca chama `build_gateway`. A aresta antiga era simplesmente
        falsa, e vinha com HIGH.
        """
        edges = inference._call_edges(
            "def charge(gateway=build_gateway()):\n    pass\n", "r.py"
        )

        self.assertTrue(edges)
        self.assertNotIn("`charge`", edges[0]["claim"])

    def test_methods_of_different_classes_are_distinct_graph_nodes(self):
        """IMPORTANTE 8: `process` e `process` fundiam num nó só."""
        edges = inference._call_edges(
            "class Alpha:\n"
            "    def process(self):\n"
            "        alpha_only()\n"
            "\n"
            "class Beta:\n"
            "    def process(self):\n"
            "        beta_only()\n",
            "r.py",
        )
        origins = {e["claim"].split("`")[3] for e in edges}

        self.assertEqual(origins, {"Alpha.process", "Beta.process"})

    def test_evidence_line_shows_the_called_name_in_a_multiline_chain(self):
        """BLOQUEANTE 2: a evidência apontava a linha do início da expressão.

        A limitação nº 3 promete que a aresta prova uma chamada com aquele nome
        NAQUELA linha — era falso para cadeia quebrada em linhas.
        """
        source = "def multiline():\n    result = (\n        client\n        .session\n        .post(url)\n    )\n"
        edges = inference._call_edges(source, "c.py")
        post = [e for e in edges if "`post`" in e["claim"]]
        line = post[0]["evidence"][0]["line"]

        self.assertIn("post", source.splitlines()[line - 1])

    def test_domain_signal_alone_is_not_a_candidate(self):
        """IMPORTANTE 6: nada travava a conjunção, o mecanismo de precisão.

        Trocar o `and` por `or` faria a tool virar gerador de ruído — todo `if`
        do projeto — e a suíte anterior continuaria verde.
        """
        self.assertEqual(list(inference._rule_candidate_lines("total = amount * 2\n")), [])

    def test_decision_signal_alone_is_not_a_candidate(self):
        self.assertEqual(
            list(inference._rule_candidate_lines("if not path:\n    raise ValueError(1)\n")),
            [],
        )

    def test_both_signals_together_are_a_candidate(self):
        candidates = list(inference._rule_candidate_lines("if valor > limite:\n"))

        self.assertEqual(len(candidates), 1)

    def test_long_snippet_is_marked_as_truncated(self):
        """BLOQUEANTE 3: cortava no meio da condição, sem marca.

        Perder um `and` ou uma negação entrega uma condição que se lê como
        completa e significa o oposto — na tool cujo produto É o snippet.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            long_line = "if saldo > limite " + "and outra_condicao " * 20 + ": aprovar()\n"
            (root / "b.py").write_text(long_line)

            result = _call_business_rules(root)
            snippet = result["findings"][0]["evidence"][0]["snippet"]

            self.assertIn("truncado", snippet)

    def test_short_snippet_is_the_verbatim_line_without_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "b.py").write_text("if valor > limite:\n")

            result = _call_business_rules(root)
            snippet = result["findings"][0]["evidence"][0]["snippet"]

            self.assertEqual(snippet, "if valor > limite:")
            self.assertNotIn("truncado", snippet)

    def test_scope_limitations_declare_the_natural_language_bias(self):
        """IMPORTANTE 5: o vocabulário é PT/EN, não agnóstico de idioma."""
        with tempfile.TemporaryDirectory() as tmp:
            result = _call_business_rules(tmp)

        joined = " ".join(result["scope_limitations"]).lower()
        self.assertIn("idioma", joined)
        self.assertIn("comentário", joined)

    def test_identifiers_in_another_natural_language_yield_nothing(self):
        """Prova a limitação declarada acima, em vez de só afirmá-la em texto."""
        self.assertEqual(
            list(inference._rule_candidate_lines("if betrag > kreditgrenze:\n")), []
        )
