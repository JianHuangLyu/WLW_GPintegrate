"""Integrity checks for externally mounted Person A assets."""

from __future__ import annotations

from functools import lru_cache
import hashlib
import hmac
from pathlib import Path
from typing import Any

import yaml

from contracts.paths import sibling_logical_path


MANIFEST_PATH = Path(__file__).with_name("external-assets.yaml")
INTEGRITY_MODES = {"enforce", "record_only"}


class ExternalAssetIntegrityError(ValueError):
    """Raised when a fixed external asset does not match its manifest entry."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@lru_cache(maxsize=None)
def _load_manifest_cached(manifest_path: str) -> dict[str, Any]:
    path = Path(manifest_path)
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("assets"), list):
        raise ExternalAssetIntegrityError(
            f"External asset manifest is invalid: {path}"
        )
    return document


def load_external_asset_manifest(
    manifest_path: str | Path = MANIFEST_PATH,
) -> dict[str, Any]:
    """Load the versioned external-asset manifest."""

    return _load_manifest_cached(str(Path(manifest_path).resolve()))


def _mounted_path(path: Path) -> str:
    return "/" + sibling_logical_path(path)


def _entry_for_path(
    path: Path,
    manifest: dict[str, Any],
) -> dict[str, Any] | None:
    mounted_path = _mounted_path(path)
    for entry in manifest["assets"]:
        if (
            isinstance(entry, dict)
            and entry.get("expected_mount_path") == mounted_path
        ):
            return entry
    return None


def verify_external_asset(
    path: str | Path,
    *,
    integrity_mode: str = "enforce",
    manifest_path: str | Path = MANIFEST_PATH,
) -> dict[str, Any]:
    """Hash an asset and enforce its declared digest when requested.

    ``enforce`` is the production policy: the exact logical mount path must be
    present in ``external-assets.yaml`` and its SHA-256 must match. Synthetic
    tests may opt into ``record_only``; their digest is recorded but they are
    not treated as a fixed production asset.
    """

    mode = str(integrity_mode)
    if mode not in INTEGRITY_MODES:
        raise ValueError(
            f"asset_integrity must be one of {sorted(INTEGRITY_MODES)}, got {mode!r}"
        )

    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Person A external asset was not found: {resolved}")

    actual = sha256_file(resolved)
    manifest = load_external_asset_manifest(manifest_path)
    entry = _entry_for_path(resolved, manifest)
    expected = entry.get("sha256") if entry is not None else None
    matches = (
        isinstance(expected, str)
        and len(expected) == 64
        and hmac.compare_digest(actual, expected.lower())
    )

    if mode == "enforce":
        if entry is None:
            raise ExternalAssetIntegrityError(
                f"External asset is not declared at its mounted path: "
                f"{_mounted_path(resolved)}"
            )
        if not isinstance(expected, str) or len(expected) != 64:
            raise ExternalAssetIntegrityError(
                f"External asset {entry.get('name')!r} has no fixed SHA-256"
            )
        if not matches:
            raise ExternalAssetIntegrityError(
                f"External asset SHA-256 mismatch for {_mounted_path(resolved)}; "
                f"expected {expected.lower()}, got {actual}"
            )

    return {
        "sha256": actual,
        "integrity_mode": mode,
        "integrity_verified": bool(matches and mode == "enforce"),
        "manifest_asset": entry.get("name") if entry is not None else None,
        "manifest_revision": entry.get("revision") if entry is not None else None,
        "expected_sha256": expected.lower() if isinstance(expected, str) else None,
    }
