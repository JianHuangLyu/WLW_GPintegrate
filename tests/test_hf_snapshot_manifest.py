from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from components.person_a.hf_snapshot_manifest import build_snapshot_manifest
from contracts.paths import RUN_ROOT


class HuggingFaceSnapshotManifestTests(unittest.TestCase):
    def test_manifest_records_revision_size_and_digest(self) -> None:
        with tempfile.TemporaryDirectory(dir=RUN_ROOT) as temp_dir:
            revision = "abc123"
            snapshot = Path(temp_dir) / revision
            snapshot.mkdir()
            (snapshot / "config.json").write_text("{}\n", encoding="utf-8")
            weights = snapshot / "weights"
            weights.mkdir()
            (weights / "model.bin").write_bytes(b"synthetic weights")

            manifest = build_snapshot_manifest(
                snapshot,
                model_id="example/model",
                revision=revision,
            )

        self.assertEqual("example/model", manifest["model_id"])
        self.assertEqual(revision, manifest["revision"])
        self.assertEqual(
            ["config.json", "weights/model.bin"],
            [entry["path"] for entry in manifest["files"]],
        )
        self.assertTrue(all(entry["size"] > 0 for entry in manifest["files"]))
        self.assertTrue(
            all(len(entry["sha256"]) == 64 for entry in manifest["files"])
        )

    def test_manifest_rejects_unpinned_snapshot_directory(self) -> None:
        with tempfile.TemporaryDirectory(dir=RUN_ROOT) as temp_dir:
            snapshot = Path(temp_dir) / "different-revision"
            snapshot.mkdir()
            (snapshot / "config.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match pinned revision"):
                build_snapshot_manifest(
                    snapshot,
                    model_id="example/model",
                    revision="expected-revision",
                )

    def test_export_rejects_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory(dir=RUN_ROOT) as temp_dir:
            parent = Path(temp_dir)
            root = parent / "abc123"
            root.mkdir()
            outside = parent / "outside.bin"
            outside.write_bytes(b"outside")
            try:
                (root / "weights.bin").symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"OS does not permit symlink creation: {exc}")
            with self.assertRaisesRegex(ValueError, "escapes root"):
                build_snapshot_manifest(root, model_id="test/model", revision="abc123")


if __name__ == "__main__":
    unittest.main()
