"""The committed Person B examples must stay reproducible from their own inputs."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from components.person_b import dense
from components.person_b.assets import model_identity
from components.person_b.knowledge_retrieval import _section_candidates, build_dense_artifact
from components.person_b.prepare_literature import build_literature_artifact_from_rag_database
from contracts.runtime import validate_artifact

try:
    import numpy  # noqa: F401

    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

ROOT = Path(__file__).resolve().parents[1]
PERSON_B = ROOT / "components/person_b"
PREPARE = PERSON_B / "examples/prepare_literature"
RETRIEVAL = PERSON_B / "examples/knowledge_retrieval"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class PrepareLiteratureExampleTests(unittest.TestCase):
    def test_source_converts_to_the_expected_a(self) -> None:
        config = _load(PREPARE / "config.example.json")
        artifact = build_literature_artifact_from_rag_database(
            PREPARE / "source.synthetic", config
        )
        expected = _load(PREPARE / "A_literature.expected.json")
        validate_artifact(expected, "A.Literature")
        self.assertEqual(expected, artifact)

    def test_empty_placeholder_is_skipped_and_none_is_kept(self) -> None:
        expected = _load(PREPARE / "A_literature.expected.json")
        self.assertEqual(5, expected["payload"]["corpus"]["literature_count"])
        texts = [
            section["text"]
            for item in expected["payload"]["literature_list"]
            for section in item["sections"]
        ]
        self.assertEqual(5, texts.count("None"))

    def test_retrieval_input_is_the_same_a(self) -> None:
        self.assertEqual(
            _load(PREPARE / "A_literature.expected.json"),
            _load(RETRIEVAL / "A_literature.valid.json"),
        )

    def test_example_configs_match_the_loadable_copies_in_configs(self) -> None:
        self.assertEqual(
            _load(PREPARE / "config.example.json"),
            _load(PERSON_B / "configs/example.rag_database.json"),
        )
        self.assertEqual(
            _load(RETRIEVAL / "config.example.json"),
            _load(PERSON_B / "configs/example.dense.hashing.json"),
        )


@unittest.skipUnless(HAS_NUMPY, "dense mode needs numpy")
class KnowledgeRetrievalExampleTests(unittest.TestCase):
    def test_f_is_reproduced_from_the_example_inputs(self) -> None:
        literature = _load(RETRIEVAL / "A_literature.valid.json")
        d_artifact = _load(RETRIEVAL / "D_dx_pairs.valid.json")
        config = _load(RETRIEVAL / "config.example.json")
        expected = _load(RETRIEVAL / "F_chunks.expected.json")
        validate_artifact(literature, "A.Literature")
        validate_artifact(d_artifact, "D.DxPairs")
        validate_artifact(expected, "F.Chunks")

        model_dir, model_logical, model_sha = model_identity(config["embedding"])
        embedder = dense.make_embedder(config["embedding"], model_dir)
        candidates = _section_candidates(literature)
        with tempfile.TemporaryDirectory() as tmp:
            kb = Path(tmp) / "kb"
            dense.build_knowledge_base(
                kb,
                literature,
                candidates,
                embedder,
                knowledge_base_id=config["knowledge_base"]["knowledge_base_id"],
                provider="hashing",
                model_logical_path=model_logical,
                model_sha256=model_sha,
                dtype=None,
                builder=config["component_version"],
            )
            actual = build_dense_artifact(
                literature,
                d_artifact,
                config,
                knowledge_base_dir=kb,
                model_dir=model_dir,
                model_sha256=model_sha,
                model_logical_path=model_logical,
            )

        # Environment-dependent by design: where the index lives and its npy byte digest.
        for artifact in (actual, expected):
            artifact["payload"]["knowledge_base"].pop("archive_path")
            artifact["payload"]["knowledge_base"].pop("archive_sha256")
        actual_chunks = actual["payload"].pop("chunks")
        expected_chunks = expected["payload"].pop("chunks")
        self.assertEqual(expected, actual)
        self.assertEqual(len(expected_chunks), len(actual_chunks))
        for want, got in zip(expected_chunks, actual_chunks):
            self.assertAlmostEqual(want.pop("dense_score"), got.pop("dense_score"), places=5)
            self.assertAlmostEqual(want.pop("relevance_score"), got.pop("relevance_score"), places=3)
            self.assertEqual(want, got)  # same sections, same order, same ranks

    def test_expected_f_has_the_three_chunks_person_a_needs(self) -> None:
        expected = _load(RETRIEVAL / "F_chunks.expected.json")
        chunks = expected["payload"]["chunks"]
        self.assertEqual([1, 2, 3], [c["retrieval_rank"] for c in chunks])
        self.assertEqual(
            {"Invasive breast carcinoma of no special type"},
            {c["literature_title"] for c in chunks},
        )


if __name__ == "__main__":
    unittest.main()
