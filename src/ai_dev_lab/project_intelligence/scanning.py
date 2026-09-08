"""Primitivas de varredura compartilhadas pelas camadas de análise.

Extraído quando surgiu o terceiro consumidor. Antes disso, `understanding.py`
expunha `_iter_project_files` e `_read_text` como privados e `inference.py` os
importava — o que fazia o contrato público de `understanding` mentir: ela não
podia refatorar essas funções sem quebrar outra camada.

Aqui os nomes são públicos de propósito. Uma camada de análise depender de uma
primitiva compartilhada é a direção certa; depender dos internals de outra
camada de análise não é.

`MAX_FINDINGS` mora aqui pelo mesmo motivo: estava duplicado em dois módulos,
dois nomes iguais com dois valores iguais e nenhum vínculo entre eles.
"""
from __future__ import annotations

import os
from pathlib import Path

from .exploration import (
    MAX_FILE_SIZE_FOR_LINE_COUNT,
    _load_gitignore_patterns,
    _matches_any_gitignore_pattern,
    _prune_gitignore_dirs,
    _walk_pruned,
)
from .findings import validate_finding

# Teto de findings de UMA resposta, compartilhado por toda tool interpretativa.
# Cada handler decide o que fazer ao atingi-lo; o valor é um só.
MAX_FINDINGS = 300


def relative_posix(path, project_root):
    return Path(path).relative_to(project_root).as_posix()


def iter_project_files(project_root, counters):
    """Arquivos regulares da raiz, com `.git` e o `.gitignore` de topo aplicados.

    Reusa integralmente o mecanismo de poda da Camada Exploração — nenhuma
    lógica de `.gitignore` é reimplementada.
    """
    patterns = _load_gitignore_patterns(project_root) or []

    for dirpath, dirnames, filenames in _walk_pruned(project_root, counters):
        if patterns:
            _prune_gitignore_dirs(dirnames, dirpath, project_root, patterns)

        # Ordem determinística. Sem isto a travessia segue a ordem do
        # filesystem, e quando um teto de findings corta, *quais* arquivos
        # entram varia por máquina e por execução — o consumidor recebe um
        # subconjunto arbitrário e irreprodutível.
        dirnames.sort()
        for filename in sorted(filenames):
            relative_file = relative_posix(Path(dirpath, filename), project_root)
            if patterns and _matches_any_gitignore_pattern(patterns, filename, relative_file):
                continue

            file_path = os.path.join(dirpath, filename)
            # `isfile` antes de qualquer `open()` — FIFO sem writer não bloqueia.
            if not os.path.isfile(file_path):
                counters["unreadable_entries_skipped"] += 1
                continue

            yield file_path, relative_file


def read_text(file_path):
    """Texto do arquivo, ou `None` se binário, grande demais ou ilegível.

    Colapsa três causas num só `None` de propósito: o chamador conta como
    "entrada ilegível" e segue. Distinguir as três exigiria três contadores em
    cada tool, e nenhuma delas ramifica por causa.
    """
    try:
        if os.path.getsize(file_path) > MAX_FILE_SIZE_FOR_LINE_COUNT:
            return None
        with open(file_path, "rb") as handle:
            raw = handle.read()
    except OSError:
        return None

    if b"\x00" in raw[:8192]:
        return None
    return raw.decode("utf-8", errors="ignore")


def validated(findings):
    """Revalida todo finding antes de ele ir para a wire.

    `make_finding` já valida na construção; isto fecha o caminho de quem montar
    o dict à mão. Custo O(n) sobre lista já limitada por teto.
    """
    for finding in findings:
        validate_finding(finding)
    return findings
