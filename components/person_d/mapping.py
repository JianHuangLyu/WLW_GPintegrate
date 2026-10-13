"""Vocabulary-to-diagnosticCriteria option mapping.

A vocabulary label reaches a criteria option through the label map (attribute
alias, then global alias), then an exact, then a case-insensitive match
(``LabelMap.resolve``).  A criteria option no vocabulary label reaches is
*unreachable*: the backend can never predict it.  ``mapping_acceptance.json``
records the accepted mapping for one criteria version and classifies every
unreachable option; ``check_acceptance`` compares it with the assets in use.

Standard library only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping

from components.person_d.matching_filter import LabelMap


ACCEPTANCE_PATH = Path(__file__).resolve().parent / "mapping_acceptance.json"
RULES = ("attribute_alias", "global_alias", "exact", "case_insensitive", "unmapped")
MUST_CONDITIONS = ("Must_True", "Must_False")


def map_label(label_map: LabelMap, attribute_key: str, label: str, options: List[str]) -> tuple[List[str], str]:
    """Return the criteria options one vocabulary label reaches and the rule that applied."""

    mapped = label_map.resolve(attribute_key, label, options)
    if not mapped:
        return [], "unmapped"
    if label in label_map.attribute_aliases.get(attribute_key, {}):
        return mapped, "attribute_alias"
    if label in label_map.global_aliases:
        return mapped, "global_alias"
    return mapped, "exact" if mapped == [label] else "case_insensitive"


def reachable_options(
    vocabulary: Mapping[str, Mapping[str, List[str]]],
    label_map: LabelMap,
    category: str,
    attribute: str,
    options: List[str],
) -> set[str]:
    """Return the criteria options at least one vocabulary label of the attribute reaches."""

    key = f"{category}.{attribute}"
    return {
        option
        for label in vocabulary.get(category, {}).get(attribute, [])
        for option in label_map.resolve(key, label, options)
    }


def audit(
    vocabulary: Mapping[str, Mapping[str, List[str]]],
    label_map: LabelMap,
    criteria_options: Mapping[str, List[str]],
) -> Dict[str, Dict[str, Any]]:
    """Return the per-attribute mapping and the unreachable criteria options."""

    result: Dict[str, Dict[str, Any]] = {}
    labels_by_key = {
        f"{category}.{attribute}": list(labels)
        for category, attributes in vocabulary.items()
        for attribute, labels in attributes.items()
    }
    for key, options in criteria_options.items():
        labels = labels_by_key.get(key, [])
        mapping = {}
        for label in labels:
            mapped, rule = map_label(label_map, key, label, list(options))
            mapping[label] = {"options": mapped, "rule": rule}
        reached = {option for entry in mapping.values() for option in entry["options"]}
        result[key] = {
            "prompt_options": labels,
            "criteria_options": list(options),
            "mapping": mapping,
            "unreachable": [option for option in options if option not in reached],
        }
    return result


def summarize(attributes: Mapping[str, Mapping[str, Any]]) -> Dict[str, int]:
    entries = list(attributes.values())
    return {
        "attributes": len(entries),
        "prompt_options": sum(len(entry["prompt_options"]) for entry in entries),
        "criteria_options": sum(len(entry["criteria_options"]) for entry in entries),
        "unmapped_prompt_options": sum(
            1 for entry in entries for mapped in entry["mapping"].values() if not mapped["options"]
        ),
        "multi_mapped_prompt_options": sum(
            1 for entry in entries for mapped in entry["mapping"].values() if len(mapped["options"]) > 1
        ),
        "unreachable_criteria_options": sum(len(entry["unreachable"]) for entry in entries),
    }


def criteria_option_lists(criteria: Mapping[str, Any]) -> Dict[str, List[str]]:
    return {
        f"{category}.{attribute}": list(spec["options"])
        for category, attributes in criteria["visualAttrs"].items()
        for attribute, spec in attributes.items()
    }


def load_acceptance(path: Path = ACCEPTANCE_PATH) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def check_acceptance(
    acceptance: Mapping[str, Any],
    vocabulary: Mapping[str, Mapping[str, List[str]]],
    label_map_document: Mapping[str, Any],
) -> List[str]:
    """Return the differences between the accepted mapping and the assets in use."""

    errors: List[str] = []
    if label_map_document["criteria_version"] != acceptance["criteria_version"]:
        errors.append(
            f"label map criteria_version {label_map_document['criteria_version']!r} is not the accepted "
            f"{acceptance['criteria_version']!r}"
        )
    for name in ("global_aliases", "attribute_aliases"):
        if label_map_document[name] != acceptance["label_map"][name]:
            errors.append(f"label map {name} differ from the accepted mapping")

    accepted = acceptance["attributes"]
    criteria_options = {key: entry["criteria_options"] for key, entry in accepted.items()}
    actual = audit(vocabulary, LabelMap.from_document(label_map_document), criteria_options)
    vocabulary_keys = {
        f"{category}.{attribute}" for category, attributes in vocabulary.items() for attribute in attributes
    }
    for key in sorted(vocabulary_keys - set(accepted)):
        errors.append(f"{key}: vocabulary attribute is not in the accepted mapping")
    for key, entry in accepted.items():
        if actual[key]["prompt_options"] != entry["prompt_options"]:
            errors.append(f"{key}: vocabulary options differ from the accepted mapping")
        if actual[key]["mapping"] != entry["mapping"]:
            errors.append(f"{key}: label-to-option mapping differs from the accepted mapping")
        if actual[key]["unreachable"] != list(entry["unreachable"]):
            errors.append(f"{key}: unreachable criteria options differ from the accepted mapping")
    return errors


MARKDOWN_PATH = Path(__file__).resolve().parent / "MAPPING.md"
RULE_TEXT = {
    "attribute_alias": "attribute alias",
    "global_alias": "global alias",
    "exact": "exact",
    "case_insensitive": "case-insensitive",
    "unmapped": "unmapped",
}


def render_markdown(acceptance: Mapping[str, Any]) -> str:
    """Render ``mapping_acceptance.json`` as the attribute-level mapping document."""

    summary = acceptance["summary"]
    categories = acceptance["unreachable_categories"]
    lines = [
        "# Person D vocabulary to diagnosticCriteria mapping",
        "",
        "Generated from `mapping_acceptance.json` by `python -m components.person_d.mapping --write`; do not",
        "edit by hand. `tests/test_mapping.py` keeps the two files, the mapping rule and the reference",
        "assets in step.",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| diagnosticCriteria version | `{acceptance['criteria_version']}` |",
        f"| Prompt asset (vocabulary) | `{acceptance['prompt_asset']['version']}`, SHA-256 `{acceptance['prompt_asset']['sha256']}` |",
        f"| Label map | `{acceptance['label_map']['version']}`, SHA-256 `{acceptance['label_map']['sha256']}` |",
        f"| Attributes | {summary['attributes']} |",
        f"| Vocabulary options | {summary['prompt_options']} |",
        f"| Criteria options | {summary['criteria_options']} |",
        f"| Unmapped vocabulary options | {summary['unmapped_prompt_options']} |",
        f"| Vocabulary options mapped to several criteria options | {summary['multi_mapped_prompt_options']} |",
        f"| Unreachable criteria options | {summary['unreachable_criteria_options']} |",
        "",
        "## Rules",
        "",
        "1. A vocabulary label reaches criteria options through, in order: the label map attribute alias,",
        "   the label map global alias, an exact match, a case-insensitive match (`LabelMap.resolve`).",
        "2. An **unmapped** vocabulary label is dropped. When it was the only agreed label, the attribute is",
        "   not evaluated (`unmapped_label`).",
        "3. A vocabulary label **mapped to several** criteria options counts once when those options carry",
        "   the same condition in the query's criteria; when their conditions differ the label is ambiguous",
        "   and dropped (`ambiguous_label`).",
        "4. An **unreachable** criteria option is one no vocabulary label reaches, so the backend can never",
        "   predict it. In matching:",
        "   - a `Must_True` or `Must_False` condition on an unreachable option cannot be verified. It never",
        "     counts as passed: the query is `skipped` (`insufficient_visual_evidence`) under",
        "     `unverified_must_true: skip`, or `rejected` (`must_condition_failed`) under `reject`, and is",
        "     never `selected`. A verified failure on another attribute still rejects first;",
        "   - a miss on an attribute whose `Must_True` option is unreachable is unverified, not failed;",
        "   - any other condition on an unreachable option simply never contributes to the score.",
        "",
        "## Unreachable criteria options by category",
        "",
        "| Category | Options | Meaning |",
        "|---|---:|---|",
    ]
    for name, count in summary["unreachable_by_category"].items():
        lines.append(f"| `{name}` | {count} | {categories[name]} |")

    lines += ["", "| Attribute | Criteria option | Category | Note |", "|---|---|---|---|"]
    for key, entry in acceptance["attributes"].items():
        for option, info in entry["unreachable"].items():
            lines.append(f"| `{key}` | {option} | `{info['category']}` | {info.get('note', '')} |")

    lines += [
        "",
        "## Attribute-level mapping",
        "",
        "Each row is one vocabulary label, the criteria option or options it reaches, and the rule that",
        "applied.",
    ]
    for key, entry in acceptance["attributes"].items():
        lines += [
            "",
            f"### {key}",
            "",
            f"Criteria options: {', '.join(entry['criteria_options'])}",
            "",
            "| Vocabulary label | Criteria option | Rule |",
            "|---|---|---|",
        ]
        for label, mapped in entry["mapping"].items():
            target = ", ".join(mapped["options"]) if mapped["options"] else "none"
            lines.append(f"| {label} | {target} | {RULE_TEXT[mapped['rule']]} |")
        for label, note in entry.get("prompt_option_notes", {}).items():
            lines += ["", f"`{label}`: {note}"]
        if entry["unreachable"]:
            lines += ["", f"Unreachable: {', '.join(entry['unreachable'])}"]
    return "\n".join(lines) + "\n"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="丁: render the vocabulary to diagnosticCriteria mapping")
    parser.add_argument("--write", action="store_true", help="Write MAPPING.md next to this module")
    args = parser.parse_args()
    text = render_markdown(load_acceptance())
    if args.write:
        MARKDOWN_PATH.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {MARKDOWN_PATH}")
    else:
        import sys

        sys.stdout.buffer.write(text.encode("utf-8"))


if __name__ == "__main__":
    main()
