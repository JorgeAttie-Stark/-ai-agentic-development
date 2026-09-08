"""Entrypoint do servidor: `python3 -m ai_dev_lab.project_intelligence [--root PATH]`.

Casca fina — toda a lógica testável vive em `config.py` e `protocol.py`. Este
módulo só lê `sys.argv`/`os.getcwd()`, resolve a configuração e sobe o loop
stdio.
"""
import logging
import os
import sys

from ai_dev_lab.project_intelligence import protocol
from ai_dev_lab.project_intelligence.config import ConfigError, build_context, resolve_project_root


def main():
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

    try:
        project_root = resolve_project_root(sys.argv[1:], os.getcwd())
    except ConfigError as error:
        # Erro de configuração: mensagem de operador via stderr, processo não
        # sobe. Nunca trafega pelo protocolo MCP.
        print(f"project-intelligence: {error}", file=sys.stderr)
        sys.exit(1)

    context = build_context(project_root)
    protocol.serve_stdio(sys.stdin, sys.stdout, context)


if __name__ == "__main__":
    main()
