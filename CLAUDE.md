# AI Dev Lab

## Objetivo

Este projeto é um laboratório para aprender
AI Engineering usando Claude Code.

## Stack

- Python 3 (stdlib)
- unittest (stdlib)
- FastAPI — planejado, ainda não utilizado

## Regras

- Não alterar código sem entender os testes.
- Sempre criar testes para novo comportamento.
- Rodar os testes depois das alterações.
- Não considerar uma tarefa concluída sem verificar os testes.

## Arquitetura

```text
src/ai_dev_lab/
    project_intelligence/    # servidor MCP sobre stdio (Milestone 0 e 1)
tests/
    project_intelligence/    # testes de config.py, protocol.py e exploration.py
docs/
```

O pacote importável é `ai_dev_lab`, dentro de `src/`.

### `project_intelligence/` — servidor MCP

Servidor MCP sobre stdio (JSON-RPC 2.0, uma requisição por linha), que aponta
para um `projectRoot` resolvido de `--root`, com o `cwd` do processo como
fallback. Hoje expõe `initialize`, `tools/list` e `tools/call` para dezoito tools:

**Camada Exploração** — retrieval pura, sem envelope:

| Tool | O que faz |
|---|---|
| `project_info` | contagem por extensão, total de arquivos e linhas, manifestos na raiz |
| `list_files` | inventário de arquivos, ignorando `.git/` e o `.gitignore` de topo |
| `read_file` | conteúdo de um arquivo de texto, confinado à raiz via `paths.resolve_within` |
| `search_code` | regex nos arquivos de texto; devolve arquivo, linha e o trecho que casou |
| `project_profile` | visão consolidada, derivada de `project_info` + `list_files` |

**Camada Entendimento** — as primeiras que *afirmam* algo:

| Tool | Método | `confidence` |
|---|---|---|
| `project_map` | árvore de diretórios — factual, **sem** findings | — |
| `architecture_explainer` | `name-pattern` | `MEDIUM`, capado |
| `code_structure_analyzer` | `ast-parse` (Python) / `regex-heuristic` (resto) | `HIGH` / `LOW` |
| `dependency_analyzer` | `manifest-read` / `regex-heuristic` (TOML) | `HIGH` / `LOW` |
| `data_flow_analyzer` | `ast-parse` — grafo de **chamadas**, não fluxo de dados | `HIGH` |
| `business_rules_analyzer` | `regex-heuristic` — localiza candidatos, **não descreve a regra** | `LOW` |

**Camada Análise** — nomes que prometem juízo, com o limite fixado:

| Tool | Limite |
|---|---|
| `security_analyzer` | detecta **padrão**, nunca vulnerabilidade confirmada. Nada chega a `HIGH` |
| `improvement_analyzer` | **métrica com o valor medido** e limiares no retorno, nunca juízo |
| `test_analyzer` | **estático** — nunca executa a suíte do projeto-alvo |

**Camadas Visualização e Documentação** — serialização, zero análise nova:

| Tool | |
|---|---|
| `generate_mermaid` | aresta sólida = `HIGH`, tracejada = `MEDIUM`/`LOW` |
| `generate_project_report` | confiança e método ao lado de cada conclusão |
| `generate_architecture_documentation` | declara ausência em vez de supor |
| `generate_project_summary` | mesmas fontes, menos texto |

Toda tool destas duas camadas declara `derived_from` — um documento sem
procedência é uma afirmação sem fonte.

### O envelope de evidência

`findings.py` impõe por código, não por convenção:

- **Nenhuma claim sem evidência** — `make_finding` recusa lista vazia
- **`confidence` é derivada do `method`, nunca escolhida** — não existe parâmetro
  de confiança na API. A única forma de emitir `HIGH` é usar um método que
  parseia formato bem definido
- **`validate_finding` pega dict forjado à mão** com confiança inflada
- **Evidência recusa path absoluto** no construtor, não em cada tool

Onde não há evidência, a tool reporta **ausência**, não palpite. Lista de
findings vazia com limitação declarada é resposta melhor que inferência fraca
apresentada como descoberta.

As cinco primeiras são retrieval pura — devolvem fato observado, sem envelope
de `findings`/`confidence`.

Rodar o servidor apontado para um projeto alvo:

```bash
PYTHONPATH=src python3 -m ai_dev_lab.project_intelligence --root /caminho/do/projeto/alvo
```

Configuração no Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "project-intel": {
      "command": "python3",
      "args": [
        "-m", "ai_dev_lab.project_intelligence",
        "--root", "/caminho/do/projeto/alvo"
      ],
      "env": { "PYTHONPATH": "/caminho/do/repositorio/src" }
    }
  }
}
```

`--root` é obrigatório aqui. O Claude Desktop não suporta a chave `cwd` em
`mcpServers` — ele descarta a chave ao reescrever o arquivo de config. Sem
`--root`, a raiz vira o diretório de trabalho do app e o inventário sai
inútil, sem erro que indique a causa.

O fallback para `cwd` continua valendo ao rodar o servidor à mão no terminal.

Detalhes de arquitetura, escopo e roadmap completos em
`docs/plan-project-intelligence-mcp.md`.

## Comandos

Rodar os testes:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Neste ambiente existe apenas `python3` — `python` não está no PATH.
Não use `pytest`: o projeto usa `unittest` da stdlib.

## Definition of Done

Uma tarefa só está pronta quando:

1. implementação concluída;
2. testes criados ou atualizados;
3. testes passando;
4. nenhuma regressão conhecida.