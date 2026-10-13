from __future__ import annotations

import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

from PIL import Image


HAS_TORCH = importlib.util.find_spec("torch") is not None

VOCABULARY = {
    "attributes": {
        "Architecture": {"Pattern": ["N/A", "Solid", "Cribriform"]},
        "Cellular_and_Nuclear": {"Chromatin": ["Regular", "Hyperchromatic"]},
    },
    "multi_select_attributes": ["Pattern"],
    "prompt_descriptions": {"General_Label_Rules": {"N/A": "Not assessable."}},
}
SETTINGS = {
    "image_score_weight": 0.42,
    "text_score_weight": 0.18,
    "example_score_weight": 0.4,
    "use_custom_text_prompt": True,
    "use_example_prototypes": True,
    "multi_select_margin": 0.03,
    "copy_na_labels": True,
    "enable_prompt_chunking": True,
    "token_safety_margin": 2,
    "fallback_words_per_chunk": 35,
}
TEMPLATE = "Attribute: {attribute}. Label: {option}. Visual definition: {description}"


class _FakeEncoder:
    max_text_tokens = 77

    def encode_texts(self, texts):
        import torch
        import torch.nn.functional as F

        rows = []
        for text in texts:
            seed = int(hashlib.sha256(text.encode()).hexdigest()[:12], 16)
            rows.append(torch.randn(8, generator=torch.Generator().manual_seed(seed)))
        return F.normalize(torch.stack(rows), dim=-1)

    def encode_image(self, image):
        import torch
        import torch.nn.functional as F

        red = image.convert("RGB").getpixel((0, 0))[0] / 255.0
        return F.normalize(torch.tensor([[red, 1.0 - red, 0.5, 0, 0, 0, 0, 0.1]]), dim=-1)

    def get_text_token_counts(self, texts):
        return [len(text.split()) for text in texts]


