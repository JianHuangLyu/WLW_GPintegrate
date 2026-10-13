"""Person D visual filter: E.ROIs + G.VisualAttributeQueries -> H.MatchedROIs.

``mode: example`` is the contract-only stub used by the repository pipeline
test: it performs no image or visual-attribute inference and marks every ROI
skipped.  ``mode: native`` extracts visual attributes from each reference-WSI
ROI with PLIP and CONCH and matches them against the G diagnosticCriteria.
Both modes run the same input validation (``validate_inputs``).
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Callable

from components.person_d.assets import check_digest, required_digest
from components.person_d.geometry import roi_geometry
from components.person_d.matching_filter import LabelMap, MatchingSettings, match_query
from contracts.metadata import ensure_same_case, single_case
from contracts.paths import resolve_person_reference_path, sibling_logical_path
from contracts.runtime import cli_parser, load_config, load_inputs, write_artifact


STAGE = "visual_attributes_matching_filter"
NATIVE_BACKEND = "plip+conch"


def _producer(config: dict[str, Any]) -> str:
    producer = config.get("component_version")
    if config.get("mode") != "example" or not isinstance(producer, str) or not producer:
        raise ValueError("Person D example requires an example config with component_version")
    return producer


def build_example_artifact(
    e_artifact: dict[str, Any], g_artifact: dict[str, Any], producer: str
) -> dict[str, Any]:
    case_id = validate_inputs(e_artifact, g_artifact)
    e_case = deepcopy(single_case(e_artifact))
    g_case = single_case(g_artifact)
    e_case["structured_report"] = deepcopy(g_case["structured_report"])

    records = list(e_case["structured_report"]["DxItems"].values())
    for block in e_case["tissue_blocks"]:
        for stain in block["stains"]:
            for roi in stain["roi_list"]:
                roi["visualAttrs"] = {}
                roi["visualAttrs_info"] = {
                    "implemented": False,
                    "purpose": "contract smoke test",
                }
                event_records = records or [None]
                for record in event_records:
                    event: dict[str, Any] = {
                        "stage": "visual_attributes_matching_filter",
                        "owner": "person_D",
                        "artifact_contract": "H.MatchedROIs",
                        "action": "legality_evaluated",
                        "status": "skipped",
                        "selected": False,
                        "reason": "example_stub_no_evaluation",
                        "producer": producer,
                    }
                    if record is not None:
                        event["dx_pair_id"] = record["dx_pair_id"]
                    roi["selection_history"].append(event)
            stain["roi_num"] = len(stain["roi_list"])

    payload: dict[str, Any] = {
        "data_mode": g_artifact["payload"]["data_mode"],
        "DxItem_list": list(g_artifact["payload"]["DxItem_list"]),
        "reference_versions": deepcopy(
            g_artifact["payload"].get("reference_versions", {})
        ),
        "case_list": [e_case],
    }
    payload["reference_versions"]["example_visual_stub"] = {
        "implemented": False,
        "purpose": "contract smoke test",
    }
    if "candidateReference" in g_artifact["payload"]:
        payload["candidateReference"] = deepcopy(
            g_artifact["payload"]["candidateReference"]
        )

    return {
        "contract": "H.MatchedROIs",
        "schema_version": "2.0",
        "artifact_id": f"H-example-{case_id}",
        "case_id": case_id,
        "producer": producer,
        "payload": payload,
    }


def _native_producer(config: dict[str, Any]) -> str:
    producer = config.get("component_version")
    if config.get("mode") != "native" or not isinstance(producer, str) or not producer:
        raise ValueError("Person D native mode requires a native config with component_version")
    return producer


def _load_label_map(matching_config: dict[str, Any]) -> tuple[LabelMap, dict[str, Any]]:
    expected = required_digest(matching_config, "label_map_sha256", "matching")
    path = resolve_person_reference_path("person_d", matching_config["label_map_path"])
    if not path.is_file():
        raise FileNotFoundError(f"Person D label map does not exist: {path}")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    check_digest(digest, expected, "Person D label map")
    document = json.loads(raw.decode("utf-8"))
    return LabelMap.from_document(document), {
        "path": sibling_logical_path(path),
        "version": document.get("version"),
        "criteria_version": document["criteria_version"],
        "sha256": digest,
    }


def _event(producer: str, status: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {
        "stage": STAGE,
        "owner": "person_D",
        "artifact_contract": "H.MatchedROIs",
        "action": "legality_evaluated",
        "status": status,
        "selected": status == "selected",
        "reason": reason,
        "producer": producer,
        **extra,
    }


def _stain_ids(case: dict[str, Any]) -> list[str]:
    return [stain["stain_id"] for block in case["tissue_blocks"] for stain in block["stains"]]


def _check_criteria(query: dict[str, Any]) -> None:
    """Reject a mapped query whose diagnosticCriteria cannot be matched."""

    criteria = query.get("diagnosticCriteria")
    if query["criteria_status"] != "mapped" or not criteria:
        return
    query_id = query["query_id"]
    if not isinstance(criteria.get("version"), str) or not criteria["version"]:
        raise ValueError(f"Query {query_id} diagnosticCriteria is missing 'version'")
    visual_attrs = criteria.get("visualAttrs")
    if not isinstance(visual_attrs, dict):
        raise ValueError(f"Query {query_id} diagnosticCriteria is missing 'visualAttrs'")
    for category, attributes in visual_attrs.items():
        for attribute, spec in attributes.items():
            if not isinstance(spec.get("options"), list) or not isinstance(spec.get("conditions"), dict):
                raise ValueError(
                    f"Query {query_id} diagnosticCriteria {category}.{attribute} needs 'options' and 'conditions'"
                )


def _check_linkage(e_case: dict[str, Any], g_case: dict[str, Any]) -> None:
    e_stains = _stain_ids(e_case)
    if set(e_stains) != set(_stain_ids(g_case)):
        raise ValueError(
            f"E/G stain_id sets differ: E={sorted(e_stains)}, G={sorted(_stain_ids(g_case))}"
        )
    roi_ids = [
        roi["roi_id"]
        for block in e_case["tissue_blocks"]
        for stain in block["stains"]
        for roi in stain["roi_list"]
    ]
    if len(roi_ids) != len(set(roi_ids)):
        raise ValueError("E contains duplicate roi_id values")

    query_ids: list[str] = []
    for DxItem, record in g_case["structured_report"]["DxItems"].items():
        unknown = set(record["referenceWSI"]) - set(e_stains)
        if unknown:
            raise ValueError(f"{DxItem} referenceWSI names unknown stains: {sorted(unknown)}")
        for query in record.get("visualAttrQueries", []):
            if query["dx_pair_id"] != record["dx_pair_id"]:
                raise ValueError(
                    f"Query {query['query_id']} dx_pair_id does not match {DxItem}"
                )
            query_ids.append(query["query_id"])
            _check_criteria(query)
    if len(query_ids) != len(set(query_ids)):
        raise ValueError("G contains duplicate query_id values")


def validate_inputs(e_artifact: dict[str, Any], g_artifact: dict[str, Any]) -> str:
    """Input boundary shared by example and native mode; returns the case_id.

    Checks case identity, data_mode, stain / pair / query linkage, the shape of every
    mapped diagnosticCriteria and the metadata geometry of every ROI, so both modes
    accept or reject the same E/G pair.
    """

    case_id = ensure_same_case(e_artifact, g_artifact)
    e_mode, g_mode = e_artifact["payload"]["data_mode"], g_artifact["payload"]["data_mode"]
    if e_mode != g_mode:
        raise ValueError(f"E/G data_mode values differ: E={e_mode!r}, G={g_mode!r}")
    e_case = single_case(e_artifact)
    _check_linkage(e_case, single_case(g_artifact))
    for block in e_case["tissue_blocks"]:
        for stain in block["stains"]:
            for roi in stain["roi_list"]:
                roi_geometry(roi)
    return case_id


def _model_summary(models: dict[str, Any]) -> dict[str, Any]:
    return {
        name: {
            category: {
                attribute: {
                    "prediction": info["prediction"],
                    "scores": {option: round(score, 6) for option, score in info["scores"].items()},
                }
                for attribute, info in attributes.items()
            }
            for category, attributes in prediction.items()
        }
        for name, prediction in models.items()
    }


def build_native_artifact(
    e_artifact: dict[str, Any],
    g_artifact: dict[str, Any],
    config: dict[str, Any],
    *,
    extractor_factory: Callable[[], Any],
    image_reader: Any,
    extraction_info: dict[str, Any],
    vocabulary: dict[str, dict[str, list[str]]],
) -> dict[str, Any]:
    """Build H; models load only when at least one ROI needs extraction.

    ``vocabulary`` is the extraction vocabulary (category -> attribute -> labels).
    """

    case_id = validate_inputs(e_artifact, g_artifact)
    producer = _native_producer(config)
    settings = MatchingSettings.from_config(config["matching"])
    label_map, label_map_info = _load_label_map(config["matching"])
    data_mode = g_artifact["payload"]["data_mode"]

    case = deepcopy(single_case(e_artifact))
    g_case = single_case(g_artifact)
    case["structured_report"] = deepcopy(g_case["structured_report"])
    records = case["structured_report"]["DxItems"]

    extractor = None
    for block in case["tissue_blocks"]:
        for stain in block["stains"]:
            for roi in stain["roi_list"]:
                events: list[dict[str, Any] | None] = []
                pending: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
                if not records:
                    events.append(_event(producer, "skipped", "no_diagnostic_pair"))
                for record in records.values():
                    dx_pair_id = record["dx_pair_id"]
                    queries = record.get("visualAttrQueries", [])
                    is_reference = stain["stain_id"] in record["referenceWSI"]
                    if not queries:
                        # Pair-level event: the pair has no query to link to.
                        reason = "no_visual_attr_query" if is_reference else "stain_not_in_reference_wsi"
                        events.append(_event(producer, "skipped", reason, dx_pair_id=dx_pair_id))
                        continue
                    for query in queries:
                        linkage = {
                            "dx_pair_id": dx_pair_id,
                            "query_id": query["query_id"],
                            "criteria_status": query["criteria_status"],
                        }
                        if not is_reference:
                            events.append(
                                _event(producer, "skipped", "stain_not_in_reference_wsi", **linkage)
                            )
                            continue
                        if query["criteria_status"] != "mapped" or not query["diagnosticCriteria"]:
                            events.append(
                                _event(producer, "skipped", "query_unmapped", **linkage)
                            )
                            continue
                        pending.append((len(events), query, linkage))
                        events.append(None)

                if pending:
                    if extractor is None:
                        extractor = extractor_factory()
                    extraction = extractor.extract(image_reader.read(stain, roi))
                    matching: dict[str, Any] = {}
                    for index, query, linkage in pending:
                        result = match_query(
                            extraction["consistent"],
                            query["diagnosticCriteria"],
                            label_map,
                            settings,
                            vocabulary,
                        )
                        details: dict[str, Any] = {"backend": NATIVE_BACKEND}
                        if result["status"] != "skipped":
                            details.update(
                                score=result["score"],
                                threshold=settings.score_threshold,
                                comparison=">=",
                                must_true_passed=result["must_true_passed"],
                                must_false_passed=result["must_false_passed"],
                                matched_attributes=result["matched_attributes"],
                                failed_attributes=result["failed_attributes"],
                            )
                        events[index] = _event(
                            producer, result["status"], result["reason"], **linkage, **details
                        )
                        matching[query["query_id"]] = {
                            key: result[key]
                            for key in (
                                "status",
                                "evaluated_count",
                                "must_true_unverified",
                                "must_unverifiable",
                                "attributes",
                            )
                        }
                    roi["visualAttrs"] = extraction["consistent"]
                    roi["visualAttrs_info"] = {
                        "backend": NATIVE_BACKEND,
                        "producer": producer,
                        "models": _model_summary(extraction["models"]),
                        "matching": matching,
                    }
                roi["selection_history"].extend(events)
            stain["roi_num"] = len(stain["roi_list"])

    reference_versions = deepcopy(g_artifact["payload"].get("reference_versions", {}))
    own_entries = {
        "roi_source": {
            "artifact_id": e_artifact["artifact_id"],
            "producer": e_artifact["producer"],
            "reference_versions": deepcopy(e_artifact["payload"].get("reference_versions", {})),
        },
        "visual_attribute_extraction": {
            **deepcopy(extraction_info),
            "models_loaded": extractor is not None,
            **(
                {"example_prototypes": extractor.example_metadata()}
                if extractor is not None
                else {}
            ),
            **(
                {"example_tree": dict(extractor.example_tree)}
                if getattr(extractor, "example_tree", None)
                else {}
            ),
        },
        "visual_matching_filter": {
            "label_map": label_map_info,
            "condition_weights": dict(settings.condition_weights),
            "score_threshold": settings.score_threshold,
            "comparison": ">=",
            "min_evaluated_attributes": settings.min_evaluated_attributes,
            "unverified_must_true": settings.unverified_must_true,
        },
    }
    collisions = set(own_entries) & set(reference_versions)
    if collisions:
        raise ValueError(f"G reference_versions already defines {sorted(collisions)}")
    reference_versions.update(own_entries)

    payload: dict[str, Any] = {
        "data_mode": data_mode,
        "DxItem_list": list(g_artifact["payload"]["DxItem_list"]),
        "reference_versions": reference_versions,
        "case_list": [case],
    }
    if "candidateReference" in g_artifact["payload"]:
        payload["candidateReference"] = deepcopy(g_artifact["payload"]["candidateReference"])

    return {
        "contract": "H.MatchedROIs",
        "schema_version": "2.0",
        "artifact_id": f"H-{case_id}",
        "case_id": case_id,
        "producer": producer,
        "payload": payload,
    }


def _run_native(
    e_artifact: dict[str, Any], g_artifact: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    from components.person_d.roi_reader import ROIImageReader
    from components.person_d.visual_attribute_extraction import (
        extraction_provenance,
        load_extractor,
        load_prompt_document,
    )

    device = config["device"]
    if not isinstance(device, str) or not device:
        raise ValueError("Person D native config requires a device")
    extraction_config = config["extraction"]
    with ROIImageReader() as reader:
        return build_native_artifact(
            e_artifact,
            g_artifact,
            config,
            extractor_factory=lambda: load_extractor(extraction_config, device),
            image_reader=reader,
            extraction_info=extraction_provenance(extraction_config, device),
            vocabulary=load_prompt_document(extraction_config)[1]["attributes"],
        )


def main() -> None:
    args = cli_parser("丁: match E ROIs against G visual attribute queries into H").parse_args()
    inputs = load_inputs(args.input, ["E.ROIs", "G.VisualAttributeQueries"])
    config = load_config(args.config)
    if config.get("mode") == "native":
        artifact = _run_native(
            inputs["E.ROIs"], inputs["G.VisualAttributeQueries"], config
        )
    else:
        artifact = build_example_artifact(
            inputs["E.ROIs"],
            inputs["G.VisualAttributeQueries"],
            _producer(config),
        )
    write_artifact(artifact, args.output, "H.MatchedROIs")


if __name__ == "__main__":
    main()
