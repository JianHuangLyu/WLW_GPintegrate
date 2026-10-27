from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from components.person_b import dense
from components.person_b.assets import model_identity
from components.person_b.knowledge_retrieval import (
    _section_candidates,
    build_dense_artifact,
)
from components.person_b.prepare_literature import build_literature_artifact_from_rag_database
from contracts.runtime import validate_artifact

try:
    import numpy  # noqa: F401

    HAS_NUMPY = True
except ImportError:  # dense mode is optional; mode=example stays stdlib-only
    HAS_NUMPY = False

DISEASES = {
    "UDH": "Usual ductal hyperplasia",
    "ADH": "Atypical ductal hyperplasia",
    "DCIS": "Ductal carcinoma in situ",
    "FEA": "Columnar cell lesions, including flat epithelial atypia",
    "IC": "Invasive breast carcinoma of no special type",
}
SECTIONS = ["Histopathology", "Cytology", "Essential and desirable diagnostic criteria"]

CONFIG = {
    "component_version": "person-b/test:0",
    "mode": "dense",
    "knowledge_base": {"knowledge_base_id": "kb-test", "path": "unused-in-tests"},
    "embedding": {"provider": "hashing", "dimension": 256, "max_tokens": 512, "query_max_tokens": 128},
    "retrieval": {
        "dx_items": ["Histologic_Type"],
        "top_k": 3,
        "candidate_k": 3,
        "min_chunks": 3,
        "queries": {
            "UDH": "the Histopathology, Cytology, and Essential diagnostic criteria of Usual Ductal Hyperplasia (UDH)",
            "IC": "the Histopathology, Cytology, and Essential diagnostic criteria of Invasive breast carcinoma of no special type (IBC-NST)",
        },
    },
}


def _literature(diseases: dict[str, str] = DISEASES) -> dict:
    corpus_title = "Breast Tumours (5th ed.)"
    literature_list = [
        {
            "literature_id": "lit-nav",
            "source_idx": 0,
            "level": 1,
            "title_list": [corpus_title, "2. Epithelial tumours", None, None],
            "title": "2. Epithelial tumours",
            "href": None,
            "sections": [],
        }
    ]
    for source_idx, (code, name) in enumerate(diseases.items(), start=1):
        sections = [
            {
                "section_id": f"sec-{code}-{index}",
                "section_idx": index,
                "title": title,
                "text": f"{title} of {name}. Findings specific to {name} ({code}).",
            }
            for index, title in enumerate(SECTIONS)
        ]
        sections.append(
            {
                "section_id": f"sec-{code}-none",
                "section_idx": len(sections),
                "title": "ICD-O coding",
                "text": "None",
            }
        )
        literature_list.append(
            {
                "literature_id": f"lit-{code}",
                "source_idx": source_idx,
                "level": 3,
                "title_list": [corpus_title, "2. Epithelial tumours", "Overview", name],
                "title": name,
                "href": f"https://example.invalid/{code}",
                "sections": sections,
            }
        )
    return {
        "contract": "A.Literature",
        "schema_version": "2.0",
        "artifact_id": "A-test",
        "producer": "test",
        "payload": {
            "corpus": {
                "corpus_id": "test-corpus",
                "title": corpus_title,
                "source_file": "test.json",
                "source_path": "reference/person_b/checkpoint/test.json",
                "sha256": "a" * 64,
                "source_size_bytes": 1,
                "literature_count": len(literature_list),
            },
            "literature_list": literature_list,
        },
    }


def _d_artifact(cls: str) -> dict:
    def item(dx_id: str, cls_value: str) -> dict:
        return {"dx_pair_id": dx_id, "DxResultCls": cls_value, "DxResultTxt": cls_value}

    return {
        "contract": "D.DxPairs",
        "case_id": "case-x",
        "payload": {
            "case_list": [
                {
                    "case_id": "case-x",
                    "structured_report": {
                        "DxItems": {
                            "Histologic_Type": item("case-x-dx-001", cls),
                            "ER_status": item("case-x-dx-002", "Negative."),
                        }
                    },
                }
            ]
        },
    }


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.literature = _literature()
        self.candidates = _section_candidates(self.literature)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.kb = Path(self.tmp.name) / "kb"
        self.model_dir, self.model_logical, self.model_sha = model_identity(CONFIG["embedding"])
        self.embedder = dense.make_embedder(CONFIG["embedding"], self.model_dir)
        self._build(self.kb, self.literature, self.candidates)

    def _build(self, directory: Path, literature: dict, candidates: list) -> dict:
        return dense.build_knowledge_base(
            directory,
            literature,
            candidates,
            self.embedder,
            knowledge_base_id="kb-test",
            provider="hashing",
            model_logical_path=self.model_logical,
            model_sha256=self.model_sha,
            dtype=None,
            builder="test",
        )

    def _artifact(self, cls: str, config: dict | None = None, literature=None, kb=None):
        return build_dense_artifact(
            literature or self.literature,
            _d_artifact(cls),
            config or CONFIG,
            knowledge_base_dir=kb or self.kb,
            model_dir=None,
            model_sha256=self.model_sha,
            model_logical_path=self.model_logical,
        )


