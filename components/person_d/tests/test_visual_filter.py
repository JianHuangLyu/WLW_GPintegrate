from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from components.person_d.visual_filter import build_example_artifact, build_native_artifact
from contracts.metadata import iter_rois
from contracts.paths import PROJECT_ROOT, REFERENCE_ROOT, RUN_ROOT
from contracts.runtime import validate_artifact


COMPONENT = Path(__file__).resolve().parents[1]
EXAMPLES = COMPONENT / "examples"
STAGE = "visual_attributes_matching_filter"
LABEL_MAP = {
    "version": "test",
    "criteria_version": "1.2.1",
    "global_aliases": {"N/A": ["Unable to confirm"]},
    "attribute_aliases": {},
}
POSITIVE = {
    "Cellular_and_Nuclear": {
        "Cytological_Atypia": ["High-grade/Severe"],
        "Chromatin": ["Hyperchromatic"],
        "Cell_Pleomorphism": ["Moderate"],
    }
}
NEGATIVE = {"Cellular_and_Nuclear": {"Chromatin": ["Regular"], "Cell_Pleomorphism": ["Moderate"]}}


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def _full_vocabulary(g: dict) -> dict:
    """One vocabulary label per criteria option of the example G, so every option is reachable."""

    record = g["payload"]["case_list"][0]["structured_report"]["DxItems"]["Histologic_Type"]
    criteria = record["visualAttrQueries"][0]["diagnosticCriteria"]
    return {
        category: {attribute: list(spec["options"]) for attribute, spec in attributes.items()}
        for category, attributes in criteria["visualAttrs"].items()
    }


def _with_evaluation_mode(g: dict) -> dict:
    g = copy.deepcopy(g)
    g["payload"]["data_mode"] = "evaluation"
    return g


def _with_negative_width(e: dict) -> dict:
    e = copy.deepcopy(e)
    next(roi for _, roi in iter_rois(e["payload"]))["level0_info"]["xywh"][2] = -1
    return e


class _FakeExtractor:
    def __init__(self, labels_by_roi: dict[str, dict]):
        self.labels_by_roi = labels_by_roi
        self.calls: list[str] = []

    def extract(self, image: Image.Image) -> dict:
        roi_id = image.info["roi_id"]
        self.calls.append(roi_id)
        consistent = self.labels_by_roi[roi_id]
        models = {
            name: {
                category: {
                    attribute: {"prediction": labels[0] if labels else "N/A", "scores": {"N/A": 0.1}}
                    for attribute, labels in attributes.items()
                }
                for category, attributes in consistent.items()
            }
            for name in ("PLIP", "CONCH")
        }
        return {"consistent": consistent, "models": models}

    def example_metadata(self) -> dict:
        return {"PLIP": {"enabled": False}, "CONCH": {"enabled": False}}


class _FakeReader:
    def __init__(self) -> None:
        self.reads: list[tuple[str, str]] = []

    def read(self, stain: dict, roi: dict) -> Image.Image:
        self.reads.append((stain["stain_id"], roi["roi_id"]))
        image = Image.new("RGB", (8, 8))
        image.info["roi_id"] = roi["roi_id"]
        return image


class NativeVisualFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = REFERENCE_ROOT / "person_d" / "template_ref"
        directory.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=directory)
        self.addCleanup(temp.cleanup)
        label_map = Path(temp.name) / "criteria_label_map.json"
        label_map.write_text(json.dumps(LABEL_MAP), encoding="utf-8")
        self.config = json.loads(
            (COMPONENT / "configs/native.example.json").read_text(encoding="utf-8")
        )
        self.config["matching"]["label_map_path"] = str(label_map)
        self.config["matching"]["label_map_sha256"] = hashlib.sha256(label_map.read_bytes()).hexdigest()
        self.e = _load("E_rois.valid.json")
        self.g = _load("G_queries.valid.json")

    def _build(self, extractor: _FakeExtractor, e=None, g=None, reader=None, vocabulary=None):
        loads: list[int] = []

        def factory() -> _FakeExtractor:
            loads.append(1)
            return extractor

        artifact = build_native_artifact(
            e or self.e,
            g or self.g,
            self.config,
            extractor_factory=factory,
            image_reader=reader or _FakeReader(),
            extraction_info={"backend": "plip+conch"},
            vocabulary=vocabulary or _full_vocabulary(self.g),
        )
        return artifact, loads

    def test_all_rois_are_kept_and_reference_rois_are_matched(self) -> None:
        extractor = _FakeExtractor(
            {
                "case-001-case-001-he-roi-001": POSITIVE,
                "case-001-case-001-he-roi-002": NEGATIVE,
            }
        )
        reader = _FakeReader()
        artifact, loads = self._build(extractor, reader=reader)
        validate_artifact(artifact, "H.MatchedROIs")

        self.assertEqual(
            [roi["roi_id"] for _, roi in iter_rois(self.e["payload"])],
            [roi["roi_id"] for _, roi in iter_rois(artifact["payload"])],
        )
        self.assertEqual(1, len(loads))
        self.assertEqual(
            [("case-001-he", "case-001-case-001-he-roi-001"), ("case-001-he", "case-001-case-001-he-roi-002")],
            reader.reads,
        )

        decisions = {}
        for stain, roi in iter_rois(artifact["payload"]):
            self.assertEqual("interest_pattern_extraction", roi["selection_history"][0]["stage"])
            for event in roi["selection_history"][1:]:
                self.assertEqual(STAGE, event["stage"])
                key = (roi["roi_id"], event["dx_pair_id"], event.get("query_id"))
                self.assertNotIn(key, decisions)
                decisions[key] = event
        def outcome(roi: str, dx: str, query: str) -> tuple[str, str]:
            event = decisions[(f"case-001-case-001-{roi}", f"case-001-dx-{dx}", f"case-001-query-{query}")]
            return event["status"], event["reason"]

        # query-001 carries Must_True options on attributes the backend never extracts.
        self.assertEqual(("skipped", "insufficient_visual_evidence"), outcome("he-roi-001", "001", "001"))
        self.assertFalse(
            decisions[("case-001-case-001-he-roi-001", "case-001-dx-001", "case-001-query-001")]["selected"]
        )
        self.assertEqual(("rejected", "must_condition_failed"), outcome("he-roi-002", "002", "002"))
        self.assertEqual(("skipped", "query_unmapped"), outcome("he-roi-002", "002", "003"))
        for roi in ("he-roi-001", "he-roi-002"):
            self.assertEqual(("selected", "visual_attributes_match"), outcome(roi, "001", "004"))
            self.assertEqual(("rejected", "score_below_threshold"), outcome(roi, "001", "005"))
        self.assertEqual(("skipped", "stain_not_in_reference_wsi"), outcome("er-roi-001", "001", "001"))
        # Every pair in the example has queries, so every event is query-level.
        self.assertTrue(
            all(event.get("query_id") and event.get("criteria_status") for event in decisions.values())
        )

        payload = artifact["payload"]
        self.assertTrue(payload["reference_versions"]["visual_attribute_extraction"]["models_loaded"])
        self.assertEqual(
            "1.2.1",
            payload["reference_versions"]["visual_matching_filter"]["label_map"]["criteria_version"],
        )

    def test_pair_without_queries_gets_one_pair_level_event(self) -> None:
        g = copy.deepcopy(self.g)
        records = g["payload"]["case_list"][0]["structured_report"]["DxItems"]
        records["Microcalcification"]["visualAttrQueries"] = []
        extractor = _FakeExtractor(
            {
                "case-001-case-001-he-roi-001": POSITIVE,
                "case-001-case-001-he-roi-002": NEGATIVE,
            }
        )
        artifact, _ = self._build(extractor, g=g)
        validate_artifact(artifact, "H.MatchedROIs")
        for stain, roi in iter_rois(artifact["payload"]):
            pair_events = [
                event
                for event in roi["selection_history"][1:]
                if event["dx_pair_id"] == "case-001-dx-002"
            ]
            self.assertEqual(1, len(pair_events))
            self.assertNotIn("query_id", pair_events[0])
            expected = "no_visual_attr_query" if stain["stain_id"] == "case-001-he" else "stain_not_in_reference_wsi"
            self.assertEqual(("skipped", expected), (pair_events[0]["status"], pair_events[0]["reason"]))
            query_events = [
                event
                for event in roi["selection_history"][1:]
                if event["dx_pair_id"] == "case-001-dx-001"
            ]
            self.assertEqual(3, len(query_events))
            self.assertTrue(all("query_id" in event for event in query_events))

    def test_unmapped_query_is_skipped_without_loading_models(self) -> None:
        g = copy.deepcopy(self.g)
        for record in g["payload"]["case_list"][0]["structured_report"]["DxItems"].values():
            for query in record["visualAttrQueries"]:
                query["criteria_status"] = "unmapped"
                query["diagnosticCriteria"] = None
        artifact, loads = self._build(_FakeExtractor({}), g=g)
        validate_artifact(artifact, "H.MatchedROIs")
        self.assertEqual([], loads)
        reasons = {
            event["reason"]
            for _, roi in iter_rois(artifact["payload"])
            for event in roi["selection_history"][1:]
        }
        self.assertEqual({"query_unmapped", "stain_not_in_reference_wsi"}, reasons)
        self.assertFalse(
            artifact["payload"]["reference_versions"]["visual_attribute_extraction"]["models_loaded"]
        )

    def test_empty_roi_case_succeeds_without_models(self) -> None:
        e = copy.deepcopy(self.e)
        for block in e["payload"]["case_list"][0]["tissue_blocks"]:
            for stain in block["stains"]:
                stain["roi_list"], stain["roi_num"] = [], 0
        artifact, loads = self._build(_FakeExtractor({}), e=e)
        validate_artifact(artifact, "H.MatchedROIs")
        self.assertEqual([], loads)
        self.assertEqual([], list(iter_rois(artifact["payload"])))

    def test_model_disagreement_is_skipped(self) -> None:
        empty = {"Cellular_and_Nuclear": {"Chromatin": []}}
        extractor = _FakeExtractor(
            {"case-001-case-001-he-roi-001": empty, "case-001-case-001-he-roi-002": empty}
        )
        artifact, _ = self._build(extractor)
        validate_artifact(artifact, "H.MatchedROIs")
        he_events = [
            event
            for stain, roi in iter_rois(artifact["payload"])
            if stain["stain_id"] == "case-001-he"
            for event in roi["selection_history"][1:]
        ]
        self.assertEqual(
            {"insufficient_visual_evidence", "query_unmapped"},
            {event["reason"] for event in he_events},
        )
        self.assertTrue(all("query_id" in event for event in he_events))

    def test_identity_and_linkage_errors_fail(self) -> None:
        extractor = _FakeExtractor({})
        e = copy.deepcopy(self.e)
        e["case_id"] = e["payload"]["case_list"][0]["case_id"] = "case-other"
        with self.assertRaisesRegex(ValueError, "same case"):
            self._build(extractor, e=e)

        g = copy.deepcopy(self.g)
        g["payload"]["case_list"][0]["tissue_blocks"][0]["stains"].pop()
        with self.assertRaisesRegex(ValueError, "stain_id sets differ"):
            self._build(extractor, g=g)

        g = copy.deepcopy(self.g)
        record = g["payload"]["case_list"][0]["structured_report"]["DxItems"]["Histologic_Type"]
        record["visualAttrQueries"][0]["dx_pair_id"] = "case-001-dx-999"
        with self.assertRaisesRegex(ValueError, "dx_pair_id"):
            self._build(extractor, g=g)

    def test_data_mode_and_geometry_are_checked_in_both_modes(self) -> None:
        cases = (
            (self.e, _with_evaluation_mode(self.g), "data_mode values differ"),
            (_with_negative_width(self.e), self.g, "invalid level0_info.xywh"),
        )
        for e, g, message in cases:
            with self.assertRaisesRegex(ValueError, message):
                build_example_artifact(e, g, "person-d/visual-filter:0.2.0")
            with self.assertRaisesRegex(ValueError, message):
                self._build(_FakeExtractor({}), e=e, g=g)

    def test_criteria_option_the_vocabulary_cannot_reach_blocks_selection(self) -> None:
        vocabulary = _full_vocabulary(self.g)
        vocabulary["Architecture"]["Pattern"].remove("Simple Tubular/Branching Structures")
        extractor = _FakeExtractor(
            {
                "case-001-case-001-he-roi-001": POSITIVE,
                "case-001-case-001-he-roi-002": POSITIVE,
            }
        )
        artifact, _ = self._build(extractor, vocabulary=vocabulary)
        validate_artifact(artifact, "H.MatchedROIs")
        for stain, roi in iter_rois(artifact["payload"]):
            if stain["stain_id"] != "case-001-he":
                continue
            events = {event["query_id"]: event for event in roi["selection_history"][1:]}
            matching = roi["visualAttrs_info"]["matching"]
            # In the real criteria this option is Must_False, and the vocabulary cannot reach it.
            self.assertEqual("skipped", events["case-001-query-001"]["status"])
            self.assertIn("Architecture.Pattern", matching["case-001-query-001"]["must_unverifiable"])
            # The synthetic queries carry no Must condition, so reachability does not affect them.
            self.assertEqual("selected", events["case-001-query-004"]["status"])
            self.assertEqual("rejected", events["case-001-query-005"]["status"])

    def test_malformed_criteria_fail_at_the_input_boundary(self) -> None:
        g = copy.deepcopy(self.g)
        record = g["payload"]["case_list"][0]["structured_report"]["DxItems"]["Histologic_Type"]
        del record["visualAttrQueries"][0]["diagnosticCriteria"]["version"]
        with self.assertRaisesRegex(ValueError, "case-001-query-001 diagnosticCriteria is missing 'version'"):
            self._build(_FakeExtractor({}), g=g)
        with self.assertRaisesRegex(ValueError, "diagnosticCriteria is missing 'version'"):
            build_example_artifact(self.e, g, "person-d/visual-filter:0.2.0")

    def test_label_map_digest_is_enforced(self) -> None:
        self.config["matching"]["label_map_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "label map SHA-256 mismatch"):
            self._build(_FakeExtractor({}))

    def test_extraction_errors_propagate(self) -> None:
        class _Broken(_FakeExtractor):
            def extract(self, image):
                raise RuntimeError("CUDA out of memory")

        with self.assertRaisesRegex(RuntimeError, "CUDA"):
            self._build(_Broken({}))


class ExampleModeTests(unittest.TestCase):
    def test_example_mode_matches_canonical_expected_output(self) -> None:
        config = json.loads((COMPONENT / "configs/example.json").read_text(encoding="utf-8"))
        artifact = build_example_artifact(
            _load("E_rois.valid.json"), _load("G_queries.valid.json"), config["component_version"]
        )
        validate_artifact(artifact, "H.MatchedROIs")
        self.assertEqual(_load("H_matches.expected.json"), artifact)

    def test_cli_rejects_invalid_inputs_without_writing_h(self) -> None:
        RUN_ROOT.mkdir(parents=True, exist_ok=True)
        e, g = _load("E_rois.valid.json"), _load("G_queries.valid.json")
        with tempfile.TemporaryDirectory(dir=RUN_ROOT) as directory:
            for name, (e_doc, g_doc) in {
                "data_mode": (e, _with_evaluation_mode(g)),
                "geometry": (_with_negative_width(e), g),
            }.items():
                e_path, g_path = Path(directory) / f"{name}_E.json", Path(directory) / f"{name}_G.json"
                e_path.write_text(json.dumps(e_doc), encoding="utf-8")
                g_path.write_text(json.dumps(g_doc), encoding="utf-8")
                output = Path(directory) / f"{name}_H.json"
                result = subprocess.run(
                    [
                        sys.executable, "-m", "components.person_d.visual_filter",
                        "--input", str(e_path), "--input", str(g_path),
                        "--output", str(output),
                        "--config", "components/person_d/configs/example.json",
                    ],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                )
                self.assertNotEqual(0, result.returncode, f"{name}: {result.stdout}")
                self.assertFalse(output.exists(), name)


if __name__ == "__main__":
    unittest.main()
