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
    parity.py
    project_intelligence/    # servidor MCP sobre stdio (Milestone 0)
tests/
    project_intelligence/    # testes de config.py e protocol.py
docs/
```

O pacote importável é `ai_dev_lab`, dentro de `src/`.

### `project_intelligence/` — servidor MCP

Servidor MCP sobre stdio (JSON-RPC 2.0, uma requisição por linha), que aponta
para um `projectRoot` — por padrão o `cwd` do processo, com `--root` como
override opcional. Hoje expõe `initialize`, `tools/list` e `tools/call` para
uma única tool: `project_info`.

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
      "args": ["-m", "ai_dev_lab.project_intelligence"],
      "cwd": "/caminho/do/projeto/alvo",
      "env": { "PYTHONPATH": "/caminho/do/repositorio/src" }
    }
  }
}
```

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