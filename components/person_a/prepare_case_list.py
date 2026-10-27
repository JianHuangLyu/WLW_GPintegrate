"""Upstream compatibility adapter: B.ReportTables to canonical CaseListInput.

This utility owns hospital-specific table/WSI discovery. Report Decompose does
not read Excel files directly; it receives the normalized output of this step.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from components.person_a.reference_data import load_dx_candidates
from components.person_a.table_parsers import parse_report_tables
from contracts.runtime import (
    cli_parser,
    load_config,
    load_inputs,
    write_case_list_input,
)


def _source_case(case: dict[str, Any], sample_idx: int) -> dict[str, Any]:
    blocks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for wsi in case["wsis"]:
        block_id = wsi["block_id"] or "block-001"
        blocks[block_id].append(
            {
                "stain_id": wsi["wsi_id"],
                "stain_type": wsi["stain_type"],
                "filename": Path(wsi["wsi_path"]).name,
                "filepath": wsi["wsi_path"],
                "memo": "",
            }
        )
    reports = [
        {
            "report_id": report["report_id"],
            "table_idx": report["table_idx"],
            "source": report["source"],
        }
        for report in case["reports"]
    ]
    raw_reports = list(dict.fromkeys(report["raw_text"] for report in case["reports"]))
    return {
        "sample_idx": sample_idx,
        "case_id": case["case_id"],
        "hospital": case["hospital"],
        "patient_info": {},
        "date": "",
        "source": {"reports": reports},
        "organ": "Breast",
        "report_raw_content": "\n\n".join(raw_reports),
        "tissue_blocks": [
            {
                "block_id": block_id,
                "stains": sorted(stains, key=lambda item: item["stain_id"]),
                "memo": "",
            }
            for block_id, stains in sorted(blocks.items())
        ],
        "memo": "",
    }


def build_case_list(
    report_tables: dict[str, Any],
    manifest_directory: Path,
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    parsed = parse_report_tables(
        report_tables["payload"]["tables"], manifest_directory
    )
    if not parsed.cases:
        raise ValueError(
            "B.ReportTables produced no cases containing both report and WSI data"
        )
    dx_item_list = config.get("dx_item_list")
    if not dx_item_list:
        candidate_reference, _ = load_dx_candidates(
            config["dx_candidates_path"],
            integrity_mode=config.get("asset_integrity", "enforce"),
        )
        dx_item_list = list(candidate_reference["DxItems"])
    return {
        "DxItem_list": list(dx_item_list),
        "case_list": [
            _source_case(case, sample_idx)
            for sample_idx, case in enumerate(parsed.cases)
        ],
    }, parsed.skipped_cases


def main() -> None:
    args = cli_parser(
        "Upstream adapter: B.ReportTables to normalized CaseListInput"
    ).parse_args()
    if len(args.input) != 1:
        raise ValueError("prepare_case_list accepts exactly one B.ReportTables input")
    report_tables = load_inputs(args.input, ["B.ReportTables"])["B.ReportTables"]
    config = load_config(args.config)
    case_list, skipped = build_case_list(
        report_tables,
        Path(args.input[0]).resolve().parent,
        config,
    )
    write_case_list_input(case_list, args.output, single_case=False)
    print(
        f"Prepared {len(case_list['case_list'])} cases; "
        f"skipped {len(skipped)} cases without complete report/WSI input"
    )


if __name__ == "__main__":
    main()
