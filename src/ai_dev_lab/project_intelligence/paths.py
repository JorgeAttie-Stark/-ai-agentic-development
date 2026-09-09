from pathlib import Path
import os

from .errors import ToolError

GIT_MARKER = ".git"


def is_repository(path):
    """Porta de alcance do servidor: o que tem `.git` é repositório.

    `exists` em vez de `is_dir` de propósito — worktree e submódulo têm `.git`
    como ARQUIVO com uma linha `gitdir:`, e recusá-los excluiria repositórios
    legítimos.
    """
    return os.path.exists(os.path.join(str(path), GIT_MARKER))


def resolve_within(project_root, relative_path):
    # Checagem independente da de containment: `root / absoluto` descarta
    # `root` (comportamento do pathlib), então um absoluto que caia dentro
    # da raiz passaria pelo `relative_to` abaixo sem ser rejeitado.
    if Path(relative_path).is_absolute():
        raise ToolError("caminho absoluto não é permitido")

    root = Path(project_root)
    candidate = Path(os.path.normpath(str(root / relative_path)))
    root_resolved = root.resolve()

    try:
        resolved = candidate.resolve()
        resolved.relative_to(root_resolved)
    except ValueError as error:
        raise ToolError("caminho fora da raiz do projeto") from error

    return resolved

def resolve_requested_root(context, requested):
    """Resolve o `root` pedido pelo cliente contra a fronteira configurada.

    `None` devolve a raiz padrão — o comportamento de todo o histórico do
    servidor, preservado para quem não passa o argumento.

    Um caminho só é aceito se estiver sob algum `--allow-parent`, ou se for a
    própria raiz padrão. A checagem roda sobre o path RESOLVIDO, então symlink
    apontando para fora da fronteira é recusado pelo mesmo mecanismo que já
    protegia `read_file` dentro de uma raiz.

    A mensagem de erro não nomeia os diretórios permitidos: o cliente pediu um
    caminho, e dizer "não é nenhum destes: /Users/..." vazaria a estrutura da
    máquina — o mesmo motivo pelo qual `make_evidence` recusa path absoluto.
    """
    default = context["roots"]["default"]
    if requested is None:
        return default

    if not isinstance(requested, str) or not requested:
        raise ToolError("root deve ser uma string não vazia")

    # Antes de resolver: um nome relativo seria resolvido contra o cwd do
    # PROCESSO, que não tem relação com o que o cliente quis dizer. O cliente
    # real mandou `app-web` e ouviu "não é um diretório" — sintoma errado, e
    # ele desistiu e pediu o caminho ao humano.
    if not requested.startswith("~") and not Path(requested).is_absolute():
        raise ToolError(
            "root deve ser um caminho absoluto — o servidor não resolve nome "
            "relativo; use list_repositories para descobrir os caminhos"
        )

    try:
        expanded = Path(requested).expanduser()
    except RuntimeError as error:
        raise ToolError("root inválido") from None

    resolved = Path(os.path.normpath(str(expanded))).resolve()

    reachable = [default, *context.get("allowed_parents", [])]
    inside = any(resolved == area or _is_within(resolved, area) for area in reachable)
    if not inside:
        raise ToolError(
            "raiz fora do alcance permitido — declare o diretório em "
            "--allow-parent na configuração do servidor"
        )

    if not resolved.is_dir():
        raise ToolError("a raiz pedida não é um diretório")

    # A raiz padrão é isenta: `--root` é decisão explícita de quem sobe o
    # servidor. Já o `root` pedido pelo cliente passa pela porta, porque
    # `--allow-parent $HOME` alcança `~/.ssh`, `~/.config/gh` e
    # `~/.zsh_history` — e `read_file` é uma das tools. Exigir `.git` faz o
    # alcance coincidir com o que foi pedido: repositórios, não a máquina.
    if resolved != default and not is_repository(resolved):
        raise ToolError(
            "a raiz pedida não é um repositório — o servidor só aceita "
            "diretórios com `.git`; use list_repositories para ver quais"
        )

    return resolved


def _is_within(candidate, area):
    try:
        candidate.relative_to(area)
    except ValueError:
        return False
    return True
