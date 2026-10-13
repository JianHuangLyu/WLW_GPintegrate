# Person A: Report Decompose and Query Generation

Component version: `0.9.0`

## Interfaces

| Entrypoint | Input | Output |
|---|---|---|
| `components.person_a.prepare_case_list` | `B.ReportTables@1.0` | `CaseListInput@1.0` batch |
| `components.person_a.report_decompose` | one `CaseListInput@1.0` case | `D.DxPairs@2.0` |
| `components.person_a.query_generation` | `D.DxPairs@2.0` + `F.Chunks@2.0` | `G.VisualAttributeQueries@2.0` |

`report_decompose` and `query_generation` handle one case per invocation.
`pipeline/run_pipeline.py` demonstrates multi-case fan-out with repository
example configs. Production orchestration uses the same single-case CLI with
production configs. Inputs are identified by contract, not command-line order.

## Behavior

- VGHTC: use the original hospital Regex only.
- CGMH: use the hospital Regex first and MedGemma for configured fallback cases.
- Normalize Histologic Type to `UDH`, `FEA`, `ADH`, `DCIS`, `IC`, `OTHER`, or
  `AMBIGUOUS`; keep other diagnostic items as free text.
- Preserve case, block, stain, WSI identity, and WSI filepath in D.
- Generate G from D and Person B's F chunks using either deterministic reference
  mapping or Gemma plus the mounted Stage 2 soft-prompt checkpoint.

## Runtime and external assets

- Python 3.11
- PyTorch 2.6.0 with CUDA 12.4
- Transformers 5.16.1, Accelerate 1.14.0, bitsandbytes 0.50.1
- NVIDIA GPU required for MedGemma and the learnable query backend

External files are not committed or copied into the image:

```text
reference/person_a/
├── checkpoint/soft_prompt_stage2_64SP_50epoch_chunk_option_conditions_retrieval_mixed_best.pt
└── template_ref/
    ├── DxStructuredCandidates_integrated.json
    ├── Histologic_Type_mappingTable.json
    ├── candidateReference.json
    ├── [typeLevel]visualAttrs_v1.2.1_2603241656.json
    └── chunks_with_attribute_condition.json
```

`external-assets.yaml` records their expected paths and SHA-256 values. Mount
the sibling `reference/` directory read-only at `/reference` and the sibling
`run/` directory read-write at `/run`. Set `HF_TOKEN` at runtime; do not store it
in a config file. Production configs enforce the manifest: undeclared paths or
SHA-256 mismatches fail before model loading. Synthetic tests explicitly use
record-only integrity mode.

For an offline Hugging Face mirror, export every snapshot file's size and
SHA-256 from the pinned revision directory:

```bash
python -m components.person_a.hf_snapshot_manifest \
  --model-id google/gemma-3-1b-it \
  --revision dcc83ea841ab6100d6b47a070329e1ba4cf78752 \
  --snapshot ../run/cache/huggingface/hub/models--google--gemma-3-1b-it/snapshots/dcc83ea841ab6100d6b47a070329e1ba4cf78752 \
  --output ../run/output/person_a_assets/gemma-3-1b-it.snapshot.json
```

## CLI

Run from the repository root.

Normalize hospital tables to CaseList:

```bash
python -m components.person_a.prepare_case_list \
  --input ../run/input/B_report_tables.json \
  --output ../run/input/pipeline/cases.json \
  --config components/person_a/configs/report_decompose.default.json
```

The orchestrator must split this batch into one-case CaseList files before
calling `report_decompose`.

Create D for one case:

```bash
python -m components.person_a.report_decompose \
  --input ../run/input/pipeline/case-001.json \
  --output ../run/output/work/D_dx_pairs.json \
  --config components/person_a/configs/report_decompose.default.json
```

Create G from D and F:

```bash
python -m components.person_a.query_generation \
  --input ../run/output/work/D_dx_pairs.json \
  --input ../run/output/work/F_chunks.json \
  --output ../run/output/work/G_queries.json \
  --config components/person_a/configs/query_generation.learnable.json
```

## Docker

Build from the repository root:

```bash
docker build \
  -f components/person_a/Dockerfile \
  -t wlw/person-a:0.9.0 .
```

The default image entrypoint is `report_decompose`:

```bash
docker run --rm --gpus all \
  --env-file integration/.env \
  -v "$(pwd)/../reference:/reference:ro" \
  -v "$(pwd)/../run:/run" \
  wlw/person-a:0.9.0 \
  --input /run/input/pipeline/case-001.json \
  --output /run/output/work/D_dx_pairs.json \
  --config /app/components/person_a/configs/report_decompose.default.json
```

See `REPORT_DECOMPOSE_GUIDE.md` for Excel/WSI mounts and
`QUERY_GENERATION_GUIDE.md` for the Query Generation Docker command.

## Validation

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover \
  -s components/person_a/tests -v
docker compose -f integration/compose.yaml config --quiet
```

The CLI exits non-zero and does not write a partial artifact when input schema,
case identity, external assets, model loading, or output schema validation fails.
Reports without Histologic Type are valid and do not emit that DxItem.
