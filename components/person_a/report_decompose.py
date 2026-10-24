"""Person A Report Decompose: one normalized CaseList case to D.DxPairs.

Hospital Excel/WSI discovery is intentionally kept outside this runtime
boundary. ``prepare_case_list`` is the upstream compatibility adapter for the
legacy B.ReportTables manifest.
"""

from __future__ import annotations

from copy import deepcopy
import logging
from typing import Any

from components.person_a.reference_data import load_dx_candidates
from components.person_a.report_extraction import ReportExtractionEngine
from contracts.runtime import (
    cli_parser,
    load_case_list_input,
    load_config,
    write_artifact,
)


def _component_version(config: dict[str, Any]) -> str:
    version = config.get("component_version")
    if not isinstance(version, str) or not version:
        raise ValueError("report_decompose config requires component_version")
    return version


def _example_artifact(
    source: dict[str, Any], producer: str
) -> dict[str, Any]:
    """Keep the public repository smoke test independent of private assets."""

    case = deepcopy(source["case_list"][0])
    case_id = case["case_id"]
    records: dict[str, dict[str, Any]] = {}
    for index, name in enumerate(source["DxItem_list"]):
        records[name] = {
            "dx_pair_id": f"{case_id}-example-dx-{index + 1:03d}",
            "source_report_id": f"{case_id}-example-report",
            "DxResultCls": "Not implemented",
            "DxResultTxt": "Example stub; replace with Person A implementation.",
            "DxResultRawTxt": None,
            "referenceBlock": None,
            "referenceType": [],
            "referenceWSI": [],
            "appear_reportTypes": [],
            "optionTypes": "example",
            "has_numericalData": False,
        }
    case["structured_report"] = {
        "reportType": None,
        "reportSubTypes": [],
        "DxItems": records,
    }
    for block in case["tissue_blocks"]:
        for stain in block["stains"]:
            stain["roi_num"] = 0
            stain["roi_list"] = []
    return {
        "contract": "D.DxPairs",
        "schema_version": "2.0",
        "artifact_id": f"D-example-{case_id}",
        "case_id": case_id,
        "producer": producer,
        "payload": {
            "data_mode": "inference",
            "DxItem_list": list(source["DxItem_list"]),
            "reference_versions": {
                "example_stub": {
                    "implemented": False,
                    "purpose": "contract smoke test",
                }
            },
            "case_list": [case],
        },
    }


def _internal_case(source_case: dict[str, Any]) -> dict[str, Any]:
    """Convert the canonical source case to the extraction-engine shape."""

    case_id = source_case["case_id"]
    wsis: list[dict[str, Any]] = []
    for block in source_case["tissue_blocks"]:
        for stain in block["stains"]:
            wsis.append(
                {
                    "wsi_id": stain["stain_id"],
                    "stain_type": stain["stain_type"],
                    "wsi_path": stain["filepath"],
                    "block_id": block["block_id"],
                }
            )
    return {
        "case_id": case_id,
        "hospital": source_case["hospital"],
        "reports": [
            {
                "report_id": f"{case_id}-report",
                "raw_text": source_case["report_raw_content"],
            }
        ],
        "wsis": wsis,
        "observations": [],
        "dx_pairs": [],
    }


def _reference_wsi_ids(
    pair: dict[str, Any], wsis: list[dict[str, Any]], definition: dict[str, Any]
) -> list[str]:
    explicit = pair.get("reference_wsi_ids") or []
    if explicit:
        return list(explicit)
    reference_types = definition.get("referenceType", [])
    if not reference_types:
        return [wsi["wsi_id"] for wsi in wsis]
    allowed = {str(item).upper() for item in reference_types}
    return [
        wsi["wsi_id"]
        for wsi in wsis
        if str(wsi["stain_type"]).upper() in allowed
    ]


def _reference_blocks(
    reference_wsi: list[str], wsis: list[dict[str, Any]]
) -> list[str] | None:
    selected = set(reference_wsi)
    blocks = list(
        dict.fromkeys(
            str(wsi["block_id"])
            for wsi in wsis
            if wsi["wsi_id"] in selected and str(wsi["block_id"])
        )
    )
    return blocks or None


def _structured_case(
    source_case: dict[str, Any],
    extracted: dict[str, Any],
    catalog: dict[str, Any],
    *,
    strict_result_classes: bool,
) -> dict[str, Any]:
    dx_items: dict[str, dict[str, Any]] = {}
    for pair in extracted["dx_pairs"]:
        name = pair["dx_item"]
        definition = catalog[name]
        result = pair["dx_result"]
        allowed_results = definition.get("DxResultCls", [])
        if strict_result_classes and allowed_results and result not in allowed_results:
            raise ValueError(
                f"Case {source_case['case_id']!r} {name} result {result!r} "
                "is not in the configured diagnostic candidates"
            )
        reference_wsi = _reference_wsi_ids(pair, extracted["wsis"], definition)
        dx_items[name] = {
            "dx_pair_id": pair["dx_pair_id"],
            "source_report_id": pair["source_report_id"],
            "DxResultCls": result,
            "DxResultTxt": pair.get("dx_result_text", result),
            "DxResultRawTxt": pair.get("dx_result_raw_text", result),
            "referenceBlock": _reference_blocks(reference_wsi, extracted["wsis"]),
            "referenceType": list(definition.get("referenceType", [])),
            "referenceWSI": reference_wsi,
            "appear_reportTypes": list(definition.get("appear_reportTypes", [])),
            "optionTypes": definition["optionTypes"],
            "has_numericalData": definition["has_numericalData"],
        }

    case = deepcopy(source_case)
    case["structured_report"] = {
        "reportType": None,
        "reportSubTypes": [],
        "DxItems": dx_items,
    }
    for block in case["tissue_blocks"]:
        for stain in block["stains"]:
            stain["roi_num"] = 0
            stain["roi_list"] = []
    return case


def build_artifact(
    source: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    producer = _component_version(config)
    if config.get("mode") == "example":
        return _example_artifact(source, producer)

    candidate_reference, candidate_provenance = load_dx_candidates(
        config["dx_candidates_path"],
        integrity_mode=config.get("asset_integrity", "enforce"),
    )
    full_catalog = candidate_reference["DxItems"]
    requested = source["DxItem_list"]
    unknown = [name for name in requested if name not in full_catalog]
    if unknown:
        raise ValueError(f"CaseList requests unknown DxItems: {unknown}")
    catalog = {name: full_catalog[name] for name in requested}

    extracted = _internal_case(source["case_list"][0])
    extraction = ReportExtractionEngine(catalog, config.get("report_extraction"))
    extraction.fill_case(extracted)
    case = _structured_case(
        source["case_list"][0],
        extracted,
        catalog,
        strict_result_classes=extraction.strict_result_classes,
    )
    case_id = case["case_id"]
    return {
        "contract": "D.DxPairs",
        "schema_version": "2.0",
        "artifact_id": f"D-{case_id}",
        "case_id": case_id,
        "producer": producer,
        "payload": {
            "data_mode": "inference",
            "DxItem_list": list(requested),
            "reference_versions": {
                "dx_candidates": candidate_provenance, **extraction.provenance,
            },
            "case_list": [case],
        },
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = cli_parser("Person A: one CaseList case to D.DxPairs").parse_args()
    if len(args.input) != 1:
        raise ValueError("report_decompose accepts exactly one CaseList input")
    source = load_case_list_input(args.input[0], single_case=True)
    config = load_config(args.config)
    write_artifact(build_artifact(source, config), args.output, "D.DxPairs")


if __name__ == "__main__":
    main()
