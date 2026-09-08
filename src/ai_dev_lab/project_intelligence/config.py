"""Resolução do `projectRoot` a partir de argumentos de CLI e do `cwd` do processo.

Função pura: recebe `argv`/`cwd` como parâmetros, nunca lê `sys.argv`/`os.getcwd()`
diretamente. Isso é o que torna a resolução testável sem subprocess (ver
docs/plan-project-intelligence-mcp.md:279-283).
"""
import argparse
from pathlib import Path


class ConfigError(Exception):
    """Falha de configuração do servidor — mensagem de operador, via stderr.

    Pode incluir o path absoluto: nunca trafega pelo protocolo MCP.
    """


def _build_arg_parser():
    parser = argparse.ArgumentParser(prog="project-intelligence", add_help=False)
    parser.add_argument("--root", default=None)
    return parser


def resolve_project_root(argv, cwd):
    """Resolve o `projectRoot`: `--root` tem precedência sobre `cwd`.

    `cwd` é o mecanismo padrão da v1: o cliente MCP já controla o diretório de
    trabalho do processo que ele lança. `--root` é override opcional, sempre
    resolvido contra `cwd` quando relativo.
    """
    args = _build_arg_parser().parse_args(argv)
    raw_root = args.root if args.root is not None else cwd

    # `expanduser()` precisa rodar antes do join: só expande `~` quando ele é
    # o primeiro componente do path, e depois de `Path(cwd, raw_root)` nunca
    # mais é (cwd já é absoluto). Sem isso, `--root ~/projeto` vira
    # `<cwd>/~/projeto` — código morto que nunca dispara.
    #
    # `~usuario` com usuário inexistente no sistema levanta `RuntimeError`
    # (não `ConfigError`) — `--root` vem de `claude_desktop_config.json`
    # escrito à mão, sem shell validando nada, então um typo aqui precisa
    # virar a mesma mensagem de operador das outras falhas de configuração,
    # não um traceback cru.
    try:
        raw_root = Path(raw_root).expanduser()
    except RuntimeError as error:
        raise ConfigError(f"projectRoot inválido: {error}") from error

    # Path(cwd, raw_root) descarta `cwd` automaticamente se `raw_root` já for
    # absoluto — cobre os dois casos (default e override) com uma única linha.
    project_root = Path(cwd, raw_root).resolve()

    if not project_root.exists():
        raise ConfigError(f"projectRoot não existe: {project_root}")
    if not project_root.is_dir():
        raise ConfigError(f"projectRoot não é um diretório: {project_root}")

    return project_root


def build_context(project_root):
    """Monta o `context` do servidor — mapeamento de raízes, não `Path` solto.

    Uma entrada só hoje ("default"); a costura para múltiplos projetos é a
    forma do dict, não lógica adicional (docs/plan-project-intelligence-mcp.md:181-189).
    `initialized` começa `False`: só `protocol.dispatch` o marca `True`, depois
    de responder `initialize` com sucesso.
    """
    return {"roots": {"default": project_root}, "initialized": False}
