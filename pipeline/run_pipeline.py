"""Outer CaseList runner for the contract-first single-case DAG."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.paths import RUN_ROOT, resolve_run_path, sibling_logical_path
from contracts.runtime import load_case_list_input, write_case_list_input


INPUTS = RUN_ROOT / "input" / "pipeline"
CONFIGS = {
    "report_decompose": ROOT / "components/person_a/configs/example.json",
    "knowledge_retrieval": ROOT / "components/person_b/configs/example.json",
    "query_generation": ROOT / "components/person_a/configs/example.json",
    "interest_pattern": ROOT / "components/person_c/configs/example.json",
    "visual_filter": ROOT / "components/person_d/configs/example.json",
    "clee": ROOT / "components/person_e/configs/default.json",
}


def _case_directory_name(case_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", case_id).strip("._")
    if not safe:
        raise ValueError(f"case_id cannot be represented as a directory: {case_id!r}")
    return safe


def run_component(module: str, inputs: list[Path], output: Path, config: Path) -> None:
    command = [sys.executable, "-m", module]
    for input_path in inputs:
        command.extend(["--input", str(input_path)])
    command.extend(["--output", str(output), "--config", str(config)])
    print(f"\n=== {module} ===", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the contract pipeline once per CaseList case"
    )
    parser.add_argument(
        "--case-list",
        type=Path,
        default=INPUTS / "cases.json",
        help="CaseList input below the sibling run directory",
    )
    parser.add_argument(
        "--literature",
        type=Path,
        default=INPUTS / "A_literature.json",
        help="Shared A.Literature artifact used for every case",
    )
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=RUN_ROOT / "output" / "pipeline",
        help="Output directory below sibling run/",
    )
    args = parser.parse_args()
    case_list_path = resolve_run_path(args.case_list)
    literature = resolve_run_path(args.literature)
    artifacts = resolve_run_path(args.artifacts)
    artifacts.mkdir(parents=True, exist_ok=True)
    source = load_case_list_input(case_list_path)

    completed_cases = []
    used_directories: set[str] = set()
    for raw_case in source["case_list"]:
        case_id = raw_case["case_id"]
        directory_name = _case_directory_name(case_id)
        if directory_name in used_directories:
            raise ValueError(f"Case directory collision after normalization: {case_id!r}")
        used_directories.add(directory_name)

        case_artifacts = artifacts / "cases" / directory_name
        case_input = case_artifacts / "case_input.json"
        d = case_artifacts / "D_dx_pairs.json"
        e = case_artifacts / "E_rois.json"
        f = case_artifacts / "F_chunks.json"
        g = case_artifacts / "G_queries.json"
        h = case_artifacts / "H_matches.json"
        selected_rois = case_artifacts / "I_selected_rois.json"
        write_case_list_input(
            {"DxItem_list": source["DxItem_list"], "case_list": [raw_case]}, case_input
        )

        print(f"\n##### case {case_id} #####", flush=True)
        run_component(
            "components.person_a.report_decompose",
            [case_input],
            d,
            CONFIGS["report_decompose"],
        )
        run_component(
            "components.person_c.interest_pattern",
            [case_input],
            e,
            CONFIGS["interest_pattern"],
        )
        run_component(
            "components.person_b.knowledge_retrieval",
            [literature, d],
            f,
            CONFIGS["knowledge_retrieval"],
        )
        run_component(
            "components.person_a.query_generation",
            [d, f],
            g,
            CONFIGS["query_generation"],
        )
        run_component(
            "components.person_d.visual_filter",
            [e, g],
            h,
            CONFIGS["visual_filter"],
        )
        run_component(
            "components.person_e.clee",
            [d, h],
            selected_rois,
            CONFIGS["clee"],
        )
        completed_cases.append(
            {
                "case_id": case_id,
                "case_input_path": case_input.relative_to(artifacts).as_posix(),
                "selected_rois_path": selected_rois.relative_to(artifacts).as_posix(),
            }
        )

    run_manifest = {
        "case_list": sibling_logical_path(case_list_path),
        "literature_artifact": sibling_logical_path(literature),
        "completed_cases": completed_cases,
    }
    run_manifest_path = artifacts / "run_manifest.json"
    run_manifest_path.write_text(
        json.dumps(run_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"\nPipeline complete: {len(completed_cases)} cases. "
        f"Run manifest: {run_manifest_path}"
    )


if __name__ == "__main__":
    main()
