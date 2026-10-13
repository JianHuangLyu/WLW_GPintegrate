"""Create a file-level integrity manifest for an offline Hugging Face snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from components.person_a.asset_integrity import sha256_file
from contracts.paths import resolve_run_path


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
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file():
            continue
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
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
