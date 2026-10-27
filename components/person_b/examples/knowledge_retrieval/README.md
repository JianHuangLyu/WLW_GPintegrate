# Example: `knowledge_retrieval`

Synthetic `A` and `D` in, expected `F.Chunks@2.0` out. Redistributable; no real corpus, patient or
model is involved.

| File | Role |
|---|---|
| `A_literature.valid.json` | the A from `../prepare_literature` (a test checks they are identical) |
| `D_dx_pairs.valid.json` | a valid D built with Person A's contract stub; `Histologic_Type` is `IC` |
| `config.example.json` | `mode: dense` with the **hashing** test embedder |
| `F_chunks.expected.json` | the F that the commands below produce |

## The hashing embedder

`embedding.provider: hashing` is a deterministic bag-of-words embedder with no semantic quality. It
exists only so the example runs without torch or a model download and gives the same ranking on every
machine. The real configuration is `configs/dense.default.json` (MedEmbed). Because the
knowledge base of this example has no model directory, its `embedding_model_path` is
`example://hashing-bow`.

## Expected result

Three chunks for `example-case-dx-001`, all from "Invasive breast carcinoma of no special type",
ranks 1..3: Essential criteria (0.7329), Histopathology (0.6792), Cytology (0.5887). The sections
that are literal `"None"` are never retrieved; the index has 15 documents (5 diseases x 3 sections).

Ordering and tie-break rules are fixed: best cosine first, equal scores keep corpus order
(`source_idx`, `section_idx`).

## Run it

Stage the inputs below `run/`, build the example knowledge base, then retrieve. Configs must be below
`components/person_b/configs/`, so use the loadable copy of `config.example.json`
(`configs/example.dense.hashing.json`; a test checks the two are equal):

```bash
mkdir -p ../run/output/work/b_example
cp components/person_b/examples/knowledge_retrieval/A_literature.valid.json ../run/output/work/b_example/A_literature.json
cp components/person_b/examples/knowledge_retrieval/D_dx_pairs.valid.json   ../run/output/work/b_example/D_dx_pairs.json

python -m components.person_b.build_knowledge_base \
  --input ../run/output/work/b_example/A_literature.json \
  --config components/person_b/configs/example.dense.hashing.json
# -> ../reference/person_b/checkpoint/kb-example-hashing (delete it afterwards)

python -m components.person_b.knowledge_retrieval \
  --input ../run/output/work/b_example/A_literature.json \
  --input ../run/output/work/b_example/D_dx_pairs.json \
  --output ../run/output/work/b_example/F_chunks.json \
  --config components/person_b/configs/example.dense.hashing.json
```

## What may differ from `F_chunks.expected.json`

Everything else is exact. These depend on the machine and are excluded from the comparison in
`tests/test_person_b_examples.py`:

- `knowledge_base.archive_path` (where you built the index) and `archive_sha256` (it digests the
  `.npy` bytes, which can differ between NumPy versions);
- `dense_score` and `relevance_score` are compared with a tolerance (5 and 3 decimal places).

Sections, order, ranks, token counts and every other field must match exactly.
