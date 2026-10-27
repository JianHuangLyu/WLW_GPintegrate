"""乙: build the versioned dense knowledge base (A.Literature -> index directory).

The index location comes from the same config the retriever uses
(``knowledge_base.path`` below ``reference/person_b/``), so builder and retriever cannot
disagree about the model or the location.  An existing index is never overwritten
unless ``--overwrite`` is given: a knowledge base version is immutable.
"""

from __future__ import annotations

import argparse
import shutil

from components.person_b import dense
from components.person_b.assets import logical_path, model_identity, resolve_asset
from components.person_b.knowledge_retrieval import _section_candidates
from contracts.runtime import load_config, load_inputs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="乙: build an embedding index of A.Literature sections"
    )
    parser.add_argument("--input", required=True, help="A.Literature artifact (below run/)")
    parser.add_argument("--config", required=True, help="Dense retrieval config JSON")
    parser.add_argument(
        "--overwrite", action="store_true", help="Replace an existing knowledge base directory"
    )
    args = parser.parse_args()

    literature = load_inputs([args.input], ["A.Literature"])["A.Literature"]
    config = load_config(args.config)
    if config.get("mode") != "dense":
        raise ValueError("build_knowledge_base needs a config with mode=dense")

    target = resolve_asset(config["knowledge_base"]["path"])
    if target.exists() and any(target.iterdir()):
        if not args.overwrite:
            raise FileExistsError(
                f"{logical_path(target)} already exists; use a new knowledge_base.path "
                "for a new version, or pass --overwrite"
            )
        shutil.rmtree(target)

    candidates = _section_candidates(literature)
    if not candidates:
        raise ValueError("A.Literature has no retrievable sections")
    embedding_config = config["embedding"]
    model_dir, model_logical, model_sha256 = model_identity(embedding_config)
    embedder = dense.make_embedder(embedding_config, model_dir)
    manifest = dense.build_knowledge_base(
        target,
        literature,
        candidates,
        embedder,
        knowledge_base_id=config["knowledge_base"]["knowledge_base_id"],
        provider=embedding_config.get("provider", "sentence_transformers"),
        model_logical_path=model_logical,
        model_sha256=model_sha256,
        dtype=embedding_config.get("dtype") or None,
        builder=config["component_version"],
    )
    print(
        f"knowledge base {manifest['knowledge_base_id']}: {len(candidates)} sections x "
        f"{manifest['embedding']['dimension']} dims -> {logical_path(target)}"
    )


if __name__ == "__main__":
    main()
