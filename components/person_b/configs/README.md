# Person B configs

- `example.json`: the shared contract example (`mode: example`); no corpus, index or model.
- `dense.default.json`: real retrieval and index build (`mode: dense`). Asset paths are logical
  `reference/person_b/...` paths; they must stay under the sibling `reference/person_b/`.
- `prepare_literature.rag_database.json`: wraps a RAG_database folder as A (`mode: rag_database`).
