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
tests/
docs/
```

O pacote importável é `ai_dev_lab`, dentro de `src/`.

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