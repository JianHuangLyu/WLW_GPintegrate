from __future__ import annotations

import json
import hashlib
from pathlib import Path
import tempfile
import unittest

from components.person_a.learnable_query_generator import (
    LearnableQueryGenerationError,
    load_attribute_reference,
    parse_strict_json_object,
    validate_generated_attributes,
)
from components.person_a.query_generation import generate_artifact
from contracts.metadata import dx_items
from contracts.paths import REFERENCE_ROOT
from contracts.runtime import validate_artifact


PERSON_A_REFERENCE = REFERENCE_ROOT / "person_a/template_ref"


class FakeLearnableGenerator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []
        self.provenance = {
            "backend": "learnable_soft_prompt",
            "model_name": "google/gemma-3-1b-it",
            "model_revision": None,
            "checkpoint_name": "soft_prompt_condition_best.pt",
            "checkpoint_sha256": "abc123",
            "attribute_reference": {
                "source_name": "chunks_with_attribute_condition.json",
                "sha256": "def456",
            },
            "required_chunk_count": 3,
        }

    def generate(self, dx_text: str, chunks: list[dict]) -> dict:
        self.calls.append((dx_text, [chunk["chunk_id"] for chunk in chunks]))
        return {
            "Cellular_and_Nuclear": {
                "Cell_Pleomorphism": {
                    "Monomorphic": "Must_True",
                    "Pleomorphic": "Not_Mentioned",
                },
                "Polarity": {
                    "Maintained": "High_Possibly_True",
                    "Lost": "Must_False",
                },
            }
        }


class ForbiddenGenerator:
    provenance = {"checkpoint_sha256": "must-not-be-used"}

    def generate(self, dx_text: str, chunks: list[dict]) -> dict:
        raise AssertionError("reference backend must not invoke the model")


def _d_artifact() -> dict:
    return {
        "contract": "D.DxPairs",
        "schema_version": "2.0",
        "artifact_id": "D-case-001",
        "case_id": "case-001",
        "producer": "test",
        "payload": {
            "data_mode": "inference",
            "DxItem_list": ["Histologic_Type"],
            "reference_versions": {},
            "case_list": [
                {
                    "sample_idx": 0,
                    "case_id": "case-001",
                    "hospital": "TEST",
                    "patient_info": {},
                    "date": "",
                    "source": {},
                    "organ": "Breast",
                    "report_raw_content": "Deidentified report",
                    "structured_report": {
                        "reportType": None,
                        "reportSubTypes": None,
                        "DxItems": {
                            "Histologic_Type": {
                                "dx_pair_id": "case-001-dx-001",
                                "source_report_id": "report-001",
                                "DxResultCls": "ADH",
                                "DxResultTxt": "Atypical ductal hyperplasia",
                                "DxResultRawTxt": "Focal atypical ductal hyperplasia",
                                "referenceBlock": None,
                                "referenceType": ["HE"],
                                "referenceWSI": ["case-001-he"],
                                "appear_reportTypes": ["Pathology"],
                                "optionTypes": "single_choice",
                                "has_numericalData": False,
                            }
                        },
                    },
                    "tissue_blocks": [
                        {
                            "block_id": "A",
                            "memo": "",
                            "stains": [
                                {
                                    "stain_id": "case-001-he",
                                    "stain_type": "HE",
                                    "filename": "case-001-he.svs",
                                    "filepath": "/data/case-001-he.svs",
                                    "memo": "",
                                    "roi_num": 0,
                                    "roi_list": [],
                                }
                            ],
                        }
                    ],
                    "memo": "",
                }
            ],
        },
    }


def _f_artifact(count: int = 3) -> dict:
    chunks = []
    for index in range(count):
        chunks.append(
            {
                "chunk_id": f"case-001-chunk-{index + 1:03d}",
                "dx_pair_id": "case-001-dx-001",
                "literature_id": "literature-001",
                "section_id": f"section-{index + 1:03d}",
                "source_idx": 0,
                "section_idx": index,
                "title_list": ["Breast", "ADH", None, None],
                "literature_title": "Deidentified reference",
                "section_title": "Histopathology",
                "source_href": None,
                "text": f"Reference evidence {index + 1}",
                "retrieval_rank": index + 1,
                "relevance_score": 1.0,
            }
        )
    return {
        "contract": "F.Chunks",
        "schema_version": "2.0",
        "artifact_id": "F-case-001",
        "case_id": "case-001",
        "producer": "test",
        "payload": {"corpus_id": "test-corpus", "chunks": chunks},
    }


