from pathlib import Path
import os


def resolve_within(project_root, relative_path):
    root = Path(project_root)
    candidate = Path(os.path.normpath(str(root / relative_path)))

    root_resolved = root.resolve()

    try:
        candidate.resolve().relative_to(root_resolved)
    except ValueError:
        raise ValueError("Path is outside project root")

    return candidate