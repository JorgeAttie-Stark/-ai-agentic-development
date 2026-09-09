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

# A mensagem diz o que fazer, não só o que faltou: sem a causa, o humano
# conclui que o repositório não existe e o move de lugar. No macOS,
# `~/Desktop`, `~/Documents` e `~/Downloads` são gated por TCC POR APLICATIVO —
# o terminal pode ter acesso e o app cliente não, e aí a mesma varredura
# devolve listas diferentes.
UNREADABLE_LIMITATION = (
    "não foi possível ler {count} diretório(s) — os repositórios dentro deles "
    "NÃO aparecem nesta lista, e a ausência aqui não significa que não existem; "
    "veja `unreadable_directories`. No macOS, `~/Desktop`, `~/Documents` e "
    "`~/Downloads` exigem permissão concedida ao aplicativo cliente em "
    "Ajustes do Sistema > Privacidade e Segurança > Arquivos e Pastas"
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
        "unreadable_directories": {"type": "array", "items": {"type": "string"}},
        "truncated": {"type": "boolean"},
        "scope_limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "repositories",
        "searched",
        "unreadable_directories",
        "truncated",
        "scope_limitations",
    ],
}


def _subdirectories(current, unreadable):
    try:
        with os.scandir(current) as entries:
            listed = sorted(entries, key=lambda entry: entry.name)
    except OSError:
        # Degradar sim, silenciar não. Este `except` já engoliu um
        # `PermissionError` em `~/Desktop` — o cliente recebeu 15 repos em vez
        # de 19, concluiu que o `app-web` "não estava clonado" e recomendou
        # mover o repositório. Ausência não declarada vira inexistência para
        # quem lê.
        unreadable.append(str(current))
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


def _discover(area, unreadable):
    found = []
    pending = [(Path(area), 0)]

    while pending:
        current, depth = pending.pop()
        if is_repository(current):
            found.append(current)
            continue
        if depth >= MAX_SCAN_DEPTH:
            continue
        pending.extend((child, depth + 1) for child in _subdirectories(current, unreadable))

    return found


def _handle_list_repositories(project_root, arguments, context):
    areas = [context["roots"]["default"], *context.get("allowed_parents", [])]

    by_path = {}
    unreadable = []
    for area in areas:
        for repository in _discover(area, unreadable):
            by_path.setdefault(str(repository), repository.name)

    paths = sorted(by_path)
    truncated = len(paths) > MAX_REPOSITORIES
    limitations = list(DISCOVERY_LIMITATIONS)
    if truncated:
        limitations.append(f"mostrando {MAX_REPOSITORIES} de {len(paths)} repositórios")
    if unreadable:
        limitations.append(UNREADABLE_LIMITATION.format(count=len(unreadable)))

    return {
        "repositories": [{"path": path, "name": by_path[path]} for path in paths[:MAX_REPOSITORIES]],
        "searched": [str(area) for area in areas],
        "unreadable_directories": sorted(set(unreadable)),
        "truncated": truncated,
        "scope_limitations": limitations,
    }