@unittest.skipUnless(HAS_TORCH, "torch is not installed")
class VisualAttributeExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        from components.person_d import visual_attribute_extraction as extraction

        self.extraction = extraction
        self.vocabulary = extraction.load_vocabulary(VOCABULARY)
        self.settings = extraction.ExtractionSettings.from_config(SETTINGS)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.example_dir = Path(temp.name) / "ROI_Analysis"
        option_dir = self.example_dir / "Architecture" / "Pattern" / "Solid"
        option_dir.mkdir(parents=True)
        Image.new("RGB", (4, 4), (250, 0, 0)).save(option_dir / "solid.png")

    def _classifier(self):
        return self.extraction.AttributeClassifier(
            _FakeEncoder(),
            vocabulary=self.vocabulary,
            settings=self.settings,
            option_prompt_template=TEMPLATE,
            custom_text_prompts=["A histopathology ROI image."],
            example_dir=self.example_dir,
        )

    def test_missing_example_folders_are_recorded_not_fatal(self) -> None:
        metadata = self._classifier().example_metadata
        self.assertEqual(1, metadata["readable_example_images"])
        self.assertIn("Cellular_and_Nuclear/Chromatin/Regular", metadata["options_without_examples"])

    def test_unreadable_example_image_fails(self) -> None:
        (self.example_dir / "Architecture" / "Pattern" / "Solid" / "broken.png").write_bytes(b"x")
        with self.assertRaisesRegex(RuntimeError, "Unreadable Person D example image"):
            self._classifier()

    def test_multi_select_drops_na_when_other_options_tie(self) -> None:
        import torch

        classifier = self._classifier()
        options = ["N/A", "Solid", "Cribriform"]
        self.assertEqual(
            ["Solid", "Cribriform"],
            classifier._predict_multi(options, torch.tensor([0.50, 0.51, 0.49])),
        )
        self.assertEqual(["N/A"], classifier._predict_multi(options, torch.tensor([0.9, 0.1, 0.1])))

    def test_consistent_labels_require_model_agreement(self) -> None:
        plip = {
            "Architecture": {"Pattern": {"prediction": ["Solid", "Cribriform"]}},
            "Cellular_and_Nuclear": {"Chromatin": {"prediction": "Hyperchromatic"}},
        }
        conch = {
            "Architecture": {"Pattern": {"prediction": ["Cribriform"]}},
            "Cellular_and_Nuclear": {"Chromatin": {"prediction": "Regular"}},
        }
        self.assertEqual(
            {
                "Architecture": {"Pattern": ["Cribriform"]},
                "Cellular_and_Nuclear": {"Chromatin": []},
            },
            self.extraction.get_consistent_labels(self.vocabulary, plip, conch, True),
        )

    def test_predict_one_returns_prediction_and_scores_for_every_attribute(self) -> None:
        result = self._classifier().predict_one(Image.new("RGB", (4, 4), (250, 0, 0)))
        self.assertEqual({"Pattern"}, set(result["Architecture"]))
        self.assertEqual(set(VOCABULARY["attributes"]["Architecture"]["Pattern"]),
                         set(result["Architecture"]["Pattern"]["scores"]))
        self.assertIn(result["Cellular_and_Nuclear"]["Chromatin"]["prediction"], ["Regular", "Hyperchromatic"])

    def test_weight_sha256_mismatch_fails(self) -> None:
        weight = self.example_dir.parent / "weights.bin"
        weight.write_bytes(b"weights")
        self.extraction.verify_sha256(weight, None, "CONCH")
        self.extraction.verify_sha256(weight, hashlib.sha256(b"weights").hexdigest(), "CONCH")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            self.extraction.verify_sha256(weight, "0" * 64, "CONCH")

    def test_example_tree_digest_is_enforced(self) -> None:
        from components.person_d.assets import tree_sha256

        attributes = VOCABULARY["attributes"]
        _, digest = tree_sha256(self.example_dir)
        self.assertEqual(
            {"file_count": 1, "usable_file_count": 1},
            self.extraction.verify_example_tree(self.example_dir, digest, attributes),
        )
        Image.new("RGB", (4, 4)).save(self.example_dir / "Architecture" / "Pattern" / "Solid" / "extra.png")
        with self.assertRaisesRegex(ValueError, r"example tree \(2 files\) SHA-256 mismatch"):
            self.extraction.verify_example_tree(self.example_dir, digest, attributes)

    def test_example_file_outside_an_option_folder_fails(self) -> None:
        from components.person_d.assets import tree_sha256

        attributes = VOCABULARY["attributes"]
        Image.new("RGB", (4, 4)).save(self.example_dir / "Architecture" / "Pattern" / "stray.png")
        _, digest = tree_sha256(self.example_dir)
        with self.assertRaisesRegex(ValueError, "1 file.*Architecture/Pattern/stray.png"):
            self.extraction.verify_example_tree(self.example_dir, digest, attributes)

    def test_prompt_asset_digest_is_enforced(self) -> None:
        import json

        from contracts.paths import REFERENCE_ROOT

        directory = REFERENCE_ROOT / "person_d" / "template_ref"
        directory.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=directory)
        self.addCleanup(temp.cleanup)
        prompts = Path(temp.name) / "prompts.json"
        prompts.write_text(json.dumps(VOCABULARY), encoding="utf-8")
        config = {
            "prompts_path": str(prompts),
            "prompts_sha256": hashlib.sha256(prompts.read_bytes()).hexdigest(),
        }
        self.assertEqual(VOCABULARY, self.extraction.load_prompt_document(config)[1])
        with self.assertRaisesRegex(ValueError, "prompt asset SHA-256 mismatch"):
            self.extraction.load_prompt_document({**config, "prompts_sha256": "0" * 64})
        with self.assertRaisesRegex(ValueError, "prompts_sha256"):
            self.extraction.load_prompt_document({"prompts_path": str(prompts)})

    def test_cuda_request_without_cuda_fails(self) -> None:
        import torch

        if torch.cuda.is_available():
            self.skipTest("CUDA is available")
        with self.assertRaisesRegex(RuntimeError, "CUDA is not available"):
            self.extraction.load_extractor({}, "cuda")


if __name__ == "__main__":
    unittest.main()
