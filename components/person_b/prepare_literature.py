"""Person B literature preparation: external corpus -> A.Literature.

Without ``--source`` and with ``mode: example`` this keeps the synthetic contract example
used by ``pipeline/run_prepare_literature.py``.  With ``--source`` and ``mode: rag_database``
it wraps a RAG_database folder as a text-only A artifact.

Source format ``rag_database`` v1 (owned and versioned by 乙): a directory with one
``<disease>.json`` per disease::

    {"disease_name": str, "sections": [{"section_type": str, "page_content": str}, ...],
     "images": [...]}      # images are ignored: A is text-only

Files without a ``.json`` extension (empty chapter placeholders) are skipped.  There is no
chapter hierarchy or URL in this source, so each disease becomes a level-3 node with
``title_list=[corpus_title, null, null, disease_name]`` and ``href=null``.  A literal
``"None"`` page_content is kept in A (so A can be compared with the source) and is not
indexed by retrieval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from components.person_b.assets import logical_path
from contracts.runtime import load_config, write_artifact


def _producer(config: dict[str, Any]) -> str:
    producer = config.get("component_version")
    if config.get("mode") != "example" or not isinstance(producer, str) or not producer:
        raise ValueError("Person B example requires an example config with component_version")
    return producer


def build_example_artifact(producer: str) -> dict[str, Any]:
    """Return synthetic content that is unrelated to any research corpus."""

    return {
        "contract": "A.Literature",
        "schema_version": "2.0",
        "artifact_id": "A-example-literature",
        "producer": producer,
        "payload": {
            "corpus": {
                "corpus_id": "example-corpus",
                "title": "Synthetic contract example",
                "source_file": "synthetic-example.txt",
                "source_path": "example://synthetic-example.txt",
                "sha256": "not-applicable-example-content",
                "source_size_bytes": 1,
                "literature_count": 1,
            },
            "literature_list": [
                {
                    "literature_id": "example-literature-001",
                    "source_idx": 0,
                    "level": 1,
                    "title_list": ["Synthetic example", None, None, None],
                    "title": "Synthetic example",
                    "href": None,
                    "sections": [
                        {
                            "section_id": "example-section-001",
                            "section_idx": 0,
                            "title": "Example",
                            "text": "Placeholder text for contract testing only.",
                        }
                    ],
                }
            ],
        },
    }


def _stable_id(prefix: str, *parts: Any) -> str:
    canonical = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return f"{prefix}-{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:16]}"


def build_literature_artifact_from_rag_database(
    source_dir: str | Path, config: dict[str, Any]
) -> dict[str, Any]:
    root = Path(source_dir).resolve()
    # Sort by file name string: Path ordering is case-insensitive on Windows and case-sensitive on
    # Linux, which would give a different A (order, source_idx, corpus digest) on each platform.
    files = sorted(root.glob("*.json"), key=lambda path: path.name)
    if not files:
        raise ValueError(f"No *.json disease files found in {root}")
    corpus_title = config["corpus_title"]

    digest = hashlib.sha256()
    total_bytes = 0
    literature_list = []
    used_names: set[str] = set()
    for source_idx, path in enumerate(files):
        raw = path.read_bytes()
        digest.update(path.name.encode("utf-8") + b"\0" + raw + b"\0")
        total_bytes += len(raw)
        entry = json.loads(raw.decode("utf-8"))
        disease = entry.get("disease_name") if isinstance(entry, dict) else None
        if not isinstance(disease, str) or not disease:
            raise ValueError(f"{path.name} has no disease_name")
        if disease in used_names:
            raise ValueError(f"Duplicate disease_name {disease!r} ({path.name})")
        used_names.add(disease)
        if not isinstance(entry.get("sections"), list):
            raise ValueError(f"{path.name} sections must be an array")

        title_list = [corpus_title, None, None, disease]
        literature_id = _stable_id("lit", 3, title_list, disease, None)
        section_title_counts: dict[str, int] = {}
        sections = []
        for section_idx, section in enumerate(entry["sections"]):
            title, text = section.get("section_type"), section.get("page_content")
            if not isinstance(title, str) or not title or not isinstance(text, str):
                raise ValueError(
                    f"{path.name} section {section_idx} needs string section_type/page_content"
                )
            occurrence = section_title_counts.get(title, 0)
            section_title_counts[title] = occurrence + 1
            sections.append(
                {
                    "section_id": _stable_id("sec", literature_id, title, occurrence),
                    "section_idx": section_idx,
                    "title": title,
                    "text": text,
                }
            )
        literature_list.append(
            {
                "literature_id": literature_id,
                "source_idx": source_idx,
                "level": 3,
                "title_list": title_list,
                "title": disease,
                "href": None,
                "sections": sections,
            }
        )

    return {
        "contract": "A.Literature",
        "schema_version": "2.0",
        "artifact_id": f"A-{config['corpus_id']}",
        "producer": config["component_version"],
        "payload": {
            "corpus": {
                "corpus_id": config["corpus_id"],
                "title": corpus_title,
                "source_file": root.name,
                "source_path": logical_path(root),
                "sha256": digest.hexdigest(),
                "source_size_bytes": total_bytes,
                "literature_count": len(literature_list),
            },
            "literature_list": literature_list,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Person B: create A.Literature")
    parser.add_argument("--output", required=True, help="Output A.Literature artifact")
    parser.add_argument("--config", required=True, help="Component config")
    parser.add_argument(
        "--source",
        help="RAG_database directory (mode rag_database); omit for the synthetic example",
    )
    args = parser.parse_args()
    config = load_config(args.config)
    if args.source is None:
        artifact = build_example_artifact(_producer(config))
    else:
        if config.get("mode") != "rag_database":
            raise ValueError("--source needs a config with mode=rag_database")
        artifact = build_literature_artifact_from_rag_database(args.source, config)
    write_artifact(artifact, args.output, "A.Literature")
    section_count = sum(len(item["sections"]) for item in artifact["payload"]["literature_list"])
    print(
        f"A.Literature: {artifact['payload']['corpus']['literature_count']} nodes, "
        f"{section_count} sections"
    )


if __name__ == "__main__":
    main()
