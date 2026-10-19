# Person B: literature preparation and knowledge retrieval

Person B turns a literature corpus into the `A.Literature@2.0` artifact and, for every case,
retrieves the sections that best match its `Histologic_Type` into `F.Chunks@2.0` (the input of
Person A's query generation).

| | |
|---|---|
| Component version | `0.5.0` (`person-b/knowledge-retrieval:0.5.0`, `person-b/literature-preparation:0.2.0`) |
| Contracts | `A.Literature@2.0`, `D.DxPairs@2.0` (input), `F.Chunks@2.0` |
| Retrieval method | pure **dense** (`retrieval_mode: dense`); exact cosine search over L2-normalised vectors in a NumPy matrix. No sparse/hybrid part, so `sparse_score`/`sparse_rank` are `null` and `hybrid_weights` is `{dense: 1.0, sparse: 0.0}` |
| Index unit | one section = one document, text `Disease: <disease>\nSection: <section title>\nContent: <text>` (the layout of the `0401_RAG_3` experiments). Empty and literal `"None"` sections are kept in A but not indexed |
| Embedding model | `abhinand/MedEmbed-large-v0.1`, Hugging Face revision `963121bfb9c625475f65b08fb54990ce9c4e7a1a` (BERT-large, 1024 dimensions, 512-token limit) |
| Python / frameworks | Python 3.13 for the host runs, Python 3.12.15 in the Docker image; `torch 2.6.0+cu124`, `sentence-transformers 6.1.0`, `transformers 5.17.0`, `numpy 2.5.3` |
| Hardware | GPU optional (`embedding.device: auto` falls back to CPU). Verified on an RTX 2050 (4 GB). Peak VRAM/RAM and CPU-only timing were **not measured** |

## Corpus

`rag_database@1`: a folder with one `<disease>.json` per disease (`disease_name`,
`sections[{section_type, page_content}]`, `images`). The verified corpus is the WHO Breast Tumours
(5th ed.) text export: 87 diseases, 1349 sections, of which 93 are literal `"None"`, leaving
**1256 indexed sections**. It has no upstream revision number; it is identified by its SHA-256.

- Source format, versioned by Person B: see `prepare_literature.py` (docstring).
- There is no chapter hierarchy or URL in this source, so `title_list` is
  `[corpus title, null, null, disease name]` and `href` is `null`.
- `images` are ignored: A is text-only.
- Files without a `.json` extension (empty chapter placeholders) are skipped.

## Assets and digests

Large assets live in the sibling `reference/person_b/` directory and are never committed or put in
the image. Configs and artifacts name them by the logical path `reference/person_b/...`.

| Asset | Logical path | SHA-256 |
|---|---|---|
| Corpus snapshot | `reference/person_b/checkpoint/rag_database` | `ffd76f0893866aad7b2dd0f71bce76c90d1de8faf245eb2414a500637c01bc30` |
| Embedding model | `reference/person_b/checkpoint/embedding-model-medembed-large-v0.1` | `a31db9d8ad309438808f3e5faf1af7425f4192c679aa091f0514f647860554c5` |
| Knowledge base `kb-who-breast-5e-medembed-v1` | `reference/person_b/checkpoint/kb-who-breast-5e-medembed-v1` | `f762740d56faddca51e8a9c83d8302a68d9d644eb3b4dc1e6916ebe4de0a74b9` |

How the digests are defined (the same code verifies them at runtime):

- corpus: SHA-256 over every `*.json` file (file name + raw bytes), taken in **file-name string
  order** (not `Path` order, which differs between Windows and Linux);
- model: `directory_sha256`, over every file below the model directory (relative path + content);
- knowledge base: `files_sha256` over `embeddings.npy` and `sections.json`; `manifest.json` records
  it and is excluded.

`external-assets.yaml` lists every asset with its source, revision, SHA-256 (also per file for the
model and the index), size, licence/access policy, logical path and dependencies. **The licence of
the corpus is unconfirmed** (see there); the model is Apache-2.0.

The model directory is a copy of the Hugging Face snapshot above without `README.md`. The runtime
never downloads anything (`HF_HUB_OFFLINE=1` in the image).

The knowledge base was built in fp32 (`dtype: null`), `max_tokens: 512`, normalised embeddings.
`manifest.json` also records the corpus, chunking template, embedding settings and library versions.

## Commands

All paths below are inside the repository root. Inputs and outputs of the CLIs must be under the
sibling `run/`; configs must be under `components/person_b/configs/`.

```bash
# 1. RAG_database folder -> A (shared by all cases)
python -m components.person_b.prepare_literature \
  --source ../reference/person_b/checkpoint/rag_database \
  --output ../run/input/pipeline/A_literature.json \
  --config components/person_b/configs/prepare_literature.rag_database.json

# 2. A -> knowledge base (once per corpus/model version; refuses to overwrite an existing one)
python -m components.person_b.build_knowledge_base \
  --input ../run/input/pipeline/A_literature.json \
  --config components/person_b/configs/dense.default.json

# 3. per case: A + D -> F   (the Unified CLI used by the pipeline)
python -m components.person_b.knowledge_retrieval \
  --input ../run/input/pipeline/A_literature.json \
  --input ../run/output/work/D_dx_pairs.json \
  --output ../run/output/work/F_chunks.json \
  --config components/person_b/configs/dense.default.json
```

`pipeline/run_prepare_literature.py` and the shared example pipeline keep using
`configs/example.json` (`mode: example`), which emits the contract stub.

### Configs (`components/person_b/configs/`)

| File | Mode | Purpose |
|---|---|---|
| `example.json` | `example` | shared contract stub (empty F) |
| `dense.default.json` | `dense` | real retrieval and index build |
| `prepare_literature.rag_database.json` | `rag_database` | RAG_database folder to A |
| `example.dense.hashing.json`, `example.rag_database.json` | `dense`, `rag_database` | copies of the files under `examples/` |

Retrieval parameters (all in config, none hard-coded): `retrieval.dx_items` (only
`Histologic_Type`), `top_k` (3), `candidate_k` (3, must be >= `top_k`), `min_chunks` (3),
`embedding.max_tokens`, `embedding.query_max_tokens` (128), `embedding.device`, `embedding.dtype`,
`embedding.batch_size`, and `retrieval.queries` (one query per `DxResultCls`).

## Retrieval behaviour

- The query is chosen by `DxResultCls` (`UDH`, `ADH`, `DCIS`, `FEA`, `IC`), not by the report text.
  `OTHER`/`AMBIGUOUS` (and cases without a Histologic_Type) get no chunks; Person A marks them
  unmapped and does not read F for them.
- Chunks are ordered best first and `retrieval_rank` is 1..`top_k`; ties keep corpus order.
- Person A's trained soft prompt needs **exactly three** chunks per mapped Histologic_Type and
  reads them in F order, so `top_k` is 3 and fewer than `min_chunks` is an error, never padding.
- `relevance_score` is the cosine clipped to 0..1; `dense_score` is the raw cosine.
- `indexed_token_count` is the number of tokens actually embedded (capped at `max_tokens`).

## Docker

```bash
docker build --no-cache -f components/person_b/Dockerfile -t wlw/person-b:0.5.0 .

docker run --rm --gpus all \
  -v "<host>/reference:/reference:ro" -v "<host>/run:/run" \
  wlw/person-b:0.5.0 \
  --input /run/input/pipeline/A_literature.json \
  --input /run/output/work/D_dx_pairs.json \
  --output /run/output/work/F_chunks.json \
  --config /app/components/person_b/configs/dense.default.json
```

The image holds code and libraries only (torch 2.6.0 cu124 wheel, same as Person A's image). The
corpus, model and knowledge base are mounted.

Run Person B's own tests inside the image (they need no model, index or corpus; the image carries
only `tests/test_dense_retrieval.py` and `tests/test_person_b_examples.py`):

```bash
docker run --rm --entrypoint python wlw/person-b:0.5.0 \
  -m unittest tests.test_dense_retrieval tests.test_person_b_examples -v
```

Verified: `docker build --no-cache` succeeds (about 22 min, almost all of it downloading the CUDA
torch wheels). Size: about 3.0 GB compressed, about 6 GB of layers once unpacked (the CUDA torch
layer is 5.3 GB); `docker images` on Docker Desktop's image store reports 9.09 GB. Inside the image the libraries are exactly the pinned versions and
`torch.cuda.is_available()` is true with `--gpus all`. Running the command above with the real model,
knowledge base and a real D gives the same F as the host run, on GPU and on CPU (same sections,
ranks and `dense_score` to 6 decimals; the whole run, including model digest check, took about
100 s on GPU and 70 s on CPU through Docker Desktop bind mounts).

## Failure conditions (non-zero exit)

- A, D or F violates its contract schema; D has more than one case.
- The knowledge base directory or its files are missing (no silent rebuild).
- `archive_sha256`, the model SHA-256, the corpus SHA-256, the knowledge base id or `max_tokens`
  recorded in the manifest differ from what is mounted or configured.
- The index sections differ from the sections of the A artifact (content, order or None-filtering).
- A query is longer than `embedding.query_max_tokens` (no silent truncation).
- A mapped Histologic_Type finds fewer than `min_chunks` sections; `top_k < min_chunks`;
  `candidate_k < top_k`.
- An asset path leaves `reference/person_b/`; a config is outside `components/person_b/configs/`.
- `build_knowledge_base` finds an existing knowledge base and `--overwrite` was not given.

## Known limitations

- **Truncation:** 69 of the 1256 sections are longer than 512 tokens and are truncated when
  embedded (measured with this model's tokenizer). `indexed_token_count` shows it per chunk.
- **Section choice is not restricted.** The three chunks are the three closest sections of any kind,
  so they can include sections with no visual description (for example Localization). Whether
  retrieval should be limited to Histopathology/Cytology/Essential criteria depends on what Person
  A's soft prompt was trained on and is undecided.
- **Neighbouring diseases:** in a 5-query check with this model, 13 of the 15 chunks that Person A
  reads came from the queried disease. DCIS got 1 of 3: its queries also retrieve
  "Carcinoma in situ" and "Papillary ductal carcinoma in situ". This is a small, unlabelled check,
  not an evaluation.
- **`IC` means IBC-NST.** The query follows Person A's class, not the report wording, so a report
  of invasive lobular carcinoma that Person A classified as `IC` is answered with IBC-NST sections.
- **Only dense retrieval.** There is no sparse or hybrid mode.
- **Not measured:** peak VRAM and RAM, and the split of the roughly 100 s container run between
  model digest check, model load and search (the 1.3 GB model is hashed on every run). Known build
  time of the index on an RTX 2050: about 140 s including model load.
- Real patient data must stay under `run/`; nothing under `reference/` or `run/` is committed.

## Examples and tests

- `examples/prepare_literature/` and `examples/knowledge_retrieval/`: synthetic, redistributable
  inputs with expected outputs (see their READMEs).
- `tests/test_dense_retrieval.py` (retrieval, index verification, adapter),
  `tests/test_person_b_examples.py` (the examples stay reproducible) and
  `tests/test_person_b_assets.py` (`external-assets.yaml` agrees with this README, the configs and
  `component.yaml`; skipped when PyYAML is missing):

```bash
python -m unittest tests.test_dense_retrieval tests.test_person_b_examples
```
