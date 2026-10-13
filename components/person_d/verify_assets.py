"""Check reference/person_d/ against a Person D native config.

    python -m components.person_d.verify_assets --config components/person_d/configs/native.example.json

Standard library only: run it after copying or downloading the reference assets,
before building or running the image.  It checks every pinned SHA-256, the
few-shot tree layout, and the accepted vocabulary-to-criteria mapping, and exits
1 when anything is missing or differs.  The native run performs the same digest
and layout checks before it writes H.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Iterator, Optional

from components.person_d.assets import PLIP_SUPPORT_FILES, example_layout, file_sha256, tree_sha256
from components.person_d.mapping import check_acceptance, load_acceptance
from contracts.paths import resolve_person_reference_path, sibling_logical_path
from contracts.runtime import load_config


def _files(config: dict[str, Any]) -> Iterator[tuple[str, str, Optional[str]]]:
    extraction, matching = config["extraction"], config["matching"]
    yield "prompts", extraction["prompts_path"], extraction["prompts_sha256"]
    yield "label map", matching["label_map_path"], matching["label_map_sha256"]
    plip_dir = extraction["plip"]["weight_path"].rstrip("/")
    yield "PLIP pytorch_model.bin", f"{plip_dir}/pytorch_model.bin", extraction["plip"]["sha256"]
    support = extraction["plip"]["support_files_sha256"]
    for name in PLIP_SUPPORT_FILES:
        yield f"PLIP {name}", f"{plip_dir}/{name}", support[name]
    yield "CONCH", extraction["conch"]["checkpoint_path"], extraction["conch"]["sha256"]


def _report(status: str, label: str, detail: str) -> bool:
    print(f"{status:<9} {label}: {detail}")
    return status in ("OK", "UNPINNED")


def main() -> None:
    parser = argparse.ArgumentParser(description="丁: verify reference/person_d against a native config")
    parser.add_argument("--config", required=True, help="Person D native config JSON path")
    args = parser.parse_args()
    config = load_config(args.config)
    extraction, matching = config["extraction"], config["matching"]

    results = []
    for label, raw_path, expected in _files(config):
        path = resolve_person_reference_path("person_d", raw_path)
        logical = sibling_logical_path(path)
        if not path.is_file():
            results.append(_report("MISSING", label, logical))
            continue
        actual = file_sha256(path)
        if expected is None:
            results.append(_report("UNPINNED", label, f"{logical} ({actual}; no digest configured)"))
        elif actual == expected:
            results.append(_report("OK", label, f"{logical} ({actual})"))
        else:
            results.append(_report("MISMATCH", label, f"{logical} (expected {expected}, got {actual})"))

    prompts_path = resolve_person_reference_path("person_d", extraction["prompts_path"])
    label_map_path = resolve_person_reference_path("person_d", matching["label_map_path"])
    vocabulary = (
        json.loads(prompts_path.read_text(encoding="utf-8"))["attributes"] if prompts_path.is_file() else None
    )

    if extraction["use_example_prototypes"]:
        example_dir = resolve_person_reference_path("person_d", extraction["example_dir"])
        logical = sibling_logical_path(example_dir)
        if not example_dir.is_dir():
            results.append(_report("MISSING", "few-shot examples", logical))
        else:
            count, actual = tree_sha256(example_dir)
            expected = extraction["example_tree_sha256"]
            status = "OK" if actual == expected else "MISMATCH"
            detail = f"{logical} ({count} files, tree {actual}" + (")" if status == "OK" else f"; expected {expected})")
            results.append(_report(status, "few-shot examples", detail))
            if vocabulary is not None:
                count, usable, ignored = example_layout(example_dir, vocabulary)
                status = "OK" if not ignored else "MISMATCH"
                detail = f"{usable} of {count} files are used by the prototype loader"
                if ignored:
                    detail += f"; not in an option folder: {', '.join(ignored[:5])}"
                results.append(_report(status, "few-shot layout", detail))

    if vocabulary is not None and label_map_path.is_file():
        acceptance = load_acceptance()
        errors = check_acceptance(acceptance, vocabulary, json.loads(label_map_path.read_text(encoding="utf-8")))
        summary = acceptance["summary"]
        if errors:
            results.append(_report("MISMATCH", "mapping acceptance", "; ".join(errors[:5])))
        else:
            detail = (
                f"criteria {acceptance['criteria_version']}: {summary['prompt_options']} vocabulary options, "
                f"{summary['unmapped_prompt_options']} unmapped, {summary['multi_mapped_prompt_options']} multi-mapped, "
                f"{summary['unreachable_criteria_options']} of {summary['criteria_options']} criteria options unreachable "
                "(all classified)"
            )
            results.append(_report("OK", "mapping acceptance", detail))

    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