@unittest.skipUnless(HAS_NUMPY, "dense mode needs numpy")
class DenseRetrievalTests(_Base):
    def test_literal_none_sections_are_not_indexed(self) -> None:
        self.assertEqual(len(DISEASES) * len(SECTIONS), len(self.candidates))

    def test_f_is_valid_for_the_central_schema(self) -> None:
        artifact = self._artifact("IC")
        validate_artifact(artifact, "F.Chunks")
        kb = artifact["payload"]["knowledge_base"]
        self.assertEqual("dense", kb["retrieval_mode"])
        self.assertEqual({"dense": 1.0, "sparse": 0.0}, kb["hybrid_weights"])
        self.assertEqual(len(self.candidates), kb["document_count"])
        self.assertEqual("a" * 64, kb["corpus_sha256"])
        self.assertEqual(self.model_sha, kb["embedding_model_sha256"])

    def test_f_satisfies_what_person_a_requires(self) -> None:
        chunks = self._artifact("IC")["payload"]["chunks"]
        # Only Histologic_Type is retrieved, with the three chunks 甲's soft prompt needs.
        self.assertEqual(3, len(chunks))
        self.assertEqual({"case-x-dx-001"}, {c["dx_pair_id"] for c in chunks})
        self.assertEqual(3, len({c["section_id"] for c in chunks}))
        self.assertEqual([1, 2, 3], [c["retrieval_rank"] for c in chunks])
        self.assertEqual([1, 2, 3], [c["dense_rank"] for c in chunks])
        scores = [c["dense_score"] for c in chunks]
        self.assertEqual(sorted(scores, reverse=True), scores)
        self.assertTrue(all(c["sparse_score"] is None and c["sparse_rank"] is None for c in chunks))
        self.assertTrue(all(0 <= c["relevance_score"] <= 1 for c in chunks))
        self.assertTrue(all(c["indexed_token_count"] >= 1 for c in chunks))
        self.assertTrue(all(c["text"].strip().casefold() != "none" for c in chunks))

    def test_query_targets_the_mapped_disease(self) -> None:
        for cls in ("IC", "UDH"):
            chunks = self._artifact(cls)["payload"]["chunks"]
            self.assertEqual(DISEASES[cls], chunks[0]["literature_title"])

    def test_unmapped_class_yields_no_chunks(self) -> None:
        with redirect_stderr(io.StringIO()) as captured:
            artifact = self._artifact("AMBIGUOUS")
        self.assertEqual([], artifact["payload"]["chunks"])
        self.assertIn("no retrieval query", captured.getvalue())
        validate_artifact(artifact, "F.Chunks")

    def test_too_few_sections_is_an_error_not_padding(self) -> None:
        literature = _literature({"IC": DISEASES["IC"]})
        item = literature["payload"]["literature_list"][1]
        item["sections"] = item["sections"][:2]
        candidates = _section_candidates(literature)
        kb = Path(self.tmp.name) / "kb-small"
        self._build(kb, literature, candidates)
        with self.assertRaisesRegex(ValueError, "required"):
            self._artifact("IC", literature=literature, kb=kb)

    def test_top_k_below_min_chunks_is_rejected(self) -> None:
        config = copy.deepcopy(CONFIG)
        config["retrieval"].update(top_k=2, candidate_k=2)
        with self.assertRaises(ValueError):
            self._artifact("IC", config=config)

    def test_candidate_k_below_top_k_is_rejected(self) -> None:
        config = copy.deepcopy(CONFIG)
        config["retrieval"]["candidate_k"] = 2
        with self.assertRaises(ValueError):
            self._artifact("IC", config=config)

    def test_overlong_query_is_an_error_not_a_truncation(self) -> None:
        config = copy.deepcopy(CONFIG)
        config["embedding"]["query_max_tokens"] = 3
        with self.assertRaisesRegex(dense.KnowledgeBaseError, "query_max_tokens"):
            self._artifact("IC", config=config)


