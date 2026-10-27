"""Where 乙's external assets live, and how they are named in artifacts.

Large assets (embedding model, knowledge base, corpus snapshot) sit under the
sibling ``reference/person_b/`` directory, never in the repository or the image.
Configs and artifacts refer to them by the logical path ``reference/person_b/...``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from contracts.paths import PROJECT_ROOT, resolve_person_reference_path, sibling_logical_path


def resolve_asset(raw_path: str | Path) -> Path:
    """Resolve ``reference/person_b/...`` (or an absolute path) and enforce that boundary."""

    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT.parent / path
    return resolve_person_reference_path("person_b", path)


def logical_path(path: str | Path) -> str:
    """Stable name for provenance, never a host path.

    ``reference/...`` and ``run/...`` for sibling assets, ``repo://...`` for files inside the
    repository (so a checkout under any directory name gives the same artifact).
    """

    resolved = Path(path).resolve()
    try:
        return f"repo://{resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()}"
    except ValueError:
        pass
    try:
        return sibling_logical_path(resolved)
    except ValueError:
        return f"external://{resolved.name}"


def model_identity(embedding_config: dict[str, Any]) -> tuple[Path | None, str, str]:
    """Return ``(local model dir, logical path, sha256)`` for the configured embedder."""

    from components.person_b.dense import directory_sha256

    provider = embedding_config.get("provider", "sentence_transformers")
    if provider == "hashing":  # test-only embedder: there is no model directory
        label = f"hashing:{embedding_config.get('dimension', 256)}"
        return None, "example://hashing-bow", hashlib.sha256(label.encode()).hexdigest()
    model_dir = resolve_asset(embedding_config["model_path"])
    return model_dir, logical_path(model_dir), directory_sha256(model_dir)
