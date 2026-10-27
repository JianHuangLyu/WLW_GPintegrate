"""Load the externally maintained diagnostic and visual-attribute references."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from components.person_a.asset_integrity import verify_external_asset
from contracts.paths import resolve_person_reference_path, sibling_logical_path


def resolve_reference(configured_path: str | Path) -> Path:
    """Resolve an external Person A asset and enforce reference/person_a/."""

    path = resolve_person_reference_path("person_a", configured_path)
    if not path.is_file():
        raise FileNotFoundError(f"Person A reference file was not found: {path}")
    return path


def load_reference(
    configured_path: str | Path,
    *,
    integrity_mode: str = "enforce",
) -> tuple[Any, dict[str, Any]]:
    path = resolve_reference(configured_path)
    raw = path.read_bytes()
    integrity = verify_external_asset(path, integrity_mode=integrity_mode)
    return json.loads(raw.decode("utf-8")), {
        "source_name": path.name,
        "source_path": sibling_logical_path(path),
        **integrity,
    }


def load_dx_candidates(
    configured_path: str | Path,
    *,
    integrity_mode: str = "enforce",
) -> tuple[dict[str, Any], dict[str, Any]]:
    document, provenance = load_reference(
        configured_path, integrity_mode=integrity_mode
    )
    return document["structured_report"], provenance


def load_histologic_mapping(
    configured_path: str | Path,
    *,
    integrity_mode: str = "enforce",
) -> tuple[dict[str, str], dict[str, Any]]:
    document, provenance = load_reference(
        configured_path, integrity_mode=integrity_mode
    )
    return document["Histologic_Type_mappingTable"], provenance


def load_visual_references(
    candidate_path: str | Path,
    type_level_path: str | Path,
    *,
    integrity_mode: str = "enforce",
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    candidate_document, candidate_provenance = load_reference(
        candidate_path, integrity_mode=integrity_mode
    )
    type_levels_document, type_level_provenance = load_reference(
        type_level_path, integrity_mode=integrity_mode
    )
    candidate = candidate_document["visualAttrs"]
    type_levels = deepcopy(type_levels_document)

    for type_level in type_levels:
        # The filename is canonical for this reference revision.  The embedded
        # version was confirmed to be stale, and Polarity is canonically ordinal.
        type_level["version"] = "1.2.1"
        type_level["visualAttrs"]["Cellular_and_Nuclear"]["Polarity"]["type"] = "ordinal"
        for category, features in type_level["visualAttrs"].items():
            for feature, definition in features.items():
                reference = candidate[category][feature]
                if definition["options"] != reference["options"]:
                    raise ValueError(
                        f"Type-level options differ from candidateReference at {category}.{feature}"
                    )
                if definition["type"] != reference["type"]:
                    raise ValueError(
                        f"Type-level option type differs from candidateReference at {category}.{feature}"
                    )
                if set(definition["conditions"]) != set(definition["options"]):
                    raise ValueError(
                        f"Type-level conditions do not cover every option at {category}.{feature}"
                    )

    return candidate_document, type_levels, {
        "candidate_reference": candidate_provenance,
        "type_level_visual_attrs": type_level_provenance,
    }
