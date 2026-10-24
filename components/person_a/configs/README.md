# Person A configs

- `example.json`: deterministic public contract smoke test; no external assets.
- `report_decompose.default.json`: production report extraction. VGHTC uses Regex;
  CGMH uses Regex and invokes MedGemma according to the configured fallback rules.
- `query_generation.default.json`: deterministic reference mapping to G.
- `query_generation.learnable.json`: Gemma plus the Stage 2 condition soft-prompt;
  it predicts one of six condition labels for every canonical visual option.
  The checked-in profile uses CPU offload for low-memory GPUs; an HPC runtime
  config may set `device_map_strategy` to `single_device`.
- `query_generation.single_device.json`: the same pinned model and soft prompt,
  placing the whole model on one GPU. Used by the reproducible delivery smoke
  test; sufficient free VRAM is required. It keeps dtype `auto`.

Production configs set `asset_integrity` to `enforce`. Every canonical
reference/checkpoint path must be declared in `external-assets.yaml`, and the
runtime fails before inference when its SHA-256 differs. `record_only` is
reserved for synthetic tests or explicitly versioned experimental assets.

Production paths are logical sibling paths under `../reference/person_a/`.
Both production model blocks require an explicit `model_path` under `checkpoint/`:
`gemma-3-1b-it/` for Query Generation and `medgemma-1.5-4b-it/` for extraction.
`model_name` (Gemma) and `model_id` (MedGemma) remain original Hub identities;
`model_revision` must match the trusted external-asset declaration and tree manifest.
The model tree is always verified before local-only loading; `record_only` only
applies to single-file experimental/synthetic assets. No runtime token or model
download is required or supported. Framework caches, if needed, stay under `run/`.
Both trusted model manifests are provided. Authorized model weights must be
materialized separately. See `../LOCAL_MODELS.md`.

Configs must not contain credentials, developer home directories, report data,
WSI data, or model files.
