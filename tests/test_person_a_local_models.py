from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import os
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from components.person_a.asset_integrity import (
    ExternalAssetIntegrityError, MANIFEST_PATH, load_external_asset_manifest, sha256_file,
)
from components.person_a.hf_snapshot_manifest import build_snapshot_manifest
from components.person_a.local_model_integrity import verify_local_model
from components.person_a.learnable_query_generator import (
    CONDITION_LABELS, TARGET_FORMAT, LearnableSoftPromptGenerator,
    LearnableQueryGenerationError,
)
from components.person_a.medgemma_extractor import MedGemmaExtractor
from contracts.paths import REFERENCE_ROOT, RUN_ROOT, sibling_logical_path
from contracts.runtime import validate_artifact


class LocalModelTests(unittest.TestCase):
    def setUp(self) -> None:
        parent = REFERENCE_ROOT / "person_a/checkpoint"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.revision = "a" * 40
        self.model_id = "example/model"
        # Export from a revision directory, then relocate as deployment does.
        snapshot = self.directory / self.revision
        snapshot.mkdir()
        (snapshot / "config.json").write_text('{}\n', encoding="utf-8")
        (snapshot / "model.safetensors").write_bytes(b"fixed synthetic weights")
        self.tree = build_snapshot_manifest(snapshot, model_id=self.model_id, revision=self.revision)
        self.root = self.directory / "local-model"
        snapshot.rename(self.root)
        self.tree_path = self.directory / "tree.json"
        self.manifest_path = self.directory / "external-assets.yaml"
        self.asset = {
            "name": "synthetic-model",
            "revision": self.revision,
            "source": f"huggingface:{self.model_id}",
            "expected_mount_path": "/" + sibling_logical_path(self.root),
            "tree_manifest": self.tree_path.name,
        }
        self.write_manifest()

    def write_manifest(self) -> None:
        self.tree_path.write_text(json.dumps(self.tree), encoding="utf-8")
        self.asset["tree_manifest_sha256"] = sha256_file(self.tree_path)
        self.manifest_path.write_text(json.dumps({"assets": [self.asset]}), encoding="utf-8")

    def verify(self, path=None, model_id=None, revision=None) -> dict:
        return verify_local_model(
            path or self.root, model_id=model_id or self.model_id,
            revision=revision or self.revision, manifest_path=self.manifest_path,
        )

    def test_materialized_tree_verifies_and_records_identity(self) -> None:
        result = self.verify()
        self.assertTrue(result["integrity_verified"])
        self.assertTrue(result["local_files_only"])
        self.assertEqual(self.revision, result["model_revision"])
        self.assertEqual(self.asset["tree_manifest_sha256"], result["tree_manifest_sha256"])
        self.assertEqual(2, result["file_count"])
        self.assertEqual(64, len(result["tree_sha256"]))

    def test_production_model_configs_have_trusted_pinned_manifests(self) -> None:
        component = MANIFEST_PATH.parent
        assets = load_external_asset_manifest()["assets"]
        report = json.loads((component / "configs/report_decompose.default.json").read_text(encoding="utf-8"))["report_extraction"]["medgemma"]
        query = json.loads((component / "configs/query_generation.learnable.json").read_text(encoding="utf-8"))["backend"]
        for config in (report, query):
            model_id = config.get("model_id", config.get("model_name"))
            entries = [asset for asset in assets if asset.get("source") == f"huggingface:{model_id}"]
            self.assertEqual(1, len(entries))
            entry = entries[0]
            self.assertEqual(config["model_revision"], entry["revision"])
            self.assertEqual("/" + config["model_path"].removeprefix("../"), entry["expected_mount_path"])
            manifest = component / entry["tree_manifest"]
            self.assertEqual(entry["tree_manifest_sha256"], sha256_file(manifest))
            document = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(model_id, document["model_id"])
            self.assertEqual(config["model_revision"], document["revision"])
            self.assertTrue(document["files"])

    def test_missing_extra_size_and_same_size_tamper_fail(self) -> None:
        weights = self.root / "model.safetensors"
        original = weights.read_bytes()
        weights.unlink()
        with self.assertRaisesRegex(ExternalAssetIntegrityError, "missing="):
            self.verify()
        weights.write_bytes(original)
        extra = self.root / "extra.py"
        extra.write_text("unexpected", encoding="utf-8")
        with self.assertRaisesRegex(ExternalAssetIntegrityError, "unexpected="):
            self.verify()
        extra.unlink()
        weights.write_bytes(original + b"!")
        with self.assertRaisesRegex(ExternalAssetIntegrityError, "size mismatch"):
            self.verify()
        weights.write_bytes(b"x" * len(original))
        with self.assertRaisesRegex(ExternalAssetIntegrityError, "SHA-256 mismatch"):
            self.verify()

    def test_wrong_revision_identity_and_undeclared_root_fail(self) -> None:
        with self.assertRaisesRegex(ExternalAssetIntegrityError, "revision mismatch"):
            self.verify(revision="b" * 40)
        with self.assertRaisesRegex(ExternalAssetIntegrityError, "identity mismatch"):
            self.verify(model_id="wrong/model")
        with self.assertRaisesRegex(ExternalAssetIntegrityError, "declared asset"):
            self.verify(path=self.directory)

    def test_changed_manifest_is_not_a_new_trusted_baseline(self) -> None:
        self.tree["files"][0]["sha256"] = "0" * 64
        self.tree_path.write_text(json.dumps(self.tree), encoding="utf-8")
        with self.assertRaisesRegex(ExternalAssetIntegrityError, "manifest SHA-256 mismatch"):
            self.verify()

    def test_manifest_identity_and_revision_are_checked(self) -> None:
        for key in ("model_id", "revision"):
            with self.subTest(key=key):
                original = self.tree[key]
                self.tree[key] = "wrong"
                self.write_manifest()
                with self.assertRaisesRegex(ExternalAssetIntegrityError, "identity/revision mismatch"):
                    self.verify()
                self.tree[key] = original

    def test_manifest_paths_and_duplicates_fail(self) -> None:
        original = deepcopy(self.tree)
        for name in ("../outside", "/absolute", "C:/outside", "..\\outside", "a/../config.json", "a//b", "./config.json"):
            with self.subTest(name=name):
                self.tree = deepcopy(original)
                self.tree["files"][0]["path"] = name
                self.write_manifest()
                with self.assertRaisesRegex(ExternalAssetIntegrityError, "Unsafe"):
                    self.verify()
        self.tree = deepcopy(original)
        self.tree["files"].append(self.tree["files"][0])
        self.write_manifest()
        with self.assertRaisesRegex(ExternalAssetIntegrityError, "Duplicate"):
            self.verify()

    def test_missing_trusted_manifest_fails_closed(self) -> None:
        self.asset["tree_manifest_sha256"] = None
        self.manifest_path.write_text(json.dumps({"assets": [self.asset]}), encoding="utf-8")
        with self.assertRaisesRegex(ExternalAssetIntegrityError, "BLOCKED_MISSING_ASSET"):
            self.verify()

    def test_missing_model_directory_fails_closed(self) -> None:
        hidden = self.directory / "relocated-model"
        self.root.rename(hidden)
        with self.assertRaisesRegex(FileNotFoundError, "BLOCKED_MISSING_ASSET"):
            self.verify()

    def test_preparation_uses_fixed_metadata_before_materialization(self) -> None:
        from components.person_a.prepare_local_models import prepare_local_model

        source = self.directory / "download-source"
        self.root.rename(source)
        requested = []
        original_replace = Path.replace

        def same_filesystem_replace(source_path, destination_path):
            self.assertEqual(source_path.parent, destination_path.parent)
            return original_replace(source_path, destination_path)

        def download(model_id, name, **kwargs):
            self.assertEqual(self.model_id, model_id)
            self.assertEqual(self.revision, kwargs["revision"])
            target = Path(kwargs["local_dir"]) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((source / name).read_bytes())
            requested.append(name)
            return target

        with tempfile.TemporaryDirectory(dir=RUN_ROOT) as stage, \
             patch("components.person_a.prepare_local_models.RUN_ROOT", Path(stage)), \
             patch.object(Path, "replace", same_filesystem_replace):
            result = prepare_local_model("synthetic-model", manifest_path=self.manifest_path, downloader=download)
            self.assertTrue(result["integrity_verified"])
            self.assertEqual(2, len(requested))
            self.assertEqual(set(requested), {path.name for path in self.root.iterdir()})
            self.assertFalse(any(Path(stage).rglob("*.preparing")))
            # A complete matching directory is reused without network calls.
            prepare_local_model("synthetic-model", manifest_path=self.manifest_path, downloader=MagicMock(side_effect=AssertionError("unexpected download")))

    def test_preparation_rejects_untrusted_metadata_and_existing_tamper(self) -> None:
        from components.person_a.prepare_local_models import prepare_local_model

        callback = MagicMock(side_effect=AssertionError("must not download"))
        (self.root / "config.json").write_text("[]\n", encoding="utf-8")
        with tempfile.TemporaryDirectory(dir=RUN_ROOT) as stage, \
             patch("components.person_a.prepare_local_models.RUN_ROOT", Path(stage)):
            with self.assertRaisesRegex(ExternalAssetIntegrityError, "Existing model file"):
                prepare_local_model("synthetic-model", manifest_path=self.manifest_path, downloader=callback)
            self.tree_path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ExternalAssetIntegrityError, "manifest SHA-256 mismatch"):
                prepare_local_model("synthetic-model", manifest_path=self.manifest_path, downloader=callback)
        callback.assert_not_called()

    def test_preparation_rejects_downloaded_tamper(self) -> None:
        from components.person_a.prepare_local_models import prepare_local_model

        self.root.rename(self.directory / "old-model")

        def download(model_id, name, **kwargs):
            target = Path(kwargs["local_dir"]) / name
            target.write_bytes(b"tampered")
            return target

        with tempfile.TemporaryDirectory(dir=RUN_ROOT) as stage, \
             patch("components.person_a.prepare_local_models.RUN_ROOT", Path(stage)):
            with self.assertRaisesRegex(ExternalAssetIntegrityError, "Downloaded model file"):
                prepare_local_model("synthetic-model", manifest_path=self.manifest_path, downloader=download)

    def test_manifest_schema_sizes_and_digests_are_validated(self) -> None:
        original = deepcopy(self.tree)
        for field, value in (("size", -1), ("size", True), ("sha256", "bad")):
            with self.subTest(field=field, value=value):
                self.tree = deepcopy(original)
                self.tree["files"][0][field] = value
                self.write_manifest()
                with self.assertRaises(ExternalAssetIntegrityError):
                    self.verify()
        for value in ([], None):
            self.tree = deepcopy(original)
            self.tree["files"] = value
            self.write_manifest()
            with self.assertRaisesRegex(ExternalAssetIntegrityError, "non-empty"):
                self.verify()

    def test_tree_manifest_itself_cannot_escape_metadata_root(self) -> None:
        outside = self.directory / "outside-manifest.json"
        outside.write_bytes(self.tree_path.read_bytes())
        metadata = self.directory / "metadata"
        metadata.mkdir()
        self.manifest_path = metadata / "external-assets.yaml"
        self.asset["tree_manifest"] = "../outside-manifest.json"
        self.manifest_path.write_text(json.dumps({"assets": [self.asset]}), encoding="utf-8")
        with self.assertRaisesRegex(ExternalAssetIntegrityError, "metadata directory"):
            self.verify()

    @unittest.skipUnless(os.name == "nt", "Windows junction containment regression")
    def test_windows_junction_escape_is_rejected(self) -> None:
        outside = self.directory / "outside-directory"
        outside.mkdir()
        (outside / "weights.bin").write_bytes(b"outside")
        link = self.root / "junction"
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            capture_output=True,
        )
        if result.returncode:
            self.skipTest(f"OS does not permit junction creation: {result.stderr.decode(errors='replace').strip()}")
        try:
            with self.assertRaisesRegex(ValueError, "escapes root"):
                self.verify()
            with self.assertRaisesRegex(ValueError, "escapes root"):
                build_snapshot_manifest(self.root, model_id=self.model_id, revision=self.root.name)
        finally:
            link.rmdir()

    def test_runtime_rejects_file_and_directory_symlink_escape(self) -> None:
        outside = self.directory / "outside"
        outside.mkdir()
        (outside / "data.bin").write_bytes(b"outside")
        for directory in (False, True):
            link = self.root / "escape"
            try:
                link.symlink_to(outside if directory else outside / "data.bin", target_is_directory=directory)
            except OSError as exc:
                self.skipTest(f"OS does not permit symlink creation: {exc}")
            try:
                with self.assertRaisesRegex(ValueError, "escapes root"):
                    self.verify()
            finally:
                link.unlink()

    def test_contained_file_symlink_is_verified(self) -> None:
        link = self.root / "config-copy.json"
        try:
            link.symlink_to(self.root / "config.json")
        except OSError as exc:
            self.skipTest(f"OS does not permit symlink creation: {exc}")
        self.tree["files"].append({"path": link.name, "size": link.stat().st_size, "sha256": sha256_file(link)})
        self.write_manifest()
        self.assertEqual(3, self.verify()["file_count"])

    def test_broken_links_and_contained_directory_links_fail(self) -> None:
        link = self.root / "link"
        try:
            link.symlink_to(self.root / "missing.bin")
        except OSError as exc:
            self.skipTest(f"OS does not permit symlink creation: {exc}")
        with self.assertRaisesRegex(ValueError, "invalid"):
            self.verify()
        link.unlink()
        link.symlink_to(self.root, target_is_directory=True)
        try:
            with self.assertRaisesRegex(ValueError, "directory symlinks"):
                self.verify()
        finally:
            link.unlink()

    def fake_modules(self):
        model = MagicMock()
        model.to.return_value = model
        model.parameters.return_value = []
        model.hf_device_map = {}
        model.get_input_embeddings.return_value = SimpleNamespace(
            embedding_dim=1152, weight=SimpleNamespace(device="cpu", dtype="float32"),
        )
        tokenizer = SimpleNamespace(pad_token=None, eos_token="<eos>")
        transformers = SimpleNamespace(
            AutoTokenizer=MagicMock(), AutoModelForCausalLM=MagicMock(),
            AutoProcessor=MagicMock(), AutoModelForImageTextToText=MagicMock(),
            BitsAndBytesConfig=MagicMock(),
        )
        transformers.AutoTokenizer.from_pretrained.return_value = tokenizer
        transformers.AutoProcessor.from_pretrained.return_value = SimpleNamespace(
            tokenizer=SimpleNamespace(eos_token="<eos>", pad_token_id=0),
        )
        transformers.AutoModelForCausalLM.from_pretrained.return_value = model
        transformers.AutoModelForImageTextToText.from_pretrained.return_value = model
        torch = SimpleNamespace(
            cuda=SimpleNamespace(is_available=lambda: False),
            float32="float32", float16="float16", bfloat16="bfloat16", load=MagicMock(),
        )
        return torch, transformers

    def medgemma(self):
        return MedGemmaExtractor({
            "model_id": self.model_id, "model_revision": self.revision,
            "model_path": str(self.root), "require_cuda": False, "load_in_4bit": False,
        })

    def gemma(self):
        checkpoint = self.directory / "soft-prompt.pt"
        checkpoint.write_bytes(b"synthetic prompt")
        attributes = self.directory / "attributes.json"
        attributes.write_text(json.dumps([{
            "text": "example", "attribute": {"Group": {"Feature": {"Present": "Must_True"}}},
            "attribute_condition_metadata": {
                "target_format": TARGET_FORMAT, "typelevel_sha256": "a" * 64,
                "text_sha256": hashlib.sha256(b"example").hexdigest(),
            },
        }]), encoding="utf-8")
        return LearnableSoftPromptGenerator({
            "model_name": self.model_id, "model_revision": self.revision,
            "model_path": str(self.root), "checkpoint_path": str(checkpoint),
            "attribute_reference_path": str(attributes),
            "asset_integrity": "record_only", "require_cuda": False,
        })

    def checkpoint(self, generator):
        tensor = MagicMock(ndim=2, shape=(64, 1152))
        return {
            "soft_prompt": tensor, "model_name": self.model_id,
            "model_revision": self.revision, "target_format": TARGET_FORMAT,
            "typelevel_sha256": generator.provenance["attribute_reference"]["typelevel_sha256"],
            "chunk_data_sha256": generator.provenance["attribute_reference"]["chunk_data_sha256"],
            "condition_labels": sorted(CONDITION_LABELS),
        }

    def test_both_loaders_use_verified_local_paths_without_token(self) -> None:
        torch, transformers = self.fake_modules()
        for module, loader, factories in (
            ("medgemma_extractor", self.medgemma(), [transformers.AutoProcessor, transformers.AutoModelForImageTextToText]),
            ("learnable_query_generator", self.gemma(), [transformers.AutoTokenizer, transformers.AutoModelForCausalLM]),
        ):
            with self.subTest(module=module):
                if module == "learnable_query_generator":
                    torch.load.return_value = self.checkpoint(loader)
                with patch.dict("sys.modules", {"torch": torch, "transformers": transformers}), \
                     patch.dict("os.environ", {}, clear=True), \
                     patch(f"components.person_a.{module}.verify_local_model", side_effect=self.verify):
                    loader._load()
                for factory in factories:
                    args, kwargs = factory.from_pretrained.call_args
                    self.assertEqual((str(self.root),), args)
                    self.assertTrue(kwargs["local_files_only"])
                    self.assertNotIn("token", kwargs)
                    self.assertNotIn("revision", kwargs)
                provenance = loader.provenance
                integrity = provenance.get("model_integrity", provenance)
                self.assertTrue(integrity["integrity_verified"])

    def test_both_loaders_reject_tamper_before_transformers(self) -> None:
        torch, transformers = self.fake_modules()
        (self.root / "config.json").write_text('[]\n', encoding="utf-8")
        for module, loader in (("medgemma_extractor", self.medgemma()), ("learnable_query_generator", self.gemma())):
            with self.subTest(module=module), \
                 patch.dict("sys.modules", {"torch": torch, "transformers": transformers}), \
                 patch(f"components.person_a.{module}.verify_local_model", side_effect=self.verify):
                with self.assertRaisesRegex(ExternalAssetIntegrityError, "SHA-256 mismatch"):
                    loader._load()
        for factory in (transformers.AutoProcessor, transformers.AutoModelForImageTextToText,
                        transformers.AutoTokenizer, transformers.AutoModelForCausalLM):
            factory.from_pretrained.assert_not_called()

    def test_soft_prompt_model_identity_and_revision_checks_remain(self) -> None:
        torch, transformers = self.fake_modules()
        generator = self.gemma()
        for key in ("model_name", "model_revision"):
            checkpoint = self.checkpoint(generator)
            checkpoint[key] = "wrong"
            torch.load.return_value = checkpoint
            with self.subTest(key=key), \
                 patch.dict("sys.modules", {"torch": torch, "transformers": transformers}), \
                 patch("components.person_a.learnable_query_generator.verify_local_model", side_effect=self.verify):
                with self.assertRaises(LearnableQueryGenerationError):
                    generator._load()

    def test_d_retains_model_verification_only_when_model_is_invoked(self) -> None:
        from components.person_a.report_decompose import build_artifact

        component = Path(__file__).resolve().parents[1] / "components/person_a"
        source = json.loads((component / "examples/report_decompose/case_list.valid.json").read_text(encoding="utf-8"))
        source["DxItem_list"] = ["Histologic_Type"]
        source["case_list"][0]["hospital"] = "CGMH"
        config = json.loads((component / "configs/report_decompose.default.json").read_text(encoding="utf-8"))
        provenance = self.verify()
        fake = SimpleNamespace(
            extract=lambda report, items: {"Histologic_Type": "Atypical ductal hyperplasia"},
            provenance=provenance, generation_count=1,
        )
        with patch("components.person_a.medgemma_extractor.MedGemmaExtractor", return_value=fake):
            artifact = build_artifact(source, config)
        validate_artifact(artifact, "D.DxPairs")
        self.assertEqual(provenance, artifact["payload"]["reference_versions"]["medgemma_report_extraction"])
        source["case_list"][0]["hospital"] = "VGHTC"
        with patch("components.person_a.medgemma_extractor.MedGemmaExtractor") as factory:
            artifact = build_artifact(source, config)
        factory.assert_not_called()
        self.assertNotIn("medgemma_report_extraction", artifact["payload"]["reference_versions"])


if __name__ == "__main__":
    unittest.main()
