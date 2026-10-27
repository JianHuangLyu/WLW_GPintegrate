"""Person B retrieval: A.Literature + D.DxPairs -> F.Chunks.

``mode: example`` keeps the contract-only stub (an empty chunk list) used by the shared
example pipeline.  ``mode: dense`` is the real retriever: embedding search over a prebuilt,
digest-verified knowledge base.  There is no silent rebuild or fallback; a missing or
mismatching index, model or corpus is an error.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from components.person_b import dense
from components.person_b.assets import logical_path, model_identity, resolve_asset
from contracts.metadata import dx_items, single_case
from contracts.runtime import cli_parser, load_config, load_inputs, write_artifact


# --- example stub (shared contract example pipeline) -------------------------------


def _producer(config: dict[str, Any]) -> str:
    producer = config.get("component_version")
    if config.get("mode") != "example" or not isinstance(producer, str) or not producer:
        raise ValueError("Person B example requires an example config with component_version")
    return producer


def build_example_artifact(
    literature: dict[str, Any], d_artifact: dict[str, Any], producer: str
) -> dict[str, Any]:
    """Return a valid empty retrieval result without ranking any text."""

    case_id = single_case(d_artifact)["case_id"]
    corpus_id = literature["payload"]["corpus"]["corpus_id"]
    return {
        "contract": "F.Chunks",
        "schema_version": "2.0",
        "artifact_id": f"F-example-{case_id}",
        "case_id": case_id,
        "producer": producer,
        "payload": {
            "corpus_id": corpus_id,
            "knowledge_base": {
                "knowledge_base_id": "example-not-built",
                "archive_path": "example://not-created",
                "archive_sha256": "not-applicable",
                "corpus_sha256": literature["payload"]["corpus"]["sha256"],
                "embedding_model_path": "example://not-configured",
                "embedding_model_sha256": "not-applicable",
                "document_count": 1,
                "max_tokens": 1,
                "query_max_tokens": 1,
                "retrieval_mode": "sparse",
                "top_k": 1,
                "candidate_k": 1,
                "hybrid_weights": {"dense": 0.0, "sparse": 1.0},
            },
            "chunks": [],
        },
    }


# --- dense retrieval ----------------------------------------------------------------


def _section_candidates(literature: dict[str, Any]) -> list[dict[str, Any]]:
    """Every retrievable section, in corpus order.

    A source-level literal "None" stays in A but is not evidence, so it is not indexed.
    """

    candidates = []
    for item in literature["payload"]["literature_list"]:
        for section in item["sections"]:
            if not section["text"].strip() or section["text"].strip().casefold() == "none":
                continue
            candidates.append(
                {
                    "literature_id": item["literature_id"],
                    "section_id": section["section_id"],
                    "source_idx": item["source_idx"],
                    "section_idx": section["section_idx"],
                    "title_list": item["title_list"],
                    "literature_title": item["title"],
                    "section_title": section["title"],
                    "source_href": item["href"],
                    "text": section["text"],
                }
            )
    return candidates


def _retrieval_settings(config: dict[str, Any]) -> dict[str, Any]:
    retrieval = config["retrieval"]
    top_k = int(retrieval["top_k"])
    candidate_k = int(retrieval.get("candidate_k", top_k))
    min_chunks = int(retrieval.get("min_chunks", 3))
    if candidate_k < top_k:
        raise ValueError(f"retrieval.candidate_k ({candidate_k}) must be >= top_k ({top_k})")
    if top_k < min_chunks:
        raise ValueError(f"retrieval.top_k ({top_k}) must be >= retrieval.min_chunks ({min_chunks})")
    return {
        "dx_items": set(retrieval.get("dx_items", ["Histologic_Type"])),
        "queries": retrieval["queries"],
        "top_k": top_k,
        "candidate_k": candidate_k,
        "min_chunks": min_chunks,
    }


def build_dense_artifact(
    literature: dict[str, Any],
    d_artifact: dict[str, Any],
    config: dict[str, Any],
    *,
    knowledge_base_dir: Path,
    model_dir: Path | None,
    model_sha256: str,
    model_logical_path: str,
    embedder: Any | None = None,
) -> dict[str, Any]:
    case_id = single_case(d_artifact)["case_id"]
    settings = _retrieval_settings(config)
    embedding_config = config["embedding"]
    query_max_tokens = int(embedding_config.get("query_max_tokens", 128))
    candidates = _section_candidates(literature)
    if not candidates:
        raise ValueError("A.Literature has no retrievable sections")

    embedder = embedder or dense.make_embedder(embedding_config, model_dir)
    matrix, sections, manifest = dense.load_knowledge_base(
        knowledge_base_dir,
        literature,
        candidates,
        knowledge_base_id=config["knowledge_base"]["knowledge_base_id"],
        model_sha256=model_sha256,
        max_tokens=int(embedder.max_tokens),
    )

    chunks: list[dict[str, Any]] = []
    for dx_item, pair in dx_items(d_artifact["payload"]).items():
        if dx_item not in settings["dx_items"]:
            continue
        cls = pair["DxResultCls"]
        query = settings["queries"].get(cls) if isinstance(cls, str) else None
        if query is None:
            # e.g. OTHER / AMBIGUOUS: 甲 marks these unmapped and does not read chunks.
            print(
                f"{pair['dx_pair_id']}: no retrieval query for {dx_item}={cls!r}; "
                "no chunks emitted",
                file=sys.stderr,
            )
            continue
        hits = dense.search(
            matrix, dense.embed_query(embedder, query, query_max_tokens), settings["candidate_k"]
        )
        if len(hits) < settings["min_chunks"]:
            raise ValueError(
                f"{pair['dx_pair_id']}: only {len(hits)} retrievable sections, "
                f"{settings['min_chunks']} required"
            )
        for rank, (row, cosine) in enumerate(hits[: settings["top_k"]], start=1):
            candidate = candidates[row]
            chunks.append(
                {
                    "chunk_id": f"{case_id}-chunk-{len(chunks) + 1:03d}",
                    "dx_pair_id": pair["dx_pair_id"],
                    "literature_id": candidate["literature_id"],
                    "section_id": candidate["section_id"],
                    "source_idx": candidate["source_idx"],
                    "section_idx": candidate["section_idx"],
                    "title_list": candidate["title_list"],
                    "literature_title": candidate["literature_title"],
                    "section_title": candidate["section_title"],
                    "source_href": candidate["source_href"],
                    "text": candidate["text"],
                    "indexed_token_count": sections[row]["indexed_token_count"],
                    "retrieval_rank": rank,
                    "dense_score": round(cosine, 6),
                    "dense_rank": rank,
                    "sparse_score": None,
                    "sparse_rank": None,
                    # F.relevance_score is 0..1; for pure dense retrieval it is the clipped cosine.
                    "relevance_score": round(min(1.0, max(0.0, cosine)), 3),
                }
            )

    return {
        "contract": "F.Chunks",
        "schema_version": "2.0",
        "artifact_id": f"F-{case_id}",
        "case_id": case_id,
        "producer": config["component_version"],
        "payload": {
            "corpus_id": literature["payload"]["corpus"]["corpus_id"],
            "knowledge_base": {
                "knowledge_base_id": manifest["knowledge_base_id"],
                "archive_path": logical_path(knowledge_base_dir),
                "archive_sha256": manifest["archive_sha256"],
                "corpus_sha256": manifest["corpus"]["sha256"],
                "embedding_model_path": model_logical_path,
                "embedding_model_sha256": model_sha256,
                "document_count": len(candidates),
                "max_tokens": int(embedder.max_tokens),
                "query_max_tokens": query_max_tokens,
                "retrieval_mode": "dense",
                "top_k": settings["top_k"],
                "candidate_k": settings["candidate_k"],
                "hybrid_weights": {"dense": 1.0, "sparse": 0.0},
            },
            "chunks": chunks,
        },
    }


def main() -> None:
    args = cli_parser("乙: retrieve F literature chunks for D diagnostic pairs").parse_args()
    inputs = load_inputs(args.input, ["A.Literature", "D.DxPairs"])
    literature = inputs["A.Literature"]
    d_artifact = inputs["D.DxPairs"]
    config = load_config(args.config)

    mode = config.get("mode")
    if mode == "example":
        artifact = build_example_artifact(literature, d_artifact, _producer(config))
    elif mode == "dense":
        model_dir, model_logical, model_sha256 = model_identity(config["embedding"])
        artifact = build_dense_artifact(
            literature,
            d_artifact,
            config,
            knowledge_base_dir=resolve_asset(config["knowledge_base"]["path"]),
            model_dir=model_dir,
            model_sha256=model_sha256,
            model_logical_path=model_logical,
        )
    else:
        raise ValueError(f"config.mode must be example or dense, got {mode!r}")
    write_artifact(artifact, args.output, "F.Chunks")


if __name__ == "__main__":
    main()
