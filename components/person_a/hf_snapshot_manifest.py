"""Create a file-level integrity manifest for an offline Hugging Face snapshot."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
from typing import Any

from components.person_a.asset_integrity import sha256_file
from contracts.paths import resolve_run_path


def model_tree_files(root: Path) -> dict[str, Path]:
    """List regular files, rejecting escapes and directory links/cycles.

    Contained file symlinks are allowed. HF cache links to blobs outside the
    snapshot must first be materialized into a self-contained model directory.
    """
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"Model root is not a directory: {root}")
    files: dict[str, Path] = {}

    def walk_error(error: OSError) -> None:
        raise error

    for directory, dirs, names in os.walk(root, followlinks=False, onerror=walk_error):
        for name in sorted(dirs + names):
            path = Path(directory) / name
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(root)
            except (ValueError, OSError, RuntimeError) as exc:
                raise ValueError(f"Model path escapes root or is invalid: {path}") from exc
            if name in dirs:
                reparse = getattr(path.lstat(), "st_file_attributes", 0) & getattr(
                    stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
                )
                if path.is_symlink() or reparse:
                    raise ValueError(f"Model directory symlinks/junctions are not allowed: {path}")
                continue
            if not stat.S_ISREG(resolved.stat().st_mode):
                raise ValueError(f"Model path is not a regular file: {path}")
            files[path.relative_to(root).as_posix()] = resolved
    return dict(sorted(files.items()))


def build_snapshot_manifest(
    snapshot: str | Path,
    *,
    model_id: str,
    revision: str,
) -> dict[str, Any]:
    root = Path(snapshot).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Hugging Face snapshot directory was not found: {root}")
    if root.name != revision:
        raise ValueError(
            f"Snapshot directory {root.name!r} does not match pinned revision "
            f"{revision!r}"
        )

    files: list[dict[str, Any]] = []
    for relative, path in model_tree_files(root).items():
        files.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    if not files:
        raise ValueError(f"Hugging Face snapshot contains no files: {root}")

    return {
        "schema_version": 1,
        "model_id": model_id,
        "revision": revision,
        "files": files,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export size and SHA-256 for every file in one HF snapshot"
    )
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    snapshot = resolve_run_path(args.snapshot)
    output = resolve_run_path(args.output)
    manifest = build_snapshot_manifest(
        snapshot,
        model_id=args.model_id,
        revision=args.revision,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote Hugging Face snapshot manifest -> {output}")


if __name__ == "__main__":
    main()
