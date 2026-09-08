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