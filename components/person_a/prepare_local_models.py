"""Materialize an authorized pinned model using the component's trusted manifest.

This is an explicit network-enabled preparation command, never an inference
fallback. It does not accept model terms or create credentials.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

from components.person_a.asset_integrity import (
    ExternalAssetIntegrityError, MANIFEST_PATH, load_external_asset_manifest, sha256_file,
)
from components.person_a.local_model_integrity import _expected_files, verify_local_model
from contracts.paths import REFERENCE_ROOT, RUN_ROOT, resolve_person_reference_path, resolve_run_path


def prepare_local_model(
    asset_name: str, *, manifest_path: Path = MANIFEST_PATH,
    downloader: Callable[..., Any] | None = None, token_env: str = "HF_TOKEN",
) -> dict[str, Any]:
    assets = load_external_asset_manifest(manifest_path)["assets"]
    entries = [entry for entry in assets if entry.get("name") == asset_name and entry.get("tree_manifest")]
    if len(entries) != 1:
        raise ExternalAssetIntegrityError("Expected one declared model asset with a trusted tree manifest")
    entry = entries[0]
    metadata_root = Path(manifest_path).resolve().parent
    tree_path = (metadata_root / entry["tree_manifest"]).resolve(strict=True)
    tree_path.relative_to(metadata_root)
    raw = tree_path.read_bytes()
    if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), entry["tree_manifest_sha256"]):
        raise ExternalAssetIntegrityError("Model tree manifest SHA-256 mismatch before preparation")
    tree = json.loads(raw)
    model_id = entry["source"].removeprefix("huggingface:")
    if tree.get("schema_version") != 1 or tree.get("model_id") != model_id or tree.get("revision") != entry["revision"]:
        raise ExternalAssetIntegrityError("Model identity/revision mismatch before preparation")
    files = _expected_files(tree)
    root = resolve_person_reference_path("person_a", REFERENCE_ROOT.parent / entry["expected_mount_path"].lstrip("/"))
    root.relative_to((REFERENCE_ROOT / "person_a/checkpoint").resolve())
    stage = resolve_run_path(RUN_ROOT / "model-preparation" / asset_name / entry["revision"])
    stage.mkdir(parents=True, exist_ok=True)
    root.mkdir(parents=True, exist_ok=True)
    if downloader is None:
        os.environ["HF_HOME"] = str(resolve_run_path(RUN_ROOT / "cache/hf-preparation"))
        os.environ["HF_HUB_OFFLINE"] = "0"
        from huggingface_hub import hf_hub_download
        downloader = hf_hub_download
    for name, expected in files.items():
        destination = root / name
        destination.resolve().relative_to(root)
        if destination.exists():
            if destination.stat().st_size != expected["size"] or sha256_file(destination) != expected["sha256"]:
                raise ExternalAssetIntegrityError(f"Existing model file differs from trusted metadata: {name}")
            continue
        print(f"Preparing {asset_name}: {name}", flush=True)
        source = Path(downloader(
            model_id, name, revision=entry["revision"], local_dir=str(stage),
            token=os.environ.get(token_env) or False,
        )).resolve(strict=True)
        source.relative_to(stage.resolve())
        if source.stat().st_size != expected["size"] or sha256_file(source) != expected["sha256"]:
            raise ExternalAssetIntegrityError(f"Downloaded model file differs from trusted metadata: {name}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        # /run and /reference are separate Docker bind mounts. Publish from a
        # temporary file on the destination filesystem, after checking its bytes.
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.", suffix=".preparing", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            shutil.copyfile(source, temporary)
            if temporary.stat().st_size != expected["size"] or sha256_file(temporary) != expected["sha256"]:
                raise ExternalAssetIntegrityError(f"Materialized model file differs from trusted metadata: {name}")
            temporary.replace(destination)
            source.unlink()
        finally:
            temporary.unlink(missing_ok=True)
    return verify_local_model(root, model_id=model_id, revision=entry["revision"], manifest_path=manifest_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", required=True, choices=("gemma-query-generator", "medgemma-report-extractor"))
    parser.add_argument("--token-env", default="HF_TOKEN")
    args = parser.parse_args()
    print(json.dumps(prepare_local_model(args.asset, token_env=args.token_env), indent=2))


if __name__ == "__main__":
    main()
