# Query Generation

## Contract

```text
D.DxPairs@2.0 + F.Chunks@2.0
              └─ query_generation.py
                    └─ G.VisualAttributeQueries@2.0
```

D and F must share `case_id`. F chunks are joined to a diagnosis by
`dx_pair_id`. G preserves D and adds `visualAttrQueries` to each DxItem.

## Backends

- `example`: deterministic public contract fixture.
- `reference`: map Histologic Type to mounted type-level visual criteria.
- `learnable_soft_prompt`: run Gemma with the mounted Stage 2 `.pt`; use exactly
  three F chunks for each mapped Histologic Type.

The learned backend emits every canonical visual option with one condition:
`Must_True`, `Must_False`, `High_Possibly_True`, `Low_Possibly_True`,
`Negligible`, or `Not_Mentioned`. Output with missing/extra options or illegal
conditions is rejected before G is written.

Schema-valid F is not itself a guarantee of usable evidence or valid model
output. Generic/uninformative chunk text can produce malformed generations;
the runtime rejects them without repairing JSON or writing a partial artifact.
The local-delivery smoke uses three known ADH chunks from the mounted fixed
reference vocabulary to check execution, not retrieval/generalization quality.

## Required external files

```text
reference/person_a/
├── checkpoint/
│   ├── gemma-3-1b-it/                 # all seven files from the pinned tree manifest
│   └── soft_prompt_stage2_64SP_50epoch_chunk_option_conditions_retrieval_mixed_best.pt
└── template_ref/
    ├── Histologic_Type_mappingTable.json
    ├── candidateReference.json
    ├── [typeLevel]visualAttrs_v1.2.1_2603241656.json
    └── chunks_with_attribute_condition.json
```

Mount `reference/` at `/reference:ro`. The configured `model_path` is
`../reference/person_a/checkpoint/gemma-3-1b-it`; identity remains
`google/gemma-3-1b-it`, revision `dcc83ea841ab6100d6b47a070329e1ba4cf78752`.
The loader checks the fixed manifest and every model file before local-only
loading. No HF token, cache reconstruction, or network is needed. G records
verification under `reference_versions.learnable_query_generation.model_integrity`.
See [LOCAL_MODELS.md](LOCAL_MODELS.md) for the exact preparation policy.

Person B only needs to provide schema-valid F chunks containing `dx_pair_id`,
`chunk_id`, and non-empty `text`. Person A does not import Person B code.
Chunks for each DxPair are ordered by ascending `retrieval_rank`; the learned
backend uses the configured top N (currently three). Duplicate `chunk_id`,
duplicate rank within one DxPair, or a chunk whose `dx_pair_id` is absent from
D is rejected. G records the selected IDs and ranks in provenance.

## Run without Docker

Reference backend:

```bash
python -m components.person_a.query_generation \
  --input ../run/output/work/D_dx_pairs.json \
  --input ../run/output/work/F_chunks.json \
  --output ../run/output/work/G_queries.json \
  --config components/person_a/configs/query_generation.default.json
```

Learned backend:

```bash
python -m components.person_a.query_generation \
  --input ../run/output/work/D_dx_pairs.json \
  --input ../run/output/work/F_chunks.json \
  --output ../run/output/work/G_queries.json \
  --config components/person_a/configs/query_generation.learnable.json
```

## Run with Docker

The image defaults to Report Decompose, so Query Generation overrides the
entrypoint:

```bash
docker run --rm --gpus all --network none \
  -v "$(pwd)/../reference:/reference:ro" \
  -v "$(pwd)/../run:/run" \
  --entrypoint python \
  wlw/person-a:0.9.0 \
  -m components.person_a.query_generation \
  --input /run/output/work/D_dx_pairs.json \
  --input /run/output/work/F_chunks.json \
  --output /run/output/work/G_queries.json \
  --config /app/components/person_a/configs/query_generation.learnable.json
```

`query_generation.learnable.json` limits GPU placement and offloads remaining
BF16 layers to host RAM for low-memory GPUs. On an HPC GPU with sufficient VRAM,
set `device_map_strategy` to `single_device` in a config under
`components/person_a/configs/`. Host RAM budget is 16 GB including up to 12 GiB
CPU offload and overhead; hardware minima remain unverified.

## Acceptance checks

- Local model files match the fixed tree manifest before any Transformers load.
- D and F pass their schemas and share `case_id`.
- Each mapped Histologic Type has at least three matching F chunks.
- F has unique chunk IDs and unique retrieval ranks per DxPair, with no foreign
  `dx_pair_id` values.
- Query `dx_pair_id` and `chunk_ids` identify the actual inputs used.
- Every visual option receives exactly one legal condition.
- G passes `G_visual_attribute_queries.schema.json` and preserves D metadata.
- Missing assets, model/GPU failures, or invalid model output exit non-zero and
  do not leave a partial G.
