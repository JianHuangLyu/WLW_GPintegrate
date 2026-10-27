"""Fail-closed verification of versioned, self-contained local model trees."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from typing import Any

from components.person_a.asset_integrity import (
    ExternalAssetIntegrityError,
    MANIFEST_PATH,
    load_external_asset_manifest,
    sha256_file,
)
from components.person_a.hf_snapshot_manifest import model_tree_files
from contracts.paths import REFERENCE_ROOT, resolve_person_reference_path, sibling_logical_path


def _fail(message: str) -> None:
    raise ExternalAssetIntegrityError(message)


def _digest(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _expected_files(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = document.get("files")
    if not isinstance(entries, list) or not entries:
        _fail("Model tree manifest must contain a non-empty files list")
    expected = {}
    for entry in entries:
        if not isinstance(entry, dict):
            _fail("Invalid model tree manifest file entry")
        name = entry.get("path")
        if (
            not isinstance(name, str)
            or not name
            or "\\" in name
            or ":" in name
            or "\x00" in name
            or PurePosixPath(name).is_absolute()
            or PureWindowsPath(name).drive
            or any(part in {"", ".", ".."} for part in name.split("/"))
        ):
            _fail(f"Unsafe model tree manifest path: {name!r}")
        if name in expected:
            _fail(f"Duplicate model tree manifest path: {name}")
        if type(entry.get("size")) is not int or entry["size"] < 0:
            _fail(f"Invalid model file size: {name}")
        if not _digest(entry.get("sha256")):
            _fail(f"Invalid model file SHA-256: {name}")
        expected[name] = entry
    return expected


def verify_local_model(
    model_path: str | Path,
    *,
    model_id: str,
    revision: str,
    manifest_path: str | Path = MANIFEST_PATH,
) -> dict[str, Any]:
    """Validate against a trusted manifest shipped with the component.

    Model integrity cannot be disabled via single-file ``record_only`` mode.
    Expected metadata comes from the versioned code, never the mounted model.
    """
    root = resolve_person_reference_path("person_a", model_path)
    root.relative_to((REFERENCE_ROOT / "person_a/checkpoint").resolve())
    mounted = "/" + sibling_logical_path(root)
    assets = load_external_asset_manifest(manifest_path)["assets"]
    entries = [entry for entry in assets if isinstance(entry, dict)
               and entry.get("expected_mount_path") == mounted]
    if len(entries) != 1:
        _fail(f"Local model path must have exactly one declared asset: {mounted}")
    asset = entries[0]
    if not revision or asset.get("revision") != revision:
        _fail(f"Local model revision mismatch for {mounted}")
    if asset.get("source") != f"huggingface:{model_id}":
        _fail(f"Local model identity mismatch for {mounted}")
    manifest_name = asset.get("tree_manifest")
    expected_sha = asset.get("tree_manifest_sha256")
    if not isinstance(manifest_name, str) or not _digest(expected_sha):
        _fail(f"BLOCKED_MISSING_ASSET: {model_id} has no trusted fixed tree manifest")
    metadata_root = Path(manifest_path).resolve().parent
    manifest_file = (metadata_root / manifest_name).resolve(strict=True)
    try:
        manifest_file.relative_to(metadata_root)
    except ValueError:
        _fail("Model tree manifest must remain inside the component metadata directory")
    # Hash and parse the same bytes; do not re-open after verification.
    manifest_bytes = manifest_file.read_bytes()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    if not hmac.compare_digest(manifest_sha, expected_sha):
        _fail(f"Model tree manifest SHA-256 mismatch for {model_id}")
    document = json.loads(manifest_bytes)
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        _fail("Invalid model tree manifest schema")
    if document.get("model_id") != model_id or document.get("revision") != revision:
        _fail(f"Model tree manifest identity/revision mismatch for {model_id}")
    expected = _expected_files(document)
    if not root.is_dir():
        raise FileNotFoundError(f"BLOCKED_MISSING_ASSET: local model directory not found: {root}")
    actual = model_tree_files(root)
    missing = sorted(expected.keys() - actual.keys())
    extra = sorted(actual.keys() - expected.keys())
    if missing or extra:
        _fail(f"Model tree file set mismatch; missing={missing}, unexpected={extra}")
    for name, entry in expected.items():
        path = actual[name]
        if path.stat().st_size != entry["size"]:
            _fail(f"Model file size mismatch: {name}")
        if not hmac.compare_digest(sha256_file(path), entry["sha256"]):
            _fail(f"Model file SHA-256 mismatch: {name}")
    # Stable content identity, independent of export formatting or host paths.
    tree_sha = hashlib.sha256(json.dumps(
        sorted(expected.values(), key=lambda entry: entry["path"]),
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return {
        "model_id": model_id,
        "model_revision": revision,
        "model_path": mounted,
        "manifest_asset": asset.get("name"),
        "tree_manifest": manifest_name,
        "tree_manifest_sha256": manifest_sha,
        "tree_sha256": tree_sha,
        "file_count": len(expected),
        "total_size_bytes": sum(entry["size"] for entry in expected.values()),
        "integrity_mode": "enforce",
        "integrity_verified": True,
        "local_files_only": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a declared local model before inference")
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    print(json.dumps(verify_local_model(
        args.model_path, model_id=args.model_id, revision=args.revision,
    ), indent=2))


if __name__ == "__main__":
    main()
