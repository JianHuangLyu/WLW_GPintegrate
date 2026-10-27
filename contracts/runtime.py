"""Small dependency-free runtime for the demo's JSON Schemas.

Production code should use a complete JSON Schema implementation or generated
Pydantic models.  This validator intentionally implements only the keywords
used by the schemas in this repository.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from contracts.paths import resolve_component_config_path, resolve_run_path


ROOT = Path(__file__).resolve().parent
SCHEMA_DIR = ROOT / "schemas"
CASE_LIST_SCHEMA = SCHEMA_DIR / "case_list_input.schema.json"

CONTRACT_SCHEMAS = {
    "A.Literature": "A_literature.schema.json",
    "B.ReportTables": "B_report_tables.schema.json",
    "D.DxPairs": "D_dx_pairs.schema.json",
    "D.DxPairsIndex": "D_dx_pairs_index.schema.json",
    "E.ROIs": "E_rois.schema.json",
    "F.Chunks": "F_chunks.schema.json",
    "G.VisualAttributeQueries": "G_visual_attribute_queries.schema.json",
    "H.MatchedROIs": "H_matched_rois.schema.json",
    "I.CLEESelectedROIs": "I_clee_selected_rois.schema.json",
}


class ContractError(ValueError):
    """Raised when an artifact violates its declared contract."""


def _typename(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return type(value).__name__


def _is_type(value: Any, expected: str | list[str]) -> bool:
    if isinstance(expected, list):
        return any(_is_type(value, item) for item in expected)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise ContractError(f"Unsupported schema type in demo validator: {expected}")


def _resolve_pointer(document: dict[str, Any], pointer: str) -> dict[str, Any]:
    current: Any = document
    if pointer:
        for raw_part in pointer.lstrip("/").split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            current = current[part]
    if not isinstance(current, dict):
        raise ContractError(f"Schema reference does not resolve to an object: #{pointer}")
    return current


def _validate(
    value: Any,
    schema: dict[str, Any],
    path: str = "$",
    *,
    root_schema: dict[str, Any] | None = None,
    schema_directory: Path = SCHEMA_DIR,
) -> None:
    if root_schema is None:
        root_schema = schema

    if "$ref" in schema:
        reference = schema["$ref"]
        filename, _, pointer = reference.partition("#")
        if filename:
            referenced_path = schema_directory / filename
            referenced_root = json.loads(referenced_path.read_text(encoding="utf-8"))
            _validate(
                value,
                _resolve_pointer(referenced_root, pointer),
                path,
                root_schema=referenced_root,
                schema_directory=referenced_path.parent,
            )
        else:
            _validate(
                value,
                _resolve_pointer(root_schema, pointer),
                path,
                root_schema=root_schema,
                schema_directory=schema_directory,
            )
        return
    if "const" in schema and value != schema["const"]:
        raise ContractError(f"{path}: expected constant {schema['const']!r}, got {value!r}")

    if "enum" in schema and value not in schema["enum"]:
        raise ContractError(f"{path}: {value!r} is not one of {schema['enum']!r}")

    expected = schema.get("type")
    if expected is not None and not _is_type(value, expected):
        raise ContractError(f"{path}: expected {expected}, got {_typename(value)}")

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                raise ContractError(f"{path}: missing required property {key!r}")
        additional = schema.get("additionalProperties")
        if additional is False:
            extras = set(value) - set(properties)
            if extras:
                raise ContractError(f"{path}: unexpected properties {sorted(extras)!r}")
        for key, child in value.items():
            if key in properties:
                _validate(
                    child,
                    properties[key],
                    f"{path}.{key}",
                    root_schema=root_schema,
                    schema_directory=schema_directory,
                )
            elif isinstance(additional, dict):
                _validate(
                    child,
                    additional,
                    f"{path}.{key}",
                    root_schema=root_schema,
                    schema_directory=schema_directory,
                )

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ContractError(f"{path}: expected at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise ContractError(f"{path}: expected at most {schema['maxItems']} items")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                _validate(
                    item,
                    item_schema,
                    f"{path}[{index}]",
                    root_schema=root_schema,
                    schema_directory=schema_directory,
                )

    if isinstance(value, str) and "minLength" in schema:
        if len(value) < schema["minLength"]:
            raise ContractError(f"{path}: string is shorter than {schema['minLength']}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ContractError(f"{path}: {value} is below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise ContractError(f"{path}: {value} is above maximum {schema['maximum']}")


def validate_artifact(artifact: dict[str, Any], expected_contract: str | None = None) -> None:
    contract = artifact.get("contract")
    if not isinstance(contract, str):
        raise ContractError("$: missing string property 'contract'")
    if expected_contract is not None and contract != expected_contract:
        raise ContractError(f"$: expected contract {expected_contract!r}, got {contract!r}")
    try:
        schema_file = CONTRACT_SCHEMAS[contract]
    except KeyError as exc:
        raise ContractError(f"$: unknown contract {contract!r}") from exc
    schema = json.loads((SCHEMA_DIR / schema_file).read_text(encoding="utf-8"))
    _validate(artifact, schema, root_schema=schema)
    _validate_selection_semantics(artifact)


def validate_case_list_input(document: Any, *, single_case: bool = False) -> None:
    """Validate the table-independent framework input and identity invariants."""

    schema = json.loads(CASE_LIST_SCHEMA.read_text(encoding="utf-8"))
    _validate(document, schema, root_schema=schema, schema_directory=SCHEMA_DIR)
    if not isinstance(document, dict):
        raise ContractError("$: CaseList input must be an object")
    dx_items = document["DxItem_list"]
    if len(dx_items) != len(set(dx_items)):
        raise ContractError("$.DxItem_list: duplicate diagnostic item names")
    cases = document["case_list"]
    if single_case and len(cases) != 1:
        raise ContractError(f"$.case_list: expected exactly one case, got {len(cases)}")
    case_ids = [case["case_id"] for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ContractError("$.case_list: duplicate case_id values")
    for case_index, case in enumerate(cases):
        stain_ids: set[str] = set()
        for block_index, block in enumerate(case["tissue_blocks"]):
            for stain in block["stains"]:
                stain_id = stain["stain_id"]
                if stain_id in stain_ids:
                    raise ContractError(
                        f"$.case_list[{case_index}].tissue_blocks[{block_index}]: "
                        f"duplicate stain_id {stain_id!r}"
                    )
                stain_ids.add(stain_id)


def _validate_selection_semantics(artifact: dict[str, Any]) -> None:
    """Validate cross-field ROI event invariants not expressed by the demo validator."""

    payload = artifact.get("payload", {})
    cases = payload.get("case_list")
    if not isinstance(cases, list):
        return

    for case in cases:
        for block in case.get("tissue_blocks", []):
            for stain in block.get("stains", []):
                for roi in stain.get("roi_list", []):
                    events = roi.get("selection_history", [])
                    for event in events:
                        status = event["status"]
                        if event["selected"] is not (status == "selected"):
                            raise ContractError(
                                f"ROI {roi.get('roi_id')}: event selected/status mismatch"
                            )
                        if event["stage"] == "clee":
                            expected_action = (
                                "inference_skipped"
                                if status == "skipped"
                                else "evidence_evaluated"
                            )
                            if event["action"] != expected_action:
                                raise ContractError(
                                    f"ROI {roi.get('roi_id')}: CLEE status {status!r} "
                                    f"requires action {expected_action!r}"
                                )

                    visual_events = [
                        event
                        for event in events
                        if event["stage"] == "visual_attributes_matching_filter"
                    ]
                    if artifact["contract"] in {
                        "H.MatchedROIs",
                        "I.CLEESelectedROIs",
                    }:
                        if not visual_events:
                            raise ContractError(
                                f"ROI {roi.get('roi_id')}: H/I requires a visual "
                                "attribute matching event"
                            )
                        if any(
                            event["action"] != "legality_evaluated"
                            for event in visual_events
                        ):
                            raise ContractError(
                                f"ROI {roi.get('roi_id')}: visual filter events must "
                                "use action 'legality_evaluated'"
                            )

                    if artifact["contract"] == "I.CLEESelectedROIs":
                        clee_events = [
                            event for event in events if event["stage"] == "clee"
                        ]
                        if not clee_events:
                            raise ContractError(
                                f"ROI {roi.get('roi_id')}: I requires a CLEE event"
                            )
                        evaluated = any(
                            event["action"] == "evidence_evaluated"
                            for event in clee_events
                        )
                        if evaluated != ("pseudo_DxPair" in roi):
                            raise ContractError(
                                f"ROI {roi.get('roi_id')}: pseudo_DxPair must exist "
                                "exactly when CLEE evaluated the ROI"
                            )
                        for event in clee_events:
                            upstream_selected = any(
                                visual_event.get("dx_pair_id")
                                == event.get("dx_pair_id")
                                and visual_event["status"] == "selected"
                                for visual_event in visual_events
                            )
                            if (
                                event["action"] == "evidence_evaluated"
                                and not upstream_selected
                            ):
                                raise ContractError(
                                    f"ROI {roi.get('roi_id')}: CLEE evaluation requires "
                                    "an H selected event for the same dx_pair_id"
                                )
                            if (
                                event["reason"]
                                == "upstream_visual_filter_rejected"
                                and upstream_selected
                            ):
                                raise ContractError(
                                    f"ROI {roi.get('roi_id')}: CLEE cannot claim an "
                                    "upstream rejection when H selected the ROI"
                                )


def load_inputs(paths: Iterable[str | Path], required_contracts: Iterable[str]) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for raw_path in paths:
        path = resolve_run_path(raw_path)
        artifact = json.loads(path.read_text(encoding="utf-8"))
        validate_artifact(artifact)
        contract = artifact["contract"]
        if contract in artifacts:
            raise ContractError(f"Duplicate input contract {contract!r}")
        artifacts[contract] = artifact

    required = set(required_contracts)
    missing = required - set(artifacts)
    unexpected = set(artifacts) - required
    if missing or unexpected:
        raise ContractError(
            f"Input contract mismatch; missing={sorted(missing)}, unexpected={sorted(unexpected)}"
        )
    return artifacts


def load_case_list_input(path: str | Path, *, single_case: bool = False) -> dict[str, Any]:
    resolved = resolve_run_path(path)
    document = json.loads(resolved.read_text(encoding="utf-8"))
    validate_case_list_input(document, single_case=single_case)
    return document


def write_case_list_input(
    document: dict[str, Any],
    output: str | Path,
    *,
    single_case: bool = True,
) -> None:
    """Write a canonical CaseList below run/.

    Component handoffs use the single-case default. The upstream B-to-CaseList
    adapter explicitly opts into a multi-case batch for pipeline fan-out.
    """

    validate_case_list_input(document, single_case=single_case)
    path = resolve_run_path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = resolve_component_config_path(path)
    return json.loads(config_path.read_text(encoding="utf-8"))


def write_artifact(artifact: dict[str, Any], output: str | Path, expected_contract: str) -> None:
    validate_artifact(artifact, expected_contract)
    path = resolve_run_path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {expected_contract} -> {path}")


def cli_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        help="Input artifact path; repeat for a component with multiple inputs",
    )
    parser.add_argument("--output", required=True, help="Output artifact path")
    parser.add_argument("--config", required=True, help="Component config JSON path")
    return parser
