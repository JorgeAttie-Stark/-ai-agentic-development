"""Envelope de evidência das tools interpretativas (Camadas 2+).

As tools de retrieval — `project_info`, `list_files`, `read_file`,
`search_code`, `project_profile` — não usam este módulo: elas **são** a
evidência, não uma inferência sobre ela. A partir da Camada Entendimento as
tools passam a *afirmar* coisas, e é aqui que essa afirmação fica amarrada ao
que a sustenta.

Duas invariantes, ambas impostas por código e não por convenção:

1. **Nenhuma claim sem evidência.** `make_finding` recusa lista vazia.
2. **`confidence` é derivada do `method`, nunca escolhida.** Não existe
   parâmetro de confiança — quem quiser `HIGH` precisa usar um método que
   parseia formato bem definido. Isso é o que impede a tool de "achar" que
   está mais certa do que o método permite.
"""
from __future__ import annotations

from .errors import ToolError

MAX_SNIPPET_LENGTH = 200

# A escada. `confidence` não é julgamento: é uma função do método que produziu
# a conclusão. Um método novo exige uma linha aqui, o que força a decisão de
# quanta confiança ele merece a ser explícita e revisável.
CONFIDENCE_BY_METHOD = {
    # A evidência É o fato: parsing de formato bem definido.
    "manifest-read": "HIGH",
    "ast-parse": "HIGH",
    # Convenção forte e comum, não verificada semanticamente. Um diretório
    # chamado `handlers/` sugere um padrão; não prova direção de dependência.
    "name-pattern": "MEDIUM",
    # Sem parser real. Falso positivo é esperado, não anomalia.
    "regex-heuristic": "LOW",
}


def make_evidence(file, line=None, snippet=None):
    """Um item de evidência: onde olhar para conferir a claim.

    `file` é sempre relativo à raiz do projeto. Path absoluto é recusado aqui,
    no construtor, e não em cada tool — vazamento de estrutura de máquina é
    fácil de introduzir por descuido e caro de auditar depois.
    """
    if not isinstance(file, str) or not file:
        raise ToolError("evidência exige um caminho de arquivo não vazio")
    if file.startswith("/"):
        raise ToolError("evidência exige caminho relativo, não absoluto")

    if snippet is not None:
        snippet = snippet[:MAX_SNIPPET_LENGTH]

    return {"file": file, "line": line, "snippet": snippet}


def make_finding(claim, method, evidence):
    """Constrói um finding com a confiança derivada do método.

    Não há parâmetro `confidence` de propósito: a única forma de emitir `HIGH`
    é usar um método que a escada classifica como `HIGH`.
    """
    if not isinstance(claim, str) or not claim:
        raise ToolError("finding exige uma claim não vazia")
    if method not in CONFIDENCE_BY_METHOD:
        raise ToolError(f"método desconhecido: {method}")
    if not evidence:
        raise ToolError("finding exige ao menos um item de evidência")

    return {
        "claim": claim,
        "confidence": CONFIDENCE_BY_METHOD[method],
        "method": method,
        "evidence": list(evidence),
    }


def validate_finding(finding):
    """Revalida um finding já construído, inclusive um montado à mão.

    Existe porque `make_finding` pode ser contornado — um dict literal com
    `confidence: HIGH` e `method: regex-heuristic` é sintaticamente possível.
    Esta função é o ponto onde essa inflação é pega.
    """
    missing = {"claim", "confidence", "method", "evidence"} - set(finding)
    if missing:
        raise ToolError(f"finding incompleto, faltam: {sorted(missing)}")

    method = finding["method"]
    if method not in CONFIDENCE_BY_METHOD:
        raise ToolError(f"método desconhecido: {method}")
    if finding["confidence"] != CONFIDENCE_BY_METHOD[method]:
        raise ToolError(
            f"confiança inconsistente com o método: {method} exige "
            f"{CONFIDENCE_BY_METHOD[method]}"
        )
    if not finding["evidence"]:
        raise ToolError("finding exige ao menos um item de evidência")


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
