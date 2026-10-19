"""external-assets.yaml must agree with the README, the configs and component.yaml."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

try:
    import yaml

    HAS_YAML = True
except ImportError:  # PyYAML is not a runtime dependency of Person B
    HAS_YAML = False

PERSON_B = Path(__file__).resolve().parents[1] / "components/person_b"


@unittest.skipUnless(HAS_YAML, "PyYAML is not installed")
class ExternalAssetsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        document = yaml.safe_load((PERSON_B / "external-assets.yaml").read_text(encoding="utf-8"))
        cls.assets = {asset["asset_id"]: asset for asset in document["assets"]}
        cls.readme = (PERSON_B / "README.md").read_text(encoding="utf-8")
        cls.component = (PERSON_B / "component.yaml").read_text(encoding="utf-8")
        cls.dense = json.loads((PERSON_B / "configs/dense.default.json").read_text(encoding="utf-8"))

    def test_required_fields_are_present_for_every_asset(self) -> None:
        for asset in self.assets.values():
            for field in (
                "type",
                "required",
                "version",
                "revision",
                "sha256",
                "size_bytes",
                "logical_path",
                "configured_by",
                "license_or_access_policy",
                "contains_phi",
            ):
                self.assertIn(field, asset, f"{asset['asset_id']} lacks {field}")
            self.assertRegex(asset["sha256"], r"^[0-9a-f]{64}$")

    def test_digests_and_paths_match_the_readme(self) -> None:
        for asset in self.assets.values():
            self.assertIn(asset["sha256"], self.readme, asset["asset_id"])
            self.assertIn(asset["logical_path"], self.readme, asset["asset_id"])

    def test_paths_match_the_default_config(self) -> None:
        by_type = {asset["type"]: asset for asset in self.assets.values()}
        self.assertEqual(
            self.dense["embedding"]["model_path"], by_type["model_weight"]["logical_path"]
        )
        self.assertEqual(
            self.dense["knowledge_base"]["path"], by_type["knowledge_base_index"]["logical_path"]
        )
        self.assertEqual(
            self.dense["knowledge_base"]["knowledge_base_id"],
            by_type["knowledge_base_index"]["asset_id"],
        )

    def test_model_revision_matches_component_yaml(self) -> None:
        self.assertIn(self.assets["medembed-large-v0.1"]["revision"], self.component)

    def test_dependencies_point_at_declared_assets_and_their_digests(self) -> None:
        for asset in self.assets.values():
            for dependency in asset.get("depends_on", []):
                self.assertEqual(
                    self.assets[dependency["asset_id"]]["sha256"], dependency["sha256"]
                )

    def test_per_file_digests_are_listed_for_the_model(self) -> None:
        files = self.assets["medembed-large-v0.1"]["verification"]["required_files_sha256"]
        self.assertIn("model.safetensors", files)
        for digest in files.values():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_unconfirmed_corpus_licence_is_not_hidden(self) -> None:
        policy = self.assets["rag-database-who-breast-tumours-5e"]["license_or_access_policy"]
        self.assertTrue(policy.startswith("UNCONFIRMED"))


if __name__ == "__main__":
    unittest.main()
