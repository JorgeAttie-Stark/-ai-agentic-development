"""Envelope de evidência das tools interpretativas (Camadas 2+).

As tools de retrieval — `project_info`, `list_files`, `read_file`,
`search_code`, `project_profile` — não usam este módulo: elas **são** a
evidência, não uma inferência sobre ela. A partir da Camada Entendimento as
tools passam a *afirmar* coisas, e é aqui que essa afirmação fica amarrada ao
que a sustenta.

Quatro invariantes, todas impostas por código e não por convenção:

1. **Nenhuma claim sem evidência.** `make_finding` recusa lista vazia — e
   recusa string, que é iterável e viraria um "item" por caractere.
2. **`confidence` é derivada do `method`, nunca escolhida.** Não existe
   parâmetro de confiança — quem quiser `HIGH` precisa usar um método que
   parseia formato bem definido. Isso é o que impede a tool de "achar" que
   está mais certa do que o método permite.
3. **Todo item de evidência é validado**, venha de `make_evidence` ou de dict
   cru. Path absoluto, `..` e item sem `file` são recusados em
   `_validate_evidence_item`, que os dois caminhos atravessam. Sem isso,
   `make_evidence` não era chokepoint e a garantia voltava a ser convenção.
4. **`validate_finding` é chamada em produção**, no ponto de saída de cada
   tool interpretativa — não é utilitário de teste. Ela recusa campo
   desconhecido, e é isso que torna estrutural a proibição de descrever a
   regra: uma tool futura não consegue acrescentar `interpretation` ou
   `description` a um finding.
"""
from __future__ import annotations

import os
from pathlib import Path

from .errors import ToolError

MAX_SNIPPET_LENGTH = 200
# Marca explícita de corte. Sem ela, uma condição cortada no meio se lê como
# completa e pode significar o oposto: perder um `and`, uma negação ou um
# segundo limite muda o sentido sem nenhum sinal. O `business_rules_analyzer`
# declara devolver "o trecho literal" — para linha longa, isso só é verdade
# com a marca.
SNIPPET_TRUNCATION_MARK = " …[truncado]"

# A escada. `confidence` não é julgamento: é uma função do método que produziu
# a conclusão. Um método novo exige uma linha aqui, o que força a decisão de
# quanta confiança ele merece a ser explícita e revisável.
CONFIDENCE_BY_METHOD = {
    # A evidência É o fato: parsing de formato bem definido.
    "manifest-read": "HIGH",
    "ast-parse": "HIGH",
    # Contagem determinística: linhas, caracteres, arquivos. A evidência É o
    # fato, igual a parsing. Existe separado porque rotular medição como
    # `name-pattern` deixava o handler escolher a confiança por via indireta.
    "line-count": "HIGH",
    # Convenção forte e comum, não verificada semanticamente. Um diretório
    # chamado `handlers/` sugere um padrão; não prova direção de dependência.
    "name-pattern": "MEDIUM",
    # Sem parser real. Falso positivo é esperado, não anomalia.
    "regex-heuristic": "LOW",
}


def _validate_evidence_item(item):
    """Valida um item de evidência, venha ele de `make_evidence` ou de dict cru.

    Existe separado porque `make_evidence` não era chokepoint: um dict literal
    com path absoluto passava por `make_finding` sem checagem, e a garantia de
    "recusa path absoluto no construtor" voltava a ser convenção.
    """
    if not isinstance(item, dict):
        raise ToolError("cada item de evidência deve ser um dict")

    expected = {"file", "line", "snippet"}
    missing = expected - set(item)
    if missing:
        raise ToolError(f"item de evidência incompleto, faltam: {sorted(missing)}")

    unknown = set(item) - expected
    if unknown:
        raise ToolError(f"item de evidência com campo desconhecido: {sorted(unknown)}")

    file = item["file"]
    if not isinstance(file, str) or not file:
        raise ToolError("evidência exige um caminho de arquivo não vazio")
    if os.path.isabs(file) or file.startswith("/") or ":" in file[:3]:
        raise ToolError("evidência exige caminho relativo, não absoluto")
    if ".." in Path(file).parts:
        raise ToolError("evidência não pode conter `..`")


