from pathlib import Path
import os

from .errors import ToolError


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

    return resolved


def _is_within(candidate, area):
    try:
        candidate.relative_to(area)
    except ValueError:
        return False
    return True
