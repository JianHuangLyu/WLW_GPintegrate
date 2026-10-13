from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from components.person_d import matching_filter
from components.person_d.matching_filter import LabelMap, MatchingSettings, evaluate_attribute


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
LABEL_MAP = {
    "criteria_version": "1.2.1",
    "global_aliases": {"N/A": ["Unable to confirm"]},
    "attribute_aliases": {
        "Architecture.Pattern": {"Single file": ["Single-file/Linear cords"]},
        "Cellular_and_Nuclear.Epithelial_Cell_Shape": {
            "Cuboidal/Columnar": ["Cuboidal", "Columnar"]
        },
    },
}
SETTINGS = {
    "condition_weights": {
        "Must_True": 1.0,
        "High_Possibly_True": 1.0,
        "Low_Possibly_True": -1.0,
        "Must_False": -1.0,
    },
    "score_threshold": 0.0,
    "min_evaluated_attributes": 1,
    "unverified_must_true": "skip",
}
SUPPORTING = {
    "Cellular_and_Nuclear": {
        "Cytological_Atypia": ["High-grade/Severe"],
        "Chromatin": ["Hyperchromatic"],
        "Cell_Pleomorphism": ["Moderate"],
    }
}


def histologic_criteria() -> dict:
    g = json.loads((EXAMPLES / "G_queries.valid.json").read_text(encoding="utf-8"))
    record = g["payload"]["case_list"][0]["structured_report"]["DxItems"]["Histologic_Type"]
    return record["visualAttrQueries"][0]["diagnosticCriteria"]


def full_vocabulary(criteria: dict) -> dict:
    """A vocabulary that has one label for every criteria option, so every option is reachable."""

    return {
        category: {attribute: list(spec["options"]) for attribute, spec in attributes.items()}
        for category, attributes in criteria["visualAttrs"].items()
    }


def match_query(extracted, criteria, label_map, settings, vocabulary=None):
    if vocabulary is None:
        vocabulary = full_vocabulary(criteria)
    return matching_filter.match_query(extracted, criteria, label_map, settings, vocabulary)


def without_must_true(criteria: dict) -> dict:
    """The same criteria with every Must_True option relaxed to High_Possibly_True."""

    relaxed = copy.deepcopy(criteria)
    for category in relaxed["visualAttrs"].values():
        for spec in category.values():
            spec["conditions"] = {
                option: "High_Possibly_True" if condition == "Must_True" else condition
                for option, condition in spec["conditions"].items()
            }
    return relaxed


class MatchingFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.criteria = histologic_criteria()
        self.label_map = LabelMap.from_document(LABEL_MAP)
        self.settings = MatchingSettings.from_config(SETTINGS)

    def test_label_resolution_uses_alias_then_exact_then_case_insensitive(self) -> None:
        pattern = self.criteria["visualAttrs"]["Architecture"]["Pattern"]["options"]
        resolve = self.label_map.resolve
        self.assertEqual(["Unable to confirm"], resolve("Architecture.Pattern", "N/A", pattern))
        self.assertEqual(
            ["Single-file/Linear cords"], resolve("Architecture.Pattern", "Single file", pattern)
        )
        self.assertEqual(["Solid"], resolve("Architecture.Pattern", "Solid", pattern))
        self.assertEqual(
            ["Micropapillary"], resolve("Architecture.Pattern", "micropapillary", pattern)
        )
        self.assertEqual([], resolve("Architecture.Pattern", "one to several layers", pattern))

    def test_alias_to_options_with_different_conditions_is_ambiguous(self) -> None:
        spec = self.criteria["visualAttrs"]["Cellular_and_Nuclear"]["Epithelial_Cell_Shape"]
        result = evaluate_attribute(
            ["Cuboidal/Columnar"],
            spec,
            "Cellular_and_Nuclear.Epithelial_Cell_Shape",
            self.label_map,
        )
        self.assertEqual("ambiguous_label", result["status"])

    def test_supporting_labels_are_selected(self) -> None:
        result = match_query(
            SUPPORTING, without_must_true(self.criteria), self.label_map, self.settings
        )
        self.assertEqual(("selected", "visual_attributes_match"), (result["status"], result["reason"]))
        self.assertEqual(1.0, result["score"])
        self.assertEqual(3, result["evaluated_count"])
        self.assertIn("Cellular_and_Nuclear.Chromatin", result["matched_attributes"])
        self.assertEqual([], result["must_true_unverified"])
        self.assertTrue(result["must_true_passed"])

    def test_unverified_must_true_is_never_selected(self) -> None:
        result = match_query(SUPPORTING, self.criteria, self.label_map, self.settings)
        self.assertEqual(("skipped", "insufficient_visual_evidence"), (result["status"], result["reason"]))
        self.assertEqual(3, result["evaluated_count"])
        self.assertFalse(result["must_true_passed"])
        self.assertEqual(
            [
                "Architecture.Myoepithelial_Cell_Layer",
                "Architecture.Tumour_Border",
                "Special_Features.Stromal_Characteristics",
            ],
            result["must_true_unverified"],
        )

    def test_unverified_must_true_is_checked_before_the_score(self) -> None:
        result = match_query(
            {"Cellular_and_Nuclear": {"Chromatin": ["Hyperchromatic"], "Cell_Pleomorphism": ["Monomorphic"]}},
            self.criteria,
            self.label_map,
            MatchingSettings.from_config({**SETTINGS, "score_threshold": 0.5}),
        )
        self.assertEqual(("skipped", "insufficient_visual_evidence"), (result["status"], result["reason"]))
        self.assertTrue(result["must_true_unverified"])

    def test_must_false_option_rejects(self) -> None:
        result = match_query(
            {
                "Cellular_and_Nuclear": {
                    "Chromatin": ["Regular"],
                    "Cell_Pleomorphism": ["Moderate"],
                }
            },
            self.criteria,
            self.label_map,
            self.settings,
        )
        self.assertEqual(("rejected", "must_condition_failed"), (result["status"], result["reason"]))
        self.assertFalse(result["must_false_passed"])
        self.assertEqual(["Cellular_and_Nuclear.Chromatin"], result["failed_attributes"])

    def test_evaluated_must_true_attribute_must_hit_a_must_true_option(self) -> None:
        criteria = copy.deepcopy(self.criteria)
        border = criteria["visualAttrs"]["Architecture"]["Tumour_Border"]
        other = next(
            option for option, condition in border["conditions"].items()
            if condition not in {"Must_True", "Must_False", "Negligible", "Not_Mentioned"}
        )
        result = match_query(
            {"Architecture": {"Tumour_Border": [other]}},
            criteria,
            self.label_map,
            self.settings,
        )
        self.assertEqual("rejected", result["status"])
        self.assertFalse(result["must_true_passed"])

    def test_unverified_must_true_policy(self) -> None:
        extracted = {"Cellular_and_Nuclear": {"Chromatin": ["Hyperchromatic"]}}
        strict = MatchingSettings.from_config({**SETTINGS, "unverified_must_true": "reject"})
        result = match_query(extracted, self.criteria, self.label_map, strict)
        self.assertEqual(("rejected", "must_condition_failed"), (result["status"], result["reason"]))
        self.assertIn("Architecture.Tumour_Border", result["failed_attributes"])

    def test_unreachable_must_false_option_is_never_selected(self) -> None:
        criteria = without_must_true(self.criteria)
        vocabulary = full_vocabulary(criteria)
        chromatin = criteria["visualAttrs"]["Cellular_and_Nuclear"]["Chromatin"]
        forbidden = next(o for o, c in chromatin["conditions"].items() if c == "Must_False")
        vocabulary["Cellular_and_Nuclear"]["Chromatin"].remove(forbidden)

        result = match_query(SUPPORTING, criteria, self.label_map, self.settings, vocabulary)
        self.assertEqual(("skipped", "insufficient_visual_evidence"), (result["status"], result["reason"]))
        self.assertFalse(result["must_false_passed"])
        self.assertEqual(["Cellular_and_Nuclear.Chromatin"], result["must_unverifiable"])
        self.assertEqual(
            {"Must_False": [forbidden]},
            result["attributes"]["Cellular_and_Nuclear.Chromatin"]["unreachable_must"],
        )

        strict = MatchingSettings.from_config({**SETTINGS, "unverified_must_true": "reject"})
        result = match_query(SUPPORTING, criteria, self.label_map, strict, vocabulary)
        self.assertEqual(("rejected", "must_condition_failed"), (result["status"], result["reason"]))

    def test_unreachable_must_true_option_makes_a_miss_unverified_not_failed(self) -> None:
        border = self.criteria["visualAttrs"]["Architecture"]["Tumour_Border"]
        required = next(o for o, c in border["conditions"].items() if c == "Must_True")
        other = next(
            o for o, c in border["conditions"].items()
            if c not in {"Must_True", "Must_False", "Negligible", "Not_Mentioned"}
        )
        extracted = {"Architecture": {"Tumour_Border": [other]}}
        result = match_query(extracted, self.criteria, self.label_map, self.settings)
        self.assertEqual(("rejected", "must_condition_failed"), (result["status"], result["reason"]))

        vocabulary = full_vocabulary(self.criteria)
        vocabulary["Architecture"]["Tumour_Border"].remove(required)
        result = match_query(extracted, self.criteria, self.label_map, self.settings, vocabulary)
        self.assertEqual(("skipped", "insufficient_visual_evidence"), (result["status"], result["reason"]))
        self.assertFalse(result["must_true_passed"])
        self.assertIn("Architecture.Tumour_Border", result["must_unverifiable"])

    def test_score_below_threshold_rejects(self) -> None:
        settings = MatchingSettings.from_config({**SETTINGS, "score_threshold": 0.5})
        result = match_query(
            {
                "Cellular_and_Nuclear": {
                    "Chromatin": ["Hyperchromatic"],
                    "Cell_Pleomorphism": ["Monomorphic"],
                }
            },
            without_must_true(self.criteria),
            self.label_map,
            settings,
        )
        self.assertEqual(0.0, result["score"])
        self.assertEqual(("rejected", "score_below_threshold"), (result["status"], result["reason"]))

    def test_model_disagreement_is_insufficient_evidence(self) -> None:
        result = match_query(
            {"Cellular_and_Nuclear": {"Chromatin": [], "Cell_Pleomorphism": []}},
            self.criteria,
            self.label_map,
            self.settings,
        )
        self.assertEqual(("skipped", "insufficient_visual_evidence"), (result["status"], result["reason"]))
        self.assertEqual(
            "models_disagree",
            result["attributes"]["Cellular_and_Nuclear.Chromatin"]["status"],
        )

    def test_criteria_version_must_match_label_map(self) -> None:
        criteria = {**self.criteria, "version": "9.9.9"}
        with self.assertRaisesRegex(ValueError, "criteria_version"):
            match_query({}, criteria, self.label_map, self.settings)

    def test_invalid_settings_fail(self) -> None:
        for broken in (
            {**SETTINGS, "score_threshold": 1.5},
            {**SETTINGS, "unverified_must_true": "maybe"},
            {**SETTINGS, "unverified_must_true": "ignore"},
            {**SETTINGS, "min_evaluated_attributes": 0},
            {**SETTINGS, "condition_weights": {"Must_True": 2.0}},
        ):
            with self.assertRaises(ValueError):
                MatchingSettings.from_config(broken)


if __name__ == "__main__":
    unittest.main()