def make_evidence(file, line=None, snippet=None):
    """Um item de evidência: onde olhar para conferir a claim.

    `file` é sempre relativo à raiz do projeto. Path absoluto é recusado aqui,
    no construtor, e não em cada tool — vazamento de estrutura de máquina é
    fácil de introduzir por descuido e caro de auditar depois.
    """
    if snippet is not None and len(snippet) > MAX_SNIPPET_LENGTH:
        snippet = snippet[:MAX_SNIPPET_LENGTH] + SNIPPET_TRUNCATION_MARK

    item = {"file": file, "line": line, "snippet": snippet}
    _validate_evidence_item(item)
    return item


def make_finding(claim, method, evidence):
    """Constrói um finding com a confiança derivada do método.

    Não há parâmetro `confidence` de propósito: a única forma de emitir `HIGH`
    é usar um método que a escada classifica como `HIGH`.
    """
    if not isinstance(claim, str) or not claim:
        raise ToolError("finding exige uma claim não vazia")
    if method not in CONFIDENCE_BY_METHOD:
        raise ToolError(f"método desconhecido: {method}")
    if not evidence or isinstance(evidence, (str, bytes)):
        # Uma string é iterável: `list("abc")` viraria três "itens" de
        # evidência de um caractere cada, e passava pela checagem de não-vazio.
        raise ToolError("finding exige ao menos um item de evidência")

    evidence = list(evidence)
    for item in evidence:
        _validate_evidence_item(item)

    return {
        "claim": claim,
        "confidence": CONFIDENCE_BY_METHOD[method],
        "method": method,
        "evidence": evidence,
    }


def validate_finding(finding):
    """Revalida um finding já construído, inclusive um montado à mão.

    Existe porque `make_finding` pode ser contornado — um dict literal com
    `confidence: HIGH` e `method: regex-heuristic` é sintaticamente possível.
    Esta função é o ponto onde essa inflação é pega.
    """
    expected = {"claim", "confidence", "method", "evidence"}
    missing = expected - set(finding)
    if missing:
        raise ToolError(f"finding incompleto, faltam: {sorted(missing)}")

    # Recusar chave DESCONHECIDA é o que torna a impossibilidade estrutural
    # real. Sem isto, uma tool futura acrescenta `interpretation` ou
    # `description` e passa — e a garantia de que `business_rules_analyzer`
    # não descreve a regra volta a depender de um teste que só cobre aquela
    # tool específica.
    unknown = set(finding) - expected
    if unknown:
        raise ToolError(f"finding com campo desconhecido: {sorted(unknown)}")

    method = finding["method"]
    if method not in CONFIDENCE_BY_METHOD:
        raise ToolError(f"método desconhecido: {method}")
    if finding["confidence"] != CONFIDENCE_BY_METHOD[method]:
        raise ToolError(
            f"confiança inconsistente com o método: {method} exige "
            f"{CONFIDENCE_BY_METHOD[method]}"
        )
    if not isinstance(finding["claim"], str) or not finding["claim"]:
        raise ToolError("finding exige uma claim não vazia")
    if not finding["evidence"]:
        raise ToolError("finding exige ao menos um item de evidência")
    for item in finding["evidence"]:
        _validate_evidence_item(item)


FINDING_SCHEMA = {
    "type": "object",
    "properties": {
        "claim": {"type": "string"},
        "confidence": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
        "method": {"type": "string", "enum": sorted(CONFIDENCE_BY_METHOD)},
        "evidence": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "line": {"type": ["integer", "null"]},
                    "snippet": {"type": ["string", "null"]},
                },
                "required": ["file", "line", "snippet"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["claim", "confidence", "method", "evidence"],
    "additionalProperties": False,
}


def findings_output_schema(extra_properties=None):
    """Schema de saída de uma tool interpretativa: `findings` + limitações.

    `extra_properties` acrescenta campos factuais da tool específica (contagens,
    inventários) ao lado do envelope, sem duplicar a definição de `finding`.
    """
    properties = {
        "findings": {"type": "array", "items": FINDING_SCHEMA},
        "scope_limitations": {"type": "array", "items": {"type": "string"}},
    }
    properties.update(extra_properties or {})

    return {
        "type": "object",
        "properties": properties,
        "required": sorted(properties),
        "additionalProperties": False,
    }