def _write_references(root: Path) -> dict:
    candidate = {
        "visualAttrs": {
            "Cellular_and_Nuclear": {
                "Cell_Pleomorphism": {
                    "type": "nominal",
                    "options": ["Monomorphic", "Pleomorphic"],
                    "normal": ["Monomorphic"],
                },
                "Polarity": {
                    "type": "ordinal",
                    "options": ["Maintained", "Lost"],
                    "normal": ["Maintained"],
                },
            }
        }
    }
    criteria = [
        {
            "version": "1.0.0",
            "type": "diagnosticCriteria",
            "includeReferences": [],
            "typeLevel_idx": 0,
            "DxItem": "Histologic_Type",
            "DxResult": "Atypical ductal hyperplasia",
            "attrConditions": ["Must_True", "Not_Mentioned"],
            "optionTypes": ["nominal"],
            "visualAttrs": {
                "Cellular_and_Nuclear": {
                    "Cell_Pleomorphism": {
                        "type": "nominal",
                        "options": ["Monomorphic", "Pleomorphic"],
                        "conditions": {
                            "Monomorphic": "High_Possibly_True",
                            "Pleomorphic": "Must_False",
                        },
                    },
                    "Polarity": {
                        "type": "ordinal",
                        "options": ["Maintained", "Lost"],
                        "conditions": {
                            "Maintained": "High_Possibly_True",
                            "Lost": "Must_False",
                        },
                    },
                }
            },
        }
    ]
    mapping = {
        "Histologic_Type_mappingTable": {
            "ADH": "Atypical ductal hyperplasia"
        }
    }
    paths = {
        "candidate_reference_path": root / "candidateReference.json",
        "type_level_path": root / "typeLevel.json",
        "histologic_mapping_path": root / "mapping.json",
    }
    paths["candidate_reference_path"].write_text(
        json.dumps(candidate), encoding="utf-8"
    )
    paths["type_level_path"].write_text(
        json.dumps(criteria), encoding="utf-8"
    )
    paths["histologic_mapping_path"].write_text(
        json.dumps(mapping), encoding="utf-8"
    )
    return {key: str(value) for key, value in paths.items()}


