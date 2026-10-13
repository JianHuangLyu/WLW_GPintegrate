"""Person D visual attribute matching filter.

Compares the PLIP/CONCH-consistent labels of one ROI with one G
``diagnosticCriteria`` and decides selected, rejected, or skipped.

An attribute is evaluated only when both models agree, its labels map to
criteria options, and at least one mapped condition is informative.  A
Must_False option or a missed Must_True option rejects the ROI.  A Must
condition is unverified when its attribute was not evaluated (Must_True) or
when it sits on a criteria option no vocabulary label can reach (Must_True or
Must_False): it never counts as passed, so the ROI is skipped (or rejected
under the ``reject`` policy) instead of being scored.  Otherwise the mean
condition weight must reach the configured threshold.  Too few evaluated
attributes is insufficient evidence and yields skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


CONDITIONS = (
    "Must_True",
    "Must_False",
    "High_Possibly_True",
    "Low_Possibly_True",
    "Negligible",
    "Not_Mentioned",
)
INFORMATIVE_CONDITIONS = frozenset(
    {"Must_True", "Must_False", "High_Possibly_True", "Low_Possibly_True"}
)
SUPPORTING_CONDITIONS = frozenset({"Must_True", "High_Possibly_True"})
UNVERIFIED_MUST_TRUE_POLICIES = ("skip", "reject")


@dataclass(frozen=True)
class MatchingSettings:
    condition_weights: dict[str, float]
    score_threshold: float
    min_evaluated_attributes: int
    unverified_must_true: str

    @classmethod
    def from_config(cls, raw: Mapping[str, Any]) -> "MatchingSettings":
        try:
            weights = {str(key): float(value) for key, value in raw["condition_weights"].items()}
            settings = cls(
                condition_weights=weights,
                score_threshold=float(raw["score_threshold"]),
                min_evaluated_attributes=int(raw["min_evaluated_attributes"]),
                unverified_must_true=str(raw["unverified_must_true"]),
            )
        except KeyError as exc:
            raise ValueError(f"Person D matching config is missing {exc.args[0]!r}") from exc
        if set(weights) != INFORMATIVE_CONDITIONS:
            raise ValueError(
                "condition_weights must define exactly "
                f"{sorted(INFORMATIVE_CONDITIONS)}"
            )
        if any(not -1.0 <= value <= 1.0 for value in weights.values()):
            raise ValueError("condition_weights must stay within [-1, 1]")
        if not -1.0 <= settings.score_threshold <= 1.0:
            raise ValueError("score_threshold must stay within [-1, 1]")
        if settings.min_evaluated_attributes < 1:
            raise ValueError("min_evaluated_attributes must be at least 1")
        if settings.unverified_must_true not in UNVERIFIED_MUST_TRUE_POLICIES:
            raise ValueError(
                f"unverified_must_true must be one of {UNVERIFIED_MUST_TRUE_POLICIES}"
            )
        return settings


@dataclass(frozen=True)
class LabelMap:
    """Extraction-label to criteria-option aliases for one criteria version."""

    criteria_version: str
    global_aliases: dict[str, list[str]]
    attribute_aliases: dict[str, dict[str, list[str]]]

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> "LabelMap":
        return cls(
            criteria_version=str(document["criteria_version"]),
            global_aliases={
                str(label): list(options)
                for label, options in document["global_aliases"].items()
            },
            attribute_aliases={
                str(key): {str(label): list(options) for label, options in table.items()}
                for key, table in document["attribute_aliases"].items()
            },
        )

    def resolve(self, attribute_key: str, label: str, options: list[str]) -> list[str]:
        """Return the criteria options for one label: alias, exact, then case-insensitive."""

        for table in (self.attribute_aliases.get(attribute_key, {}), self.global_aliases):
            if label in table:
                return [option for option in table[label] if option in options]
        if label in options:
            return [label]
        return [option for option in options if option.lower() == label.lower()]


def evaluate_attribute(
    labels: list[str],
    attr_spec: Mapping[str, Any],
    attribute_key: str,
    label_map: LabelMap,
) -> dict[str, Any]:
    result: dict[str, Any] = {"labels": list(labels)}
    if not labels:
        result["status"] = "models_disagree"
        return result

    options: list[str] = []
    conditions: list[str] = []
    unmapped: list[str] = []
    ambiguous: list[str] = []
    for label in labels:
        mapped = label_map.resolve(attribute_key, label, list(attr_spec["options"]))
        if not mapped:
            unmapped.append(label)
            continue
        label_conditions = {
            attr_spec["conditions"].get(option, "Not_Mentioned") for option in mapped
        }
        if len(label_conditions) > 1:
            ambiguous.append(label)
            continue
        options.extend(mapped)
        conditions.append(label_conditions.pop())

    result.update(options=options, conditions=conditions)
    if unmapped:
        result["unmapped_labels"] = unmapped
    if ambiguous:
        result["ambiguous_labels"] = ambiguous
    if not conditions:
        result["status"] = "ambiguous_label" if ambiguous else "unmapped_label"
    elif not INFORMATIVE_CONDITIONS & set(conditions):
        result["status"] = "uninformative"
    else:
        result["status"] = "evaluated"
    return result


def match_query(
    extracted: Mapping[str, Mapping[str, list[str]]],
    criteria: Mapping[str, Any],
    label_map: LabelMap,
    settings: MatchingSettings,
    vocabulary: Mapping[str, Mapping[str, list[str]]],
) -> dict[str, Any]:
    """Match one ROI's consistent labels against one diagnosticCriteria.

    ``vocabulary`` is the extraction vocabulary (category -> attribute -> labels); it decides
    which criteria options the backend can reach at all.
    """

    if criteria["version"] != label_map.criteria_version:
        raise ValueError(
            f"diagnosticCriteria version {criteria['version']!r} does not match "
            f"label map criteria_version {label_map.criteria_version!r}"
        )

    attributes: dict[str, dict[str, Any]] = {}
    for category, category_spec in criteria["visualAttrs"].items():
        for attribute, attr_spec in category_spec.items():
            key = f"{category}.{attribute}"
            labels = extracted.get(category, {}).get(attribute)
            if labels is None:
                result: dict[str, Any] = {"status": "not_extracted"}
            else:
                result = evaluate_attribute(labels, attr_spec, key, label_map)
            result["requires_must_true"] = "Must_True" in attr_spec["conditions"].values()
            options = list(attr_spec["options"])
            reachable = {
                option
                for label in vocabulary.get(category, {}).get(attribute, [])
                for option in label_map.resolve(key, label, options)
            }
            unreachable_must = {
                condition: [
                    option
                    for option in options
                    if attr_spec["conditions"].get(option) == condition and option not in reachable
                ]
                for condition in ("Must_True", "Must_False")
            }
            unreachable_must = {condition: found for condition, found in unreachable_must.items() if found}
            if unreachable_must:
                result["unreachable_must"] = unreachable_must
            attributes[key] = result

    evaluated = {key: result for key, result in attributes.items() if result["status"] == "evaluated"}
    must_false_failed = sorted(
        key for key, result in evaluated.items() if "Must_False" in result["conditions"]
    )
    # A miss only counts when every Must_True option of the attribute could have been predicted.
    must_true_failed = sorted(
        key
        for key, result in evaluated.items()
        if result["requires_must_true"]
        and "Must_True" not in result["conditions"]
        and "Must_True" not in result.get("unreachable_must", {})
    )
    must_true_unverified = sorted(
        key
        for key, result in attributes.items()
        if result["requires_must_true"] and key not in evaluated
    )
    must_unverifiable = sorted(key for key, result in attributes.items() if "unreachable_must" in result)

    attribute_scores = []
    for result in evaluated.values():
        weights = [
            settings.condition_weights[condition]
            for condition in result["conditions"]
            if condition in settings.condition_weights
        ]
        attribute_scores.append(sum(weights) / len(weights))
    score = round(sum(attribute_scores) / len(attribute_scores), 6) if attribute_scores else 0.0

    unverified = sorted(set(must_true_unverified) | set(must_unverifiable))
    reject_unverified = settings.unverified_must_true == "reject" and bool(unverified)
    must_false_passed = not must_false_failed and not any(
        "Must_False" in attributes[key]["unreachable_must"] for key in must_unverifiable
    )
    must_true_passed = (
        not must_true_failed
        and not must_true_unverified
        and not any("Must_True" in attributes[key]["unreachable_must"] for key in must_unverifiable)
    )
    failed = sorted(
        set(must_false_failed)
        | set(must_true_failed)
        | (set(unverified) if reject_unverified else set())
    )
    matched = sorted(
        key
        for key, result in evaluated.items()
        if SUPPORTING_CONDITIONS & set(result["conditions"])
    )

    # An unverified Must condition could still change the outcome, so it is
    # checked before the threshold and never ends as selected.
    if len(evaluated) < settings.min_evaluated_attributes:
        status, reason = "skipped", "insufficient_visual_evidence"
    elif must_false_failed or must_true_failed or reject_unverified:
        status, reason = "rejected", "must_condition_failed"
    elif unverified:
        status, reason = "skipped", "insufficient_visual_evidence"
    elif score < settings.score_threshold:
        status, reason = "rejected", "score_below_threshold"
    else:
        status, reason = "selected", "visual_attributes_match"

    return {
        "status": status,
        "reason": reason,
        "score": score,
        "must_true_passed": must_true_passed,
        "must_false_passed": must_false_passed,
        "matched_attributes": matched,
        "failed_attributes": failed,
        "evaluated_count": len(evaluated),
        "must_true_unverified": must_true_unverified,
        "must_unverifiable": must_unverifiable,
        "attributes": attributes,
    }