@unittest.skipUnless(HAS_NUMPY, "dense mode needs numpy")
class KnowledgeBaseTests(_Base):
    def _load(self, literature=None, **overrides):
        literature = literature or self.literature
        arguments = {
            "knowledge_base_id": "kb-test",
            "model_sha256": self.model_sha,
            "max_tokens": 512,
        }
        arguments.update(overrides)
        return dense.load_knowledge_base(
            self.kb, literature, _section_candidates(literature), **arguments
        )

    def test_manifest_records_what_is_needed_to_reproduce_the_index(self) -> None:
        _, sections, manifest = self._load()
        self.assertEqual("a" * 64, manifest["corpus"]["sha256"])
        self.assertEqual(self.model_sha, manifest["embedding"]["model_sha256"])
        self.assertEqual(len(self.candidates), manifest["chunking"]["document_count"])
        self.assertEqual(len(self.candidates), len(sections))
        self.assertEqual(manifest["archive_sha256"], dense.files_sha256(self.kb, list(dense.ARCHIVE_FILES)))

    def test_missing_index_is_a_clear_error_without_silent_rebuild(self) -> None:
        with self.assertRaisesRegex(dense.KnowledgeBaseError, "no silent rebuild"):
            dense.load_knowledge_base(
                Path(self.tmp.name) / "absent",
                self.literature,
                self.candidates,
                knowledge_base_id="kb-test",
                model_sha256=self.model_sha,
                max_tokens=512,
            )

    def test_index_from_a_different_corpus_is_refused(self) -> None:
        other = copy.deepcopy(self.literature)
        other["payload"]["corpus"]["sha256"] = "b" * 64
        with self.assertRaisesRegex(dense.KnowledgeBaseError, "different corpus"):
            self._load(literature=other)

    def test_index_with_changed_sections_is_refused(self) -> None:
        other = copy.deepcopy(self.literature)
        other["payload"]["literature_list"][1]["sections"][0]["section_id"] = "sec-changed"
        with self.assertRaisesRegex(dense.KnowledgeBaseError, "do not match"):
            self._load(literature=other)

    def test_index_built_with_another_model_is_refused(self) -> None:
        with self.assertRaisesRegex(dense.KnowledgeBaseError, "does not match the model"):
            self._load(model_sha256="c" * 64)

    def test_other_knowledge_base_id_is_refused(self) -> None:
        with self.assertRaisesRegex(dense.KnowledgeBaseError, "does not match config"):
            self._load(knowledge_base_id="kb-other")

    def test_other_max_tokens_is_refused(self) -> None:
        with self.assertRaisesRegex(dense.KnowledgeBaseError, "max_tokens"):
            self._load(max_tokens=256)

    def test_corrupted_embeddings_are_detected(self) -> None:
        with (self.kb / "embeddings.npy").open("ab") as stream:
            stream.write(b"x")
        with self.assertRaisesRegex(dense.KnowledgeBaseError, "archive_sha256"):
            self._load()

    def test_directory_digest_is_stable_and_detects_changes(self) -> None:
        model = Path(self.tmp.name) / "model"
        model.mkdir()
        (model / "a.bin").write_bytes(b"1")
        first = dense.directory_sha256(model)
        self.assertEqual(first, dense.directory_sha256(model))
        (model / "a.bin").write_bytes(b"2")
        self.assertNotEqual(first, dense.directory_sha256(model))


class RagDatabaseAdapterTests(unittest.TestCase):
    CONFIG = {
        "component_version": "test",
        "mode": "rag_database",
        "corpus_id": "rag-test",
        "corpus_title": "Breast Tumours (5th ed.)",
    }

    def _folder(self, root: Path) -> None:
        (root / "Usual_ductal_hyperplasia.json").write_text(
            json.dumps(
                {
                    "disease_name": "Usual ductal hyperplasia",
                    "sections": [
                        {"section_type": "Definition", "page_content": "A benign proliferation."},
                        {"section_type": "ICD-O coding", "page_content": "None"},
                    ],
                    "images": [{"local_path": "images\\a.png"}],
                }
            ),
            encoding="utf-8",
        )
        (root / "Adenomas").write_text("", encoding="utf-8")  # empty chapter placeholder

    def test_folder_becomes_a_valid_text_only_a(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._folder(Path(tmp))
            artifact = build_literature_artifact_from_rag_database(tmp, self.CONFIG)
            again = build_literature_artifact_from_rag_database(tmp, self.CONFIG)
        validate_artifact(artifact, "A.Literature")
        self.assertEqual(artifact, again)  # ids and digest are deterministic
        (item,) = artifact["payload"]["literature_list"]  # the extension-less file is skipped
        self.assertEqual("Usual ductal hyperplasia", item["title"])
        self.assertEqual(
            ["Breast Tumours (5th ed.)", None, None, "Usual ductal hyperplasia"],
            item["title_list"],
        )
        self.assertNotIn("images", item)
        self.assertEqual("None", item["sections"][1]["text"])  # kept in A, not retrieved
        self.assertEqual(1, len(_section_candidates(artifact)))
        self.assertNotIn(":\\", artifact["payload"]["corpus"]["source_path"])  # no host path

    def test_order_does_not_depend_on_the_platform_path_ordering(self) -> None:
        # "CDH1" sorts before "Carcinoma" by code point, after it when case is ignored (Windows).
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("Carcinoma_in_situ", "CDH1_cancer"):
                (Path(tmp) / f"{name}.json").write_text(
                    json.dumps(
                        {
                            "disease_name": name,
                            "sections": [{"section_type": "Definition", "page_content": "x"}],
                        }
                    ),
                    encoding="utf-8",
                )
            artifact = build_literature_artifact_from_rag_database(tmp, self.CONFIG)
        self.assertEqual(
            ["CDH1_cancer", "Carcinoma_in_situ"],
            [item["title"] for item in artifact["payload"]["literature_list"]],
        )


if __name__ == "__main__":
    unittest.main()
