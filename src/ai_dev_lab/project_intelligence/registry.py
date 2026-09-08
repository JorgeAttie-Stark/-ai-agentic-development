"""Catálogo de tools — a raiz de composição do servidor.

Vive fora de `exploration.py` e `understanding.py` de propósito: o registry
compõe as duas camadas, então colocá-lo dentro de uma delas obrigaria essa
camada a importar a outra. `understanding` já importa `exploration` (reusa a
poda de `.gitignore` e a caminhada da árvore); o inverso fecharia um ciclo.

`protocol.py` importa daqui e não conhece nenhuma camada diretamente.
"""
from __future__ import annotations

from . import analysis, exploration, inference, presentation, understanding

TOOL_REGISTRY = {
    "project_info": {
        "description": "Contagem de arquivos, linhas e manifestos conhecidos na raiz do projeto.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": exploration.PROJECT_INFO_OUTPUT_SCHEMA,
        "handler": exploration._handle_project_info,
    },
    "list_files": {
        "description": (
            "Lista os arquivos da raiz do projeto, ignorando `.git/` e respeitando "
            "best-effort um `.gitignore` de topo."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": exploration.LIST_FILES_OUTPUT_SCHEMA,
        "handler": exploration._handle_list_files,
    },
    "read_file": {
        "description": "Lê o conteúdo de um arquivo de texto dentro da raiz do projeto.",
        "input_schema": exploration.READ_FILE_INPUT_SCHEMA,
        "output_schema": exploration.READ_FILE_OUTPUT_SCHEMA,
        "handler": exploration._handle_read_file,
    },
    "search_code": {
        "description": (
            "Pesquisa uma regex nos arquivos de texto da raiz do projeto e devolve "
            "arquivo, número de linha e o trecho da linha que casou."
        ),
        "input_schema": exploration.SEARCH_CODE_INPUT_SCHEMA,
        "output_schema": exploration.SEARCH_CODE_OUTPUT_SCHEMA,
        "handler": exploration._handle_search_code,
    },
    "project_profile": {
        "description": (
            "Visão consolidada do projeto, derivada de project_info e list_files: "
            "extensões mais comuns, maiores diretórios e profundidade máxima."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": exploration.PROJECT_PROFILE_OUTPUT_SCHEMA,
        "handler": exploration._handle_project_profile,
    },
    "project_map": {
        "description": (
            "Árvore de diretórios da raiz com contagem de arquivos por diretório. "
            "Estrutura observada, sem inferência."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": understanding.PROJECT_MAP_OUTPUT_SCHEMA,
        "handler": understanding._handle_project_map,
    },
    "architecture_explainer": {
        "description": (
            "Relata padrões de nome de diretório que SUGEREM camadas arquiteturais. "
            "Confiança capada em MEDIUM: nome de pasta não prova dependência."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": understanding.ARCHITECTURE_EXPLAINER_OUTPUT_SCHEMA,
        "handler": understanding._handle_architecture_explainer,
    },
    "code_structure_analyzer": {
        "description": (
            "Classes, funções e imports. Python via `ast` (HIGH); outras linguagens "
            "por heurística de regex (LOW)."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": understanding.CODE_STRUCTURE_OUTPUT_SCHEMA,
        "handler": understanding._handle_code_structure_analyzer,
    },
    "dependency_analyzer": {
        "description": (
            "Dependências declaradas nos manifestos da raiz. package.json e "
            "requirements.txt parseados (HIGH); pyproject.toml por regex (LOW)."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": understanding.DEPENDENCY_OUTPUT_SCHEMA,
        "handler": understanding._handle_dependency_analyzer,
    },
    "data_flow_analyzer": {
        "description": (
            "Grafo de CHAMADAS de Python via `ast`. Não é análise de fluxo de dados: "
            "fluxo real exige CFG, inviável em stdlib. Ver scope_limitations."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": inference.DATA_FLOW_OUTPUT_SCHEMA,
        "handler": inference._handle_data_flow_analyzer,
    },
    "business_rules_analyzer": {
        "description": (
            "Localiza CANDIDATOS a regra de negócio e devolve o trecho literal. "
            "Não descreve a regra — a interpretação cabe a quem lê o snippet."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": inference.BUSINESS_RULES_OUTPUT_SCHEMA,
        "handler": inference._handle_business_rules_analyzer,
    },
    "security_analyzer": {
        "description": (
            "Detecção de PADRÃO de segurança, não de vulnerabilidade confirmada. "
            "Confirmar exigiria taint analysis. Nenhum finding chega a HIGH."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": analysis.SECURITY_OUTPUT_SCHEMA,
        "handler": analysis._handle_security_analyzer,
    },
    "improvement_analyzer": {
        "description": (
            "Métricas estruturais com o valor medido e os limiares declarados. "
            "Reporta fato, nunca juízo de qualidade."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": analysis.IMPROVEMENT_OUTPUT_SCHEMA,
        "handler": analysis._handle_improvement_analyzer,
    },
    "test_analyzer": {
        "description": (
            "Presença e convenção de testes, ESTATICAMENTE. Nunca executa a "
            "suíte do projeto-alvo."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": analysis.TEST_ANALYZER_OUTPUT_SCHEMA,
        "handler": analysis._handle_test_analyzer,
    },
    "generate_mermaid": {
        "description": (
            "Serializa findings de uma tool de análise em diagrama Mermaid. "
            "Zero análise nova: aresta sólida é HIGH, tracejada é MEDIUM/LOW."
        ),
        "input_schema": presentation.MERMAID_INPUT_SCHEMA,
        "output_schema": presentation.MERMAID_OUTPUT_SCHEMA,
        "handler": presentation._handle_generate_mermaid,
    },
    "generate_project_report": {
        "description": (
            "Relatório Markdown completo, com a confiança e o método ao lado de "
            "cada conclusão. Consome outras tools; não conclui nada."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": presentation.DOCUMENT_OUTPUT_SCHEMA,
        "handler": presentation._handle_generate_project_report,
    },
    "generate_architecture_documentation": {
        "description": (
            "Documento de arquitetura observada. Declara ausência de evidência "
            "em vez de preencher com suposição."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": presentation.DOCUMENT_OUTPUT_SCHEMA,
        "handler": presentation._handle_generate_architecture_documentation,
    },
    "generate_project_summary": {
        "description": (
            "Resumo curto do projeto. Mesmas fontes do relatório, menos texto, "
            "nenhuma síntese nova."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": presentation.DOCUMENT_OUTPUT_SCHEMA,
        "handler": presentation._handle_generate_project_summary,
    },
}
