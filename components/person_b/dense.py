"""Dense (embedding) knowledge base for 乙: section-level index, exact cosine search.

The index is a NumPy matrix of L2-normalised vectors, searched exactly (the same
result as ``faiss.IndexFlatIP``, without the dependency).  Only ``numpy`` is needed
to import this module; ``sentence_transformers``/``torch`` are imported lazily by
the real embedder.

Nothing here downloads or silently rebuilds anything: the embedding model is a local
directory, the index is a prebuilt directory, and both are verified by SHA-256
against the index manifest before a single query is answered.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

KB_SCHEMA_VERSION = "2.0"
EMBEDDINGS_FILE = "embeddings.npy"
SECTIONS_FILE = "sections.json"
MANIFEST_FILE = "manifest.json"
# Files that make up the index archive; the manifest holds their digest, so it is excluded.
ARCHIVE_FILES = (EMBEDDINGS_FILE, SECTIONS_FILE)

# Same text layout as the retrieval experiments (0401_RAG_3), which is also the
# layout 甲's soft prompt was trained on.
DOCUMENT_TEMPLATE = "Disease: {literature_title}\nSection: {section_title}\nContent: {text}"


class KnowledgeBaseError(ValueError):
    """The index, model or corpus is missing or does not match its recorded digest."""


def _numpy() -> Any:
    try:
        import numpy
    except ImportError as exc:
        raise RuntimeError("The dense retrieval backend requires numpy") from exc
    return numpy


def document_text(candidate: dict[str, Any]) -> str:
    return DOCUMENT_TEMPLATE.format(
        literature_title=candidate["literature_title"],
        section_title=candidate["section_title"],
        text=candidate["text"],
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def files_sha256(root: Path, relative_paths: list[str]) -> str:
    """One digest over named files: stable under renames of the directory itself."""

    outer = hashlib.sha256()
    for relative in sorted(relative_paths):
        outer.update(f"{relative}\0{_sha256_file(root / relative)}\n".encode("utf-8"))
    return outer.hexdigest()


def directory_sha256(root: Path) -> str:
    """Digest of every file below ``root`` (relative path + content)."""

    root = Path(root)
    if not root.is_dir():
        raise KnowledgeBaseError(f"Directory not found: {root}")
    files = [
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    ]
    if not files:
        raise KnowledgeBaseError(f"Directory is empty: {root}")
    return files_sha256(root, files)


def _normalise(matrix: Any) -> Any:
    np = _numpy()
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


class HashingEmbedder:
    """Deterministic bag-of-words hashing vectors, for tests only (no semantic quality)."""

    def __init__(self, dimension: int = 256, max_tokens: int = 512) -> None:
        self.dimension = dimension
        self.max_tokens = max_tokens

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    def token_counts(self, texts: list[str]) -> list[int]:
        return [len(self._tokens(text)) for text in texts]

    def encode(self, texts: list[str], max_tokens: int | None = None) -> Any:
        np = _numpy()
        limit = max_tokens or self.max_tokens
        matrix = np.zeros((len(texts), self.dimension), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in self._tokens(text)[:limit]:
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                column = int.from_bytes(digest[:8], "big") % self.dimension
                matrix[row, column] += 1.0 if digest[8] % 2 == 0 else -1.0
        return _normalise(matrix)


class SentenceTransformerEmbedder:
    """Loads a local SentenceTransformer directory; never reaches for the network."""

    def __init__(
        self,
        model_dir: str | Path,
        device: str = "auto",
        max_tokens: int | None = None,
        batch_size: int = 16,
        dtype: str | None = None,
    ) -> None:
        try:
            import torch
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "embedding.provider=sentence_transformers requires torch and "
                "sentence-transformers (see components/person_b/requirements.txt)"
            ) from exc
        model_dir = Path(model_dir)
        if not model_dir.is_dir():
            raise KnowledgeBaseError(f"Embedding model directory not found: {model_dir}")
        kwargs: dict[str, Any] = {}
        if device != "auto":
            kwargs["device"] = device
        if dtype:  # e.g. "float16" to fit a small GPU
            kwargs["model_kwargs"] = {"torch_dtype": getattr(torch, dtype)}
        self._model = SentenceTransformer(str(model_dir), **kwargs)
        if max_tokens:
            self._model.max_seq_length = int(max_tokens)
        self.max_tokens = int(self._model.max_seq_length)
        self._batch_size = batch_size

    def token_counts(self, texts: list[str]) -> list[int]:
        encoded = self._model.tokenizer(
            texts, add_special_tokens=True, truncation=False, padding=False, verbose=False
        )
        return [len(ids) for ids in encoded["input_ids"]]

    def encode(self, texts: list[str], max_tokens: int | None = None) -> Any:
        np = _numpy()
        previous = self._model.max_seq_length
        if max_tokens:
            self._model.max_seq_length = int(max_tokens)
        try:
            vectors = self._model.encode(
                texts,
                batch_size=self._batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        finally:
            self._model.max_seq_length = previous
        return np.asarray(vectors, dtype=np.float32)


def make_embedder(embedding_config: dict[str, Any], model_dir: Path | None) -> Any:
    provider = embedding_config.get("provider", "sentence_transformers")
    if provider == "hashing":
        return HashingEmbedder(
            int(embedding_config.get("dimension", 256)),
            int(embedding_config.get("max_tokens") or 512),
        )
    if provider == "sentence_transformers":
        if model_dir is None:
            raise KnowledgeBaseError("embedding.model_path is required")
        return SentenceTransformerEmbedder(
            model_dir,
            device=embedding_config.get("device", "auto"),
            max_tokens=embedding_config.get("max_tokens") or None,
            batch_size=int(embedding_config.get("batch_size", 16)),
            dtype=embedding_config.get("dtype") or None,
        )
    raise ValueError(
        "embedding.provider must be sentence_transformers or hashing, "
        f"got {provider!r}"
    )


def embed_query(embedder: Any, query: str, query_max_tokens: int) -> Any:
    """Embed one query; a query longer than the configured limit is an error, not a truncation."""

    (count,) = embedder.token_counts([query])
    if count > query_max_tokens:
        raise KnowledgeBaseError(
            f"Query has {count} tokens; embedding.query_max_tokens is {query_max_tokens}"
        )
    return embedder.encode([query], max_tokens=query_max_tokens)[0]


def search(matrix: Any, query_vector: Any, top_k: int) -> list[tuple[int, float]]:
    """Return ``(row, cosine)`` best-first; ties keep corpus order."""

    np = _numpy()
    scores = matrix @ query_vector
    order = np.argsort(-scores, kind="stable")[:top_k]
    return [(int(row), float(scores[row])) for row in order]


def _library_versions() -> dict[str, str]:
    versions = {}
    for package in ("sentence-transformers", "torch", "transformers", "numpy"):
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            continue
    return versions


def build_knowledge_base(
    directory: str | Path,
    literature: dict[str, Any],
    candidates: list[dict[str, Any]],
    embedder: Any,
    *,
    knowledge_base_id: str,
    provider: str,
    model_logical_path: str,
    model_sha256: str,
    dtype: str | None,
    builder: str,
) -> dict[str, Any]:
    """Embed every candidate section and write the index directory; return its manifest."""

    np = _numpy()
    documents = [document_text(item) for item in candidates]
    matrix = embedder.encode(documents)
    counts = embedder.token_counts(documents)
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    np.save(target / EMBEDDINGS_FILE, matrix)
    (target / SECTIONS_FILE).write_text(
        json.dumps(
            [
                {
                    "section_id": item["section_id"],
                    "literature_id": item["literature_id"],
                    "indexed_token_count": min(int(count), embedder.max_tokens),
                }
                for item, count in zip(candidates, counts)
            ],
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    corpus = literature["payload"]["corpus"]
    manifest = {
        "kb_schema_version": KB_SCHEMA_VERSION,
        "knowledge_base_id": knowledge_base_id,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "builder": builder,
        "corpus": {
            "corpus_id": corpus["corpus_id"],
            "sha256": corpus["sha256"],
            "source_file": corpus["source_file"],
            "literature_count": corpus["literature_count"],
        },
        "chunking": {
            "unit": "section",
            "document_template": DOCUMENT_TEMPLATE,
            "skips_empty_or_literal_none": True,
            "document_count": len(candidates),
        },
        "embedding": {
            "provider": provider,
            "model_path": model_logical_path,
            "model_sha256": model_sha256,
            "max_tokens": int(embedder.max_tokens),
            "dtype": dtype,
            "dimension": int(matrix.shape[1]),
            "normalized": True,
            "library_versions": _library_versions(),
        },
        "archive_sha256": files_sha256(target, list(ARCHIVE_FILES)),
    }
    (target / MANIFEST_FILE).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def load_knowledge_base(
    directory: str | Path,
    literature: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    knowledge_base_id: str,
    model_sha256: str,
    max_tokens: int,
) -> tuple[Any, list[dict[str, Any]], dict[str, Any]]:
    """Load the index, refusing it unless it matches this A, this model and its own digest."""

    np = _numpy()
    source = Path(directory)
    for name in (MANIFEST_FILE, *ARCHIVE_FILES):
        if not (source / name).is_file():
            raise KnowledgeBaseError(
                f"Knowledge base {str(source)!r} is missing {name}; build it with "
                "python -m components.person_b.build_knowledge_base (no silent rebuild)"
            )
    manifest = json.loads((source / MANIFEST_FILE).read_text(encoding="utf-8"))
    if manifest.get("kb_schema_version") != KB_SCHEMA_VERSION:
        raise KnowledgeBaseError(
            f"Knowledge base schema {manifest.get('kb_schema_version')!r} "
            f"is not {KB_SCHEMA_VERSION!r}"
        )
    if manifest["knowledge_base_id"] != knowledge_base_id:
        raise KnowledgeBaseError(
            f"Knowledge base id {manifest['knowledge_base_id']!r} does not match "
            f"config {knowledge_base_id!r}"
        )
    if files_sha256(source, list(ARCHIVE_FILES)) != manifest["archive_sha256"]:
        raise KnowledgeBaseError("Knowledge base files do not match archive_sha256")

    corpus = literature["payload"]["corpus"]
    if manifest["corpus"]["sha256"] != corpus["sha256"]:
        raise KnowledgeBaseError(
            "Knowledge base was built from a different corpus: "
            f"kb sha256={manifest['corpus']['sha256'][:12]}, "
            f"A sha256={corpus['sha256'][:12]}"
        )
    built = manifest["embedding"]
    if built["model_sha256"] != model_sha256:
        raise KnowledgeBaseError(
            "Embedding model does not match the model the index was built with "
            f"(index {built['model_sha256'][:12]}, model {model_sha256[:12]})"
        )
    if built["max_tokens"] != max_tokens:
        raise KnowledgeBaseError(
            f"Index was built with max_tokens={built['max_tokens']}, runtime uses {max_tokens}"
        )

    sections = json.loads((source / SECTIONS_FILE).read_text(encoding="utf-8"))
    if [item["section_id"] for item in sections] != [
        item["section_id"] for item in candidates
    ]:
        raise KnowledgeBaseError(
            "Knowledge base sections do not match the sections of A.Literature "
            "(different content, order or None-filtering); rebuild the knowledge base"
        )
    matrix = np.load(source / EMBEDDINGS_FILE)
    if matrix.shape != (len(candidates), built["dimension"]):
        raise KnowledgeBaseError(
            f"Knowledge base matrix shape {matrix.shape} does not match "
            f"{len(candidates)} sections x {built['dimension']} dimensions"
        )
    return matrix, sections, manifest
