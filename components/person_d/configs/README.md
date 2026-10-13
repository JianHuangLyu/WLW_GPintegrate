# Person D configuration

`example.json` (`mode: example`) is the contract-only stub used by the repository pipeline test. It
contains no WSI setting, model or prompt path, threshold, or device choice and runs no model.

`native.example.json` (`mode: native`) runs PLIP + CONCH visual attribute extraction and the matching
filter. Reference paths must stay below sibling `reference/person_d/`; ROI crops and relative WSI paths
resolve below sibling `run/`. Weights load from local files only.

`native.smoke.json` is identical except that CONCH points to random-initialised `conch_ViT-B-16`
weights. It exercises the complete native path (OpenSlide, both models, matching) on a clean machine
without gated CONCH access. Its decisions have no diagnostic meaning; never use it for research.
Create the smoke checkpoint once (the CONCH package from `requirements.txt` is required):

```bash
python -c "import json, torch; from pathlib import Path; from conch.open_clip_custom import factory; from conch.open_clip_custom.coca_model import CoCa; cfg = json.loads((factory.CFG_DIR / 'conch_ViT-B-16.json').read_text()); cfg.pop('custom_text', None); torch.manual_seed(0); out = Path('../reference/person_d/checkpoint/conch_smoke_random'); out.mkdir(parents=True, exist_ok=True); torch.save(CoCa(**cfg).state_dict(), out / 'pytorch_model.bin')"
```

| Key | Meaning |
|---|---|
| `component_version` | Written as the H `producer`; must match `component.yaml` and the image tag. |
| `device` | `cuda`, `cuda:<n>`, or `cpu`. A CUDA device fails when CUDA is unavailable; there is no silent CPU fallback. |
| `extraction.prompts_path` | Attribute vocabulary, option descriptions, multi-select attributes, and PLIP/CONCH prompts. |
| `extraction.prompts_sha256` | Required SHA-256 of the prompt asset, checked at the start of every native run; a mismatch fails. |
| `extraction.example_dir` | Few-shot `ROI_Analysis/<group>/<attribute>/<option>/` images; required when `use_example_prototypes` is true. |
| `extraction.example_tree_sha256` | Required tree hash of `example_dir` (algorithm in `external-assets.yaml`) when `use_example_prototypes` is true, checked before the models load; a mismatch fails. Every file must also sit in a `<group>/<attribute>/<option>/` image folder the loader reads. |
| `extraction.plip.support_files_sha256` | Required SHA-256 of the five PLIP snapshot files read besides `pytorch_model.bin` (`config.json`, `preprocessor_config.json`, `special_tokens_map.json`, `tokenizer.json`, `tokenizer_config.json`), checked before the models load; a mismatch fails. |
| `extraction.plip.weight_path` | Local `vinid/plip` snapshot directory. `revision` records the expected Hugging Face revision. |
| `extraction.conch.checkpoint_path` | Local CONCH `pytorch_model.bin`; `model_name` selects the CONCH model config. |
| `extraction.plip.sha256`, `extraction.conch.sha256` | Expected SHA-256 of PLIP `pytorch_model.bin` and the CONCH checkpoint, checked before loading; a mismatch fails. `null` leaves the file unverified and is recorded in H. CONCH loads with `strict=False`, so set its value once the gated file is obtained. |
| `extraction.image_score_weight` | Weight of image-to-option-prompt similarity. |
| `extraction.text_score_weight` | Weight of custom-text-prompt-to-option similarity; used when `use_custom_text_prompt` is true. |
| `extraction.example_score_weight` | Weight of image-to-example-prototype similarity; used when `use_example_prototypes` is true. |
| `extraction.multi_select_margin` | Multi-select attributes keep options within this margin of the best score. |
| `extraction.copy_na_labels` | Keep agreed `N/A` labels. |
| `extraction.enable_prompt_chunking`, `token_safety_margin`, `fallback_words_per_chunk` | Long option prompts are split into chunks whose embeddings are averaged. |
| `matching.label_map_path` | Extraction-label to diagnosticCriteria-option aliases; its `criteria_version` must equal G `diagnosticCriteria.version`. |
| `matching.label_map_sha256` | Required SHA-256 of the label map, checked at the start of every native run; a mismatch fails. |
| `matching.condition_weights` | Weight in [-1, 1] for each informative condition: `Must_True`, `High_Possibly_True`, `Low_Possibly_True`, `Must_False`. |
| `matching.score_threshold` | Selected requires `score >= score_threshold`, within [-1, 1]. |
| `matching.min_evaluated_attributes` | Fewer evaluated attributes yields `skipped` with `insufficient_visual_evidence`. |
| `matching.unverified_must_true` | What happens when a Must condition cannot be verified, either because an attribute with a Must_True option was not evaluated or because a Must_True / Must_False option cannot be reached by any vocabulary label (`MAPPING.md`): `skip` gives `skipped` / `insufficient_visual_evidence`, `reject` gives `rejected` / `must_condition_failed`. Either way the query is never `selected`. |