class LearnableQueryGenerationTest(unittest.TestCase):
    def test_reference_backend_keeps_fixture_path_model_free(self) -> None:
        with tempfile.TemporaryDirectory(dir=PERSON_A_REFERENCE) as temp_dir:
            config = {
                "component_version": "person-a/query-generation:0.7.0",
                "asset_integrity": "record_only",
                **_write_references(Path(temp_dir)),
                "backend": {"mode": "reference"},
            }
            artifact = generate_artifact(
                _d_artifact(),
                _f_artifact(count=1),
                config,
                generator=ForbiddenGenerator(),
            )

        validate_artifact(artifact, "G.VisualAttributeQueries")
        query = dx_items(artifact["payload"])["Histologic_Type"][
            "visualAttrQueries"
        ][0]
        self.assertEqual("mapped", query["criteria_status"])
        self.assertEqual(["case-001-chunk-001"], query["chunk_ids"])
        self.assertNotIn(
            "learnable_query_generation", artifact["payload"]["reference_versions"]
        )

    def test_learnable_backend_produces_valid_g_and_uses_three_chunks(self) -> None:
        with tempfile.TemporaryDirectory(dir=PERSON_A_REFERENCE) as temp_dir:
            config = {
                "component_version": "person-a/query-generation:0.7.0",
                "asset_integrity": "record_only",
                **_write_references(Path(temp_dir)),
                "backend": {
                    "mode": "learnable_soft_prompt",
                    "required_chunk_count": 3,
                },
            }
            generator = FakeLearnableGenerator()
            chunks = _f_artifact(count=5)
            chunks["payload"]["chunks"].reverse()
            artifact = generate_artifact(
                _d_artifact(), chunks, config, generator=generator
            )

        validate_artifact(artifact, "G.VisualAttributeQueries")
        self.assertEqual(
            [
                (
                    "Focal atypical ductal hyperplasia",
                    [
                        "case-001-chunk-001",
                        "case-001-chunk-002",
                        "case-001-chunk-003",
                    ],
                )
            ],
            generator.calls,
        )
        query = dx_items(artifact["payload"])["Histologic_Type"][
            "visualAttrQueries"
        ][0]
        conditions = query["diagnosticCriteria"]["visualAttrs"][
            "Cellular_and_Nuclear"
        ]
        self.assertEqual(
            {"Monomorphic": "Must_True", "Pleomorphic": "Not_Mentioned"},
            conditions["Cell_Pleomorphism"]["conditions"],
        )
        self.assertEqual(
            {"Maintained": "High_Possibly_True", "Lost": "Must_False"},
            conditions["Polarity"]["conditions"],
        )
        self.assertEqual(
            "abc123",
            artifact["payload"]["reference_versions"]
            ["learnable_query_generation"]["checkpoint_sha256"],
        )
        selection = artifact["payload"]["reference_versions"][
            "learnable_query_generation"
        ]
        self.assertEqual(
            "ascending_retrieval_rank_top_n",
            selection["chunk_selection_rule"],
        )
        self.assertEqual(
            [
                {"chunk_id": "case-001-chunk-001", "retrieval_rank": 1},
                {"chunk_id": "case-001-chunk-002", "retrieval_rank": 2},
                {"chunk_id": "case-001-chunk-003", "retrieval_rank": 3},
            ],
            selection["selected_chunks_by_dx_pair"]["case-001-dx-001"],
        )

    def test_learnable_backend_fails_when_f_has_fewer_than_three_chunks(self) -> None:
        with tempfile.TemporaryDirectory(dir=PERSON_A_REFERENCE) as temp_dir:
            config = {
                "component_version": "person-a/query-generation:0.7.0",
                "asset_integrity": "record_only",
                **_write_references(Path(temp_dir)),
                "backend": {
                    "mode": "learnable_soft_prompt",
                    "required_chunk_count": 3,
                },
            }
            with self.assertRaisesRegex(ValueError, "requires 3"):
                generate_artifact(
                    _d_artifact(),
                    _f_artifact(count=1),
                    config,
                    generator=FakeLearnableGenerator(),
                )

    def test_f_rejects_duplicate_rank_chunk_id_and_foreign_dx_pair(self) -> None:
        with tempfile.TemporaryDirectory(dir=PERSON_A_REFERENCE) as temp_dir:
            config = {
                "component_version": "person-a/query-generation:0.7.0",
                "asset_integrity": "record_only",
                **_write_references(Path(temp_dir)),
                "backend": {"mode": "reference"},
            }

            duplicate_rank = _f_artifact()
            duplicate_rank["payload"]["chunks"][1]["retrieval_rank"] = 1
            with self.assertRaisesRegex(ValueError, "duplicate retrieval_rank"):
                generate_artifact(_d_artifact(), duplicate_rank, config)

            duplicate_id = _f_artifact()
            duplicate_id["payload"]["chunks"][1]["chunk_id"] = (
                duplicate_id["payload"]["chunks"][0]["chunk_id"]
            )
            with self.assertRaisesRegex(ValueError, "duplicate chunk_id"):
                generate_artifact(_d_artifact(), duplicate_id, config)

            foreign = _f_artifact()
            foreign["payload"]["chunks"][0]["dx_pair_id"] = "foreign-dx"
            with self.assertRaisesRegex(ValueError, "absent from D"):
                generate_artifact(_d_artifact(), foreign, config)

    def test_attribute_reference_and_strict_json_validation(self) -> None:
        attributes = {
            "Category": {
                "Feature": {
                    "Present": "Must_True",
                    "Absent": "Not_Mentioned",
                },
                "Other": {"Seen": "Low_Possibly_True"},
            }
        }
        other_attributes = {
            "Category": {
                "Feature": {
                    "Present": "Not_Mentioned",
                    "Absent": "Must_True",
                },
                "Other": {"Seen": "Negligible"},
            }
        }

        def reference_entry(text: str, attribute: dict) -> dict:
            return {
                "text": text,
                "attribute": attribute,
                "attribute_condition_metadata": {
                    "target_format": "chunk_visual_attribute_option_conditions_v2",
                    "typelevel_sha256": "a" * 64,
                    "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                },
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "chunks.json"
            path.write_text(
                json.dumps(
                    [
                        reference_entry("first", attributes),
                        reference_entry("second", other_attributes),
                    ]
                ),
                encoding="utf-8",
            )
            template, allowed, provenance = load_attribute_reference(path)

        generated = parse_strict_json_object(json.dumps(attributes))
        validate_generated_attributes(generated, template, allowed)
        self.assertEqual(
            {
                "Must_True",
                "Must_False",
                "High_Possibly_True",
                "Low_Possibly_True",
                "Negligible",
                "Not_Mentioned",
            },
            allowed["Category.Feature.Present"],
        )
        self.assertEqual("chunks.json", provenance["source_name"])
        self.assertEqual(
            "chunk_visual_attribute_option_conditions_v2",
            provenance["target_format"],
        )
        with self.assertRaises(LearnableQueryGenerationError):
            parse_strict_json_object("```json\n{}\n```")

        invalid = json.loads(json.dumps(attributes))
        invalid["Category"]["Feature"]["Present"] = "Sometimes"
        with self.assertRaises(LearnableQueryGenerationError):
            validate_generated_attributes(invalid, template, allowed)


if __name__ == "__main__":
    unittest.main()
