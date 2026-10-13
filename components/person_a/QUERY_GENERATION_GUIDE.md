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

## Required external files

```text
reference/person_a/
├── checkpoint/soft_prompt_stage2_64SP_50epoch_chunk_option_conditions_retrieval_mixed_best.pt
└── template_ref/
    ├── Histologic_Type_mappingTable.json
    ├── candidateReference.json
    ├── [typeLevel]visualAttrs_v1.2.1_2603241656.json
    └── chunks_with_attribute_condition.json
```

Mount `reference/` at `/reference:ro`; use `run/cache/huggingface` as the
Hugging Face cache and provide `HF_TOKEN` through the environment. Asset hashes
and revisions are declared in `external-assets.yaml`.

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
docker run --rm --gpus all \
  --env-file integration/.env \
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
set `device_map_strategy` to `single_device` in an external runtime config.

## Acceptance checks

- D and F pass their schemas and share `case_id`.
- Each mapped Histologic Type has at least three matching F chunks.
- F has unique chunk IDs and unique retrieval ranks per DxPair, with no foreign
  `dx_pair_id` values.
- Query `dx_pair_id` and `chunk_ids` identify the actual inputs used.
- Every visual option receives exactly one legal condition.
- G passes `G_visual_attribute_queries.schema.json` and preserves D metadata.
- Missing assets, model/GPU failures, or invalid model output exit non-zero and
  do not leave a partial G.
