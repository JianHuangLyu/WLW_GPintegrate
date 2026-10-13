# Person A configs

- `example.json`: deterministic public contract smoke test; no external assets.
- `report_decompose.default.json`: production report extraction. VGHTC uses Regex;
  CGMH uses Regex and invokes MedGemma according to the configured fallback rules.
- `query_generation.default.json`: deterministic reference mapping to G.
- `query_generation.learnable.json`: Gemma plus the Stage 2 condition soft-prompt;
  it predicts one of six condition labels for every canonical visual option.
  The checked-in profile uses CPU offload for low-memory GPUs; an HPC runtime
  config may set `device_map_strategy` to `single_device`.

Production configs set `asset_integrity` to `enforce`. Every canonical
reference/checkpoint path must be declared in `external-assets.yaml`, and the
runtime fails before inference when its SHA-256 differs. `record_only` is
reserved for synthetic tests or explicitly versioned experimental assets.

Production paths are logical sibling paths under `../reference/person_a/`. Runtime model
downloads and caches belong under `../run/cache/`. Configs must not contain credentials,
developer home directories, report data, WSI data, or model files.
