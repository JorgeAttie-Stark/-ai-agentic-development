"""Descoberta das raízes que o cliente pode pedir.

Existe porque o cliente não tem como adivinhar caminhos. Sem esta tool, a
única forma de analisar outro repositório é o humano digitar o caminho
absoluto — foi exatamente o que travou o primeiro teste real no Claude
Desktop, que precisou perguntar onde o `app-web` estava clonado.

Esta é a única tool que devolve caminho absoluto. `make_evidence` recusa
absoluto porque vazaria a estrutura da máquina sem ganho nenhum; aqui o
caminho absoluto É o produto, porque o cliente precisa devolvê-lo em `root`.
O alcance não aumenta: a tool só nomeia o que os `--allow-parent` já tornavam
alcançável, e só os diretórios que a porta de repositório aceitaria.
"""
from __future__ import annotations

import os
from pathlib import Path

from .paths import is_repository

MAX_SCAN_DEPTH = 4
MAX_REPOSITORIES = 200

# `Library` e `node_modules` são os dois que fazem a varredura de `$HOME`
# custar segundos em vez de milissegundos.
PRUNED_DIRECTORY_NAMES = frozenset(
    {"node_modules", "vendor", "Library", "__pycache__", "venv", ".venv", "target", "build"}
)

DISCOVERY_LIMITATIONS = (
    f"busca no máximo {MAX_SCAN_DEPTH} níveis abaixo de cada diretório permitido",
    "um repositório encontrado não é percorrido por dentro — repos aninhados não aparecem",
    "diretórios ocultos, `node_modules`, `vendor`, `Library` e `build` são podados",
    "reconhece repositório pela presença de `.git`; projeto sem versionamento não aparece",
)

LIST_REPOSITORIES_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "repositories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "name": {"type": "string"}},
                "required": ["path", "name"],
            },
        },
        "searched": {"type": "array", "items": {"type": "string"}},
        "truncated": {"type": "boolean"},
        "scope_limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["repositories", "searched", "truncated", "scope_limitations"],
}


def _subdirectories(current):
    try:
        with os.scandir(current) as entries:
            listed = sorted(entries, key=lambda entry: entry.name)
    except OSError:
        # Diretório sem permissão de leitura não interrompe a varredura das
        # outras áreas. `~/Library` de outro usuário é o caso comum.
        return []

    return [
        Path(entry.path)
        for entry in listed
        # `follow_symlinks=False`: um link apontando para o pai fecharia um
        # ciclo, e a busca não tem detecção de visitados.
        if entry.is_dir(follow_symlinks=False)
        and not entry.name.startswith(".")
        and entry.name not in PRUNED_DIRECTORY_NAMES
    ]


def _discover(area):
    found = []
    pending = [(Path(area), 0)]

    while pending:
        current, depth = pending.pop()
        if is_repository(current):
            found.append(current)
            continue
        if depth >= MAX_SCAN_DEPTH:
            continue
        pending.extend((child, depth + 1) for child in _subdirectories(current))

    return found


def _handle_list_repositories(project_root, arguments, context):
    areas = [context["roots"]["default"], *context.get("allowed_parents", [])]

    by_path = {}
    for area in areas:
        for repository in _discover(area):
            by_path.setdefault(str(repository), repository.name)

    paths = sorted(by_path)
    truncated = len(paths) > MAX_REPOSITORIES
    limitations = list(DISCOVERY_LIMITATIONS)
    if truncated:
        limitations.append(f"mostrando {MAX_REPOSITORIES} de {len(paths)} repositórios")

    return {
        "repositories": [{"path": path, "name": by_path[path]} for path in paths[:MAX_REPOSITORIES]],
        "searched": [str(area) for area in areas],
        "truncated": truncated,
        "scope_limitations": limitations,
    }
