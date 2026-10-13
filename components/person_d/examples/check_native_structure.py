"""Check a native-mode H against H_matches.native.structure.json.

Events listed with ``status`` must match exactly; events listed with
``status_in``/``reason_in`` must use one of the allowed values.  For every event
that went through matching, the score is recomputed from the per-attribute
decisions in visualAttrs_info.matching and must agree within
score_rule.score_tolerance, and the status/reason must follow score_rule.  Exit
code 0 means the H matches.

    python components/person_d/examples/check_native_structure.py \
      components/person_d/examples/H_matches.native.structure.json \
      ../run/output/person_d/examples/H_matches.native.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from contracts.metadata import iter_rois  # noqa: E402
from contracts.runtime import validate_artifact  # noqa: E402


def expected_outcome(rule: dict, event: dict, matching: dict) -> tuple[float, tuple[str, str]]:
    """Recompute the matching score and the final status/reason of one event."""

    attributes = matching["attributes"].values()
    evaluated = [result for result in attributes if result["status"] == "evaluated"]
    attribute_scores = []
    for result in evaluated:
        weights = [
            rule["condition_weights"][condition]
            for condition in result["conditions"]
            if condition in rule["condition_weights"]
        ]
        attribute_scores.append(sum(weights) / len(weights))
    score = sum(attribute_scores) / len(attribute_scores) if attribute_scores else 0.0

    must_false_failed = any("Must_False" in result["conditions"] for result in evaluated)
    must_true_failed = any(
        result["requires_must_true"]
        and "Must_True" not in result["conditions"]
        and "Must_True" not in result.get("unreachable_must", {})
        for result in evaluated
    )
    unverified = any(
        (result["requires_must_true"] and result["status"] != "evaluated") or "unreachable_must" in result
        for result in attributes
    )
    reject_unverified = rule["unverified_must_true"] == "reject" and unverified

    if len(evaluated) < rule["min_evaluated_attributes"]:
        outcome = ("skipped", "insufficient_visual_evidence")
    elif must_false_failed or must_true_failed or reject_unverified:
        outcome = ("rejected", "must_condition_failed")
    elif unverified:
        outcome = ("skipped", "insufficient_visual_evidence")
    elif event.get("score", round(score, 6)) < rule["score_threshold"]:
        outcome = ("rejected", "score_below_threshold")
    else:
        outcome = ("selected", "visual_attributes_match")
    return score, outcome


def check(structure: dict, artifact: dict) -> list[str]:
    validate_artifact(artifact, "H.MatchedROIs")
    errors = []
    for key in ("case_id", "producer"):
        if artifact[key] != structure[key]:
            errors.append(f"{key}: expected {structure[key]!r}, got {artifact[key]!r}")
    loaded = artifact["payload"]["reference_versions"]["visual_attribute_extraction"]["models_loaded"]
    if loaded is not structure["models_loaded"]:
        errors.append(f"models_loaded: expected {structure['models_loaded']}, got {loaded}")

    rois = list(iter_rois(artifact["payload"]))
    roi_ids = [roi["roi_id"] for _, roi in rois]
    if roi_ids != structure["roi_ids"]:
        errors.append(f"roi_ids: expected {structure['roi_ids']}, got {roi_ids}")

    events = [
        (roi, event)
        for _, roi in rois
        for event in roi["selection_history"]
        if event["stage"] == "visual_attributes_matching_filter"
    ]
    if len(events) != len(structure["events"]):
        errors.append(f"event count: expected {len(structure['events'])}, got {len(events)}")
    rule = structure["score_rule"]
    for index, ((roi, event), expected) in enumerate(zip(events, structure["events"])):
        roi_id = roi["roi_id"]
        got = (roi_id, event.get("dx_pair_id"), event.get("query_id"))
        want = (expected["roi_id"], expected["dx_pair_id"], expected["query_id"])
        if got != want:
            errors.append(f"event {index}: linkage expected {want}, got {got}")
        if "status" in expected:
            if (event["status"], event["reason"]) != (expected["status"], expected["reason"]):
                errors.append(
                    f"event {index}: expected {expected['status']}/{expected['reason']}, "
                    f"got {event['status']}/{event['reason']}"
                )
        elif event["status"] not in expected["status_in"] or event["reason"] not in expected["reason_in"]:
            errors.append(f"event {index}: {event['status']}/{event['reason']} is not allowed")
        matching = ((roi.get("visualAttrs_info") or {}).get("matching") or {}).get(event.get("query_id"))
        if matching is not None:
            score, outcome = expected_outcome(rule, event, matching)
            if "score" in event and abs(score - event["score"]) > rule["score_tolerance"]:
                errors.append(f"event {index}: score {event['score']} differs from recomputed {score}")
            if (event["status"], event["reason"]) != outcome:
                errors.append(
                    f"event {index}: expected {outcome[0]}/{outcome[1]} from score_rule, "
                    f"got {event['status']}/{event['reason']}"
                )
    return errors


def main() -> None:
    structure_path, artifact_path = sys.argv[1:3]
    structure = json.loads(Path(structure_path).read_text(encoding="utf-8"))
    artifact = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
    errors = check(structure, artifact)
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        sys.exit(1)
    print("H matches native structure")


if __name__ == "__main__":
    main()
