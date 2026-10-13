from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from components.person_a.asset_integrity import (
    ExternalAssetIntegrityError,
    sha256_file,
    verify_external_asset,
)
from contracts.paths import REFERENCE_ROOT, sibling_logical_path


class PersonAAssetIntegrityTests(unittest.TestCase):
    def _manifest(self, path: Path, sha256: str) -> dict:
        return {
            "schema_version": 1,
            "owner": "person_a",
            "assets": [
                {
                    "name": "test-asset",
                    "revision": "test-v1",
                    "sha256": sha256,
                    "license": "synthetic-test",
                    "expected_mount_path": "/" + sibling_logical_path(path),
                }
            ],
        }

    def test_enforce_accepts_exact_digest_and_rejects_modified_file(self) -> None:
        parent = REFERENCE_ROOT / "person_a"
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temp_dir:
            directory = Path(temp_dir)
            asset = directory / "asset.json"
            asset.write_text('{"version": 1}\n', encoding="utf-8")
            manifest = directory / "external-assets.yaml"
            manifest.write_text(
                json.dumps(self._manifest(asset, sha256_file(asset))),
                encoding="utf-8",
            )

            provenance = verify_external_asset(asset, manifest_path=manifest)
            self.assertTrue(provenance["integrity_verified"])
            self.assertEqual("test-v1", provenance["manifest_revision"])

            asset.write_text('{"version": 2}\n', encoding="utf-8")
            with self.assertRaisesRegex(
                ExternalAssetIntegrityError, "SHA-256 mismatch"
            ):
                verify_external_asset(asset, manifest_path=manifest)

    def test_enforce_rejects_undeclared_asset(self) -> None:
        parent = REFERENCE_ROOT / "person_a"
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temp_dir:
            directory = Path(temp_dir)
            declared = directory / "declared.json"
            undeclared = directory / "undeclared.json"
            declared.write_text("{}\n", encoding="utf-8")
            undeclared.write_text("{}\n", encoding="utf-8")
            manifest = directory / "external-assets.yaml"
            manifest.write_text(
                json.dumps(self._manifest(declared, sha256_file(declared))),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ExternalAssetIntegrityError, "not declared"
            ):
                verify_external_asset(undeclared, manifest_path=manifest)

            provenance = verify_external_asset(
                undeclared,
                integrity_mode="record_only",
                manifest_path=manifest,
            )
            self.assertFalse(provenance["integrity_verified"])
            self.assertEqual("record_only", provenance["integrity_mode"])


if __name__ == "__main__":
    unittest.main()
