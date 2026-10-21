from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from components.person_d.mapping import (
    MARKDOWN_PATH,
    RULES,
    audit,
    check_acceptance,
    criteria_option_lists,
    load_acceptance,
    render_markdown,
    summarize,
)
from components.person_d.matching_filter import LabelMap
from contracts.paths import PROJECT_ROOT, REFERENCE_ROOT


COMPONENT = Path(__file__).resolve().parents[1]
TEMPLATE_REF = REFERENCE_ROOT / "person_d" / "template_ref"
PROMPTS = TEMPLATE_REF / "visual_attribute_prompts.json"
LABEL_MAP = TEMPLATE_REF / "criteria_label_map.json"


def _example_criteria() -> dict:
    g = json.loads((COMPONENT / "examples/G_queries.valid.json").read_text(encoding="utf-8"))
    record = g["payload"]["case_list"][0]["structured_report"]["DxItems"]["Histologic_Type"]
    return record["visualAttrQueries"][0]["diagnosticCriteria"]


def _vocabulary(acceptance: dict) -> dict:
    vocabulary: dict = {}
    for key, entry in acceptance["attributes"].items():
        category, attribute = key.split(".", 1)
        vocabulary.setdefault(category, {})[attribute] = list(entry["prompt_options"])
    return vocabulary


def _label_map_document(acceptance: dict) -> dict:
    return {"criteria_version": acceptance["criteria_version"], **acceptance["label_map"]}


class MappingAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.acceptance = load_acceptance()
        self.criteria = _example_criteria()

    def test_accepted_criteria_version_is_the_contract_version(self) -> None:
        # visual_filter accepts only this version in both modes; it must be the version the
        # metadata contract defines for diagnosticCriteria.
        schema = json.loads(
            (PROJECT_ROOT / "contracts/schemas/metadata_case_payload.schema.json").read_text(encoding="utf-8")
        )
        contract = schema["$defs"]["diagnosticCriteria"]["properties"]["version"]["const"]
        self.assertEqual(contract, self.acceptance["criteria_version"])

    def test_acceptance_covers_every_option_of_the_criteria_version(self) -> None:
        self.assertEqual(self.acceptance["criteria_version"], self.criteria["version"])
        self.assertEqual(
            criteria_option_lists(self.criteria),
            {key: entry["criteria_options"] for key, entry in self.acceptance["attributes"].items()},
        )

    def test_recorded_mapping_follows_the_mapping_rule(self) -> None:
        self.assertEqual(
            [],
            check_acceptance(self.acceptance, _vocabulary(self.acceptance), _label_map_document(self.acceptance)),
        )
        for entry in self.acceptance["attributes"].values():
            for mapped in entry["mapping"].values():
                self.assertIn(mapped["rule"], RULES)
                self.assertEqual(mapped["rule"] == "unmapped", not mapped["options"])

    def test_every_unreachable_option_is_classified(self) -> None:
        categories = self.acceptance["unreachable_categories"]
        counts: dict = {}
        for entry in self.acceptance["attributes"].values():
            reached = {option for mapped in entry["mapping"].values() for option in mapped["options"]}
            self.assertEqual(
                [option for option in entry["criteria_options"] if option not in reached],
                list(entry["unreachable"]),
            )
            for info in entry["unreachable"].values():
                self.assertIn(info["category"], categories)
                counts[info["category"]] = counts.get(info["category"], 0) + 1

        actual = audit(
            _vocabulary(self.acceptance),
            LabelMap.from_document(_label_map_document(self.acceptance)),
            {key: entry["criteria_options"] for key, entry in self.acceptance["attributes"].items()},
        )
        summary = dict(self.acceptance["summary"])
        self.assertEqual(dict(sorted(counts.items())), summary.pop("unreachable_by_category"))
        self.assertEqual(summarize(actual), summary)
        self.assertEqual(
            {
                "attributes": 24,
                "prompt_options": 105,
                "criteria_options": 138,
                "unmapped_prompt_options": 1,
                "multi_mapped_prompt_options": 1,
                "unreachable_criteria_options": 33,
            },
            summary,
        )

    def test_mapping_document_is_generated_from_the_acceptance(self) -> None:
        self.assertEqual(render_markdown(self.acceptance), MARKDOWN_PATH.read_text(encoding="utf-8"))

    def test_vocabulary_or_alias_drift_is_reported(self) -> None:
        vocabulary = _vocabulary(self.acceptance)
        vocabulary["Cellular_and_Nuclear"]["Chromatin"].remove("Regular")
        errors = check_acceptance(self.acceptance, vocabulary, _label_map_document(self.acceptance))
        self.assertTrue(any(error.startswith("Cellular_and_Nuclear.Chromatin") for error in errors))

        document = copy.deepcopy(_label_map_document(self.acceptance))
        document["attribute_aliases"]["Architecture.Pattern"]["one to several layers"] = ["Solid"]
        errors = check_acceptance(self.acceptance, _vocabulary(self.acceptance), document)
        self.assertIn("label map attribute_aliases differ from the accepted mapping", errors)
        self.assertTrue(any(error.startswith("Architecture.Pattern") for error in errors))

    @unittest.skipUnless(PROMPTS.is_file() and LABEL_MAP.is_file(), "reference/person_d templates are not present")
    def test_reference_assets_match_the_acceptance(self) -> None:
        config = json.loads((COMPONENT / "configs/native.example.json").read_text(encoding="utf-8"))
        prompts_raw, map_raw = PROMPTS.read_bytes(), LABEL_MAP.read_bytes()
        self.assertEqual(self.acceptance["prompt_asset"]["sha256"], config["extraction"]["prompts_sha256"])
        self.assertEqual(self.acceptance["label_map"]["sha256"], config["matching"]["label_map_sha256"])
        self.assertEqual(self.acceptance["prompt_asset"]["sha256"], hashlib.sha256(prompts_raw).hexdigest())
        self.assertEqual(self.acceptance["label_map"]["sha256"], hashlib.sha256(map_raw).hexdigest())
        self.assertEqual(
            [],
            check_acceptance(self.acceptance, json.loads(prompts_raw)["attributes"], json.loads(map_raw)),
        )


if __name__ == "__main__":
    unittest.main()
