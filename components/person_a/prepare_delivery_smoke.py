"""Prepare a model smoke input using three mounted, fixed ADH reference chunks.

The public fixture remains synthetic. Restricted reference text is written only
under run/, never copied into the repository or Docker image. This is an
execution smoke check, not a retrieval or generalization benchmark.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from components.person_a.asset_integrity import verify_external_asset
from contracts.paths import resolve_person_reference_path, resolve_run_path
from contracts.runtime import validate_artifact


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source = resolve_person_reference_path(
        "person_a", "../reference/person_a/template_ref/chunks_with_attribute_condition.json"
    )
    integrity = verify_external_asset(source)
    entries = json.loads(source.read_text(encoding="utf-8"))
    selected = [entry for entry in entries if entry.get("disease_name") == "Atypical ductal hyperplasia"]
    if len(selected) < 3:
        raise ValueError("Local model smoke requires three fixed ADH reference chunks")
    fixture = Path(__file__).parent / "examples/local_model_delivery/F_chunks.valid.json"
    artifact = json.loads(fixture.read_text(encoding="utf-8"))
    artifact["producer"] = "person-a/local-model-delivery-smoke:0.9.0"
    for chunk, reference in zip(artifact["payload"]["chunks"], selected[:3]):
        chunk["text"] = reference["text"]
        chunk["indexed_token_count"] = max(1, len(reference["text"].split()))
    artifact["payload"]["corpus_id"] = "person-a-fixed-reference-smoke"
    artifact["payload"]["knowledge_base"].update(
        knowledge_base_id="person-a-reference-smoke",
        archive_path="example://smoke-input-not-a-retrieval-archive",
        corpus_sha256=integrity["sha256"],
        embedding_model_path="example://whitespace-tokenizer-no-embedding",
        document_count=len(entries),
        max_tokens=max(chunk["indexed_token_count"] for chunk in artifact["payload"]["chunks"]),
    )
    validate_artifact(artifact, "F.Chunks")
    output = resolve_run_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print("Prepared schema-valid smoke F with three mounted ADH chunks")


if __name__ == "__main__":
    main()
