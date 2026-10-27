from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from components.person_a.histologic_type_classifier import (
    HISTOLOGIC_TYPE_CLASSES,
    classify_histologic_type,
)
from components.person_a.medgemma_extractor import _chunks, _json_object
from components.person_a.medgemma_extractor import _canonical_key
from components.person_a.prepare_case_list import build_case_list
from components.person_a.reference_data import load_dx_candidates
from components.person_a.report_decompose import build_artifact
from components.person_a.report_extraction import (
    ReportExtractionEngine,
    extract_cgmh_items,
    extract_labeled_items,
    extract_vghtc_items,
)
from contracts.paths import REFERENCE_ROOT
from contracts.runtime import validate_artifact, validate_case_list_input


def _definition(result: str, reference_type: list[str]) -> dict[str, object]:
    return {
        "DxResultCls": [result],
        "referenceType": reference_type,
        "appear_reportTypes": [],
        "optionTypes": "categorical",
        "has_numericalData": False,
    }


class ReportExtractionTests(unittest.TestCase):
    def test_histologic_type_uses_the_agreed_seven_classes(self) -> None:
        examples = {
            "usual ductal hyperplasia": "UDH",
            "flat epithelial atypia": "FEA",
            "atypical ductal hyperplasia": "ADH",
            "ductal carcinoma in situ": "DCIS",
            "invasive ductal carcinoma": "IC",
            "fibroadenoma": "OTHER",
            "carcinoma": "AMBIGUOUS",
        }
        self.assertEqual(
            ("UDH", "FEA", "ADH", "DCIS", "IC", "OTHER", "AMBIGUOUS"),
            HISTOLOGIC_TYPE_CLASSES,
        )
        for raw_text, expected in examples.items():
            with self.subTest(raw_text=raw_text):
                self.assertEqual(expected, classify_histologic_type(raw_text))

    def test_packaged_candidates_restrict_only_histologic_type(self) -> None:
        candidate_path = (
            REFERENCE_ROOT
            / "person_a/template_ref/DxStructuredCandidates_integrated.json"
        )
        structured_report, _ = load_dx_candidates(candidate_path)
        catalog = structured_report["DxItems"]
        self.assertEqual(
            list(HISTOLOGIC_TYPE_CLASSES),
            catalog["Histologic_Type"]["DxResultCls"],
        )
        self.assertEqual(25, len(catalog))
        for name, definition in catalog.items():
            if name == "Histologic_Type":
                self.assertEqual("categorical", definition["optionTypes"])
            else:
                self.assertEqual([], definition["DxResultCls"])
                self.assertEqual("free_text", definition["optionTypes"])

    def test_histologic_type_is_classified_and_other_items_remain_free_text(self) -> None:
        catalog = {
            "Histologic_Type": {
                **_definition("UDH", ["HE"]),
                "DxResultCls": list(HISTOLOGIC_TYPE_CLASSES),
            },
            "ER_status": {
                **_definition("unused", ["ER"]),
                "DxResultCls": [],
                "optionTypes": "free_text",
            },
        }
        case = {
            "case_id": "case-seven-class",
            "hospital": "VGHTC",
            "reports": [
                {
                    "report_id": "report-001",
                    "raw_text": (
                        "1. Histologic Type: Invasive ductal carcinoma.\n"
                        "15. ER status: 95%."
                    ),
                }
            ],
            "dx_pairs": [],
        }
        ReportExtractionEngine(catalog, {"backend": "hospital_routed"}).fill_case(
            case
        )
        results = {pair["dx_item"]: pair for pair in case["dx_pairs"]}
        self.assertEqual("IC", results["Histologic_Type"]["dx_result"])
        self.assertEqual(
            "Invasive ductal carcinoma.",
            results["Histologic_Type"]["dx_result_text"],
        )
        self.assertEqual("95%.", results["ER_status"]["dx_result"])

    def test_regex_extracts_items_and_stops_before_gross_description(self) -> None:
        report = """Prognostic and predictive factor:
1. Histologic Type: Invasive carcinoma of no special type (ductal).
2. Histologic Grade: Nottingham grade 2.
15. ER status: 95%.

Gross description: Histologic Type: this must not replace the diagnosis.
"""
        extracted = extract_labeled_items(report)
        self.assertEqual(
            "Invasive carcinoma of no special type (ductal).",
            extracted["Histologic Type"],
        )
        self.assertEqual("Nottingham grade 2.", extracted["Histologic Grade"])
        self.assertEqual("95%.", extracted["ER status"])
        self.assertNotIn("Gross description", " ".join(extracted.values()))

    def test_vghtc_extractor_preserves_original_vghtc_label_set(self) -> None:
        report = "Tumor Size: 2 cm\nHistologic Type: Invasive carcinoma"
        extracted = extract_vghtc_items(report)
        self.assertNotIn("Tumor Size", extracted)
        self.assertEqual("Invasive carcinoma", extracted["Histologic Type"])

    def test_cgmh_extractor_preserves_aliases_and_grade_subitems(self) -> None:
        report = (
            "ER(6F11/Novacastra): Positive\n"
            "PR(1A6/Novacastra): Negative\n"
            "HER-2-neu(polyclone/DAKO): 2+\n"
            "Tubular Differentiation: 2 Nuclear Pleomorphism: 3 "
            "Mitotic Rate: 1 ER status: Positive"
        )
        extracted = extract_cgmh_items(report)
        self.assertEqual("Positive", extracted["ER status"])
        self.assertEqual("Negative", extracted["PR status"])
        self.assertEqual("2+", extracted["Her-2/neu status"])
        self.assertEqual(
            "Tubular Differentiation: 2. Nuclear Pleomorphism: 3. "
            "Mitotic Rate: 1.",
            extracted["Histologic Grade"],
        )

    def test_engine_resolves_query_design_names_to_catalog_names(self) -> None:
        histologic = "Invasive carcinoma of no special type (ductal)."
        catalog = {
            "Histologic_Type": _definition(histologic, ["HE"]),
            "ER_status": _definition("95%.", ["ER"]),
        }
        case = {
            "case_id": "case-regex",
            "reports": [
                {
                    "report_id": "report-001",
                    "raw_text": (
                        "1. Histologic Type: Invasive carcinoma of no special "
                        "type (ductal).\n15. ER status: 95%."
                    ),
                }
            ],
            "dx_pairs": [],
        }
        engine = ReportExtractionEngine(catalog, {"backend": "regex"})
        engine.fill_case(case)
        self.assertEqual(
            ["Histologic_Type", "ER_status"],
            [pair["dx_item"] for pair in case["dx_pairs"]],
        )
        self.assertEqual(histologic, case["dx_pairs"][0]["dx_result_text"])

    def test_existing_table_results_are_not_replaced(self) -> None:
        catalog = {"Histologic_Type": _definition("Existing", ["HE"])}
        pair = {
            "dx_pair_id": "case-001-dx-001",
            "case_id": "case-001",
            "source_report_id": "report-001",
            "dx_item": "Histologic_Type",
            "dx_result": "Existing",
            "reference_wsi_ids": [],
        }
        case = {"case_id": "case-001", "reports": [], "dx_pairs": [pair]}
        ReportExtractionEngine(catalog).fill_case(case)
        self.assertEqual([pair], case["dx_pairs"])

    def test_existing_histologic_text_is_normalized_to_seven_class(self) -> None:
        catalog = {
            "Histologic_Type": {
                **_definition("UDH", ["HE"]),
                "DxResultCls": list(HISTOLOGIC_TYPE_CLASSES),
            }
        }
        pair = {
            "dx_pair_id": "case-001-dx-001",
            "case_id": "case-001",
            "source_report_id": "report-001",
            "dx_item": "Histologic_Type",
            "dx_result": "Invasive carcinoma of no special type",
            "reference_wsi_ids": [],
        }
        case = {"case_id": "case-001", "reports": [], "dx_pairs": [pair]}
        ReportExtractionEngine(catalog).fill_case(case)
        self.assertEqual("IC", pair["dx_result"])
        self.assertEqual(
            "Invasive carcinoma of no special type", pair["dx_result_text"]
        )

    def test_optional_medgemma_helpers_do_not_require_model_dependencies(self) -> None:
        self.assertEqual(["abcd", "cdef", "ef"], _chunks("abcdef", 4, 2))
        self.assertEqual(
            {"Histologic_Type": "IC"},
            _json_object('```json\n{"Histologic_Type": "IC"}\n```'),
        )
        self.assertEqual(
            _canonical_key("Histologic_Type"), _canonical_key("Histologic Type")
        )
        self.assertEqual(
            {"Histologic_Type": "IC"},
            _json_object(
                'Example: {"ignored": true}\nAnswer: '
                '{"Histologic_Type": "IC"}\nDone.'
            ),
        )

    def test_hybrid_backend_asks_model_only_for_regex_misses(self) -> None:
        histologic = "Invasive carcinoma of no special type (ductal)."
        catalog = {
            "Histologic_Type": _definition(histologic, ["HE"]),
            "ER_status": _definition("Positive", ["ER"]),
        }
        requested: list[str] = []

        class FakeMedGemma:
            def extract(self, report_text: str, items: list[str]) -> dict[str, str]:
                requested.extend(items)
                return {"ER_status": "Positive"}

        engine = ReportExtractionEngine(
            catalog, {"backend": "regex_then_medgemma"}
        )
        engine._medgemma = FakeMedGemma()
        case = {
            "case_id": "case-hybrid",
            "reports": [
                {
                    "report_id": "report-001",
                    "raw_text": f"1. Histologic Type: {histologic}",
                }
            ],
            "dx_pairs": [],
        }
        engine.fill_case(case)
        self.assertEqual(["ER_status"], requested)
        self.assertEqual(
            ["Histologic_Type", "ER_status"],
            [pair["dx_item"] for pair in case["dx_pairs"]],
        )

    def test_hospital_route_vghtc_is_always_regex_only(self) -> None:
        histologic = "Invasive carcinoma of no special type (ductal)."
        catalog = {"Histologic_Type": _definition(histologic, ["HE"])}

        class ForbiddenMedGemma:
            def extract(self, report_text: str, items: list[str]) -> dict[str, str]:
                raise AssertionError("VGHTC must never call MedGemma")

        engine = ReportExtractionEngine(catalog, {"backend": "hospital_routed"})
        engine._medgemma = ForbiddenMedGemma()
        case = {
            "case_id": "case-vghtc",
            "hospital": "VGHTC",
            "reports": [
                {
                    "report_id": "report-001",
                    "raw_text": f"1. Histologic Type: {histologic}",
                }
            ],
            "dx_pairs": [],
        }
        engine.fill_case(case)
        self.assertEqual(histologic, case["dx_pairs"][0]["dx_result"])

    def test_cgmh_regex_miss_uses_medgemma_for_all_items(self) -> None:
        catalog = {
            "Histologic_Type": _definition("Model histologic type", ["HE"]),
            "ER_status": _definition("Positive", ["ER"]),
        }
        requested: list[str] = []

        class FakeMedGemma:
            def extract(self, report_text: str, items: list[str]) -> dict[str, str]:
                requested.extend(items)
                return {
                    "Histologic_Type": "Model histologic type",
                    "ER_status": "Positive",
                }

        engine = ReportExtractionEngine(catalog, {"backend": "hospital_routed"})
        engine._medgemma = FakeMedGemma()
        case = {
            "case_id": "case-cgmh-empty-regex",
            "hospital": "CGMH",
            "reports": [
                {
                    "report_id": "report-001",
                    "raw_text": "Free-form diagnosis without any configured label.",
                }
            ],
            "dx_pairs": [],
        }
        engine.fill_case(case)
        self.assertEqual(list(catalog), requested)
        self.assertEqual(set(catalog), {pair["dx_item"] for pair in case["dx_pairs"]})

    def test_cgmh_regex_hit_keeps_regex_and_model_histologic_type(self) -> None:
        catalog = {
            "Histologic_Type": _definition("Model histologic type", ["HE"]),
            "ER_status": _definition("Positive", ["ER"]),
        }
        requested: list[str] = []

        class FakeMedGemma:
            def extract(self, report_text: str, items: list[str]) -> dict[str, str]:
                requested.extend(items)
                return {"Histologic_Type": "Model histologic type"}

        engine = ReportExtractionEngine(catalog, {"backend": "hospital_routed"})
        engine._medgemma = FakeMedGemma()
        case = {
            "case_id": "case-cgmh-regex-hit",
            "hospital": "CGMH",
            "reports": [
                {
                    "report_id": "report-001",
                    "raw_text": (
                        "Histologic Type: Regex histologic type.\n"
                        "ER status: Positive"
                    ),
                }
            ],
            "dx_pairs": [],
        }
        engine.fill_case(case)
        results = {pair["dx_item"]: pair["dx_result"] for pair in case["dx_pairs"]}
        self.assertEqual(["Histologic_Type"], requested)
        self.assertEqual("Model histologic type", results["Histologic_Type"])
        self.assertEqual("Positive", results["ER_status"])

    def test_b_is_normalized_to_case_list_before_single_case_d(self) -> None:
        histologic = "Invasive carcinoma of no special type (ductal)."
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            table_path = directory / "reports.csv"
            with table_path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(
                    stream,
                    fieldnames=[
                        "case_id",
                        "report_id",
                        "report_text",
                        "wsi_id",
                        "stain_type",
                        "wsi_path",
                        "block_id",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "case_id": "case-raw-001",
                        "report_id": "report-raw-001",
                        "report_text": f"1. Histologic Type: {histologic}",
                        "wsi_id": "case-raw-001-he",
                        "stain_type": "HE",
                        "wsi_path": "/data/case-raw-001-he.svs",
                        "block_id": "A",
                    }
                )

            manifest = {
                "contract": "B.ReportTables",
                "schema_version": "1.0",
                "artifact_id": "raw-table-test",
                "payload": {
                    "tables": [
                        {
                            "table_idx": 0,
                            "table_type": "VGHTC2024",
                            "table_path": table_path.name,
                        }
                    ]
                },
            }
            case_list, skipped = build_case_list(
                manifest,
                directory,
                {"dx_item_list": ["Histologic_Type"]},
            )
            validate_case_list_input(case_list, single_case=True)
            self.assertEqual([], skipped)

            config = {
                "component_version": "person-a/report-decompose:0.8.0-test",
                "dx_candidates_path": str(
                    REFERENCE_ROOT
                    / "person_a/template_ref/DxStructuredCandidates_integrated.json"
                ),
                "report_extraction": {
                    "enabled": True,
                    "backend": "regex",
                    "only_when_missing": True,
                    "strict_result_classes": True,
                },
            }
            artifact = build_artifact(case_list, config)
            validate_artifact(artifact, "D.DxPairs")
            case_payload = artifact["payload"]["case_list"][0]
            item = case_payload["structured_report"]["DxItems"]["Histologic_Type"]
            self.assertEqual("IC", item["DxResultCls"])
            self.assertEqual(histologic, item["DxResultTxt"])
            self.assertEqual(["A"], item["referenceBlock"])
            self.assertEqual(["case-raw-001-he"], item["referenceWSI"])


if __name__ == "__main__":
    unittest.main()
