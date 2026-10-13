# Person D: Visual Attribute Extraction and Matching Filter

Owner: person_D. Component version `0.2.0` (`component.yaml`, config `component_version`
`person-d/visual-filter:0.2.0`, image tag `wlw/person-d:0.2.0`).

`visual_filter` consumes `E.ROIs@2.0` and `G.VisualAttributeQueries@2.0` and writes
`H.MatchedROIs@2.0` (schemas in `contracts/schemas/`). Every E ROI is kept with its upstream
`selection_history`, and `visual_attributes_matching_filter` events are appended at a fixed
granularity:

| Level | When | Linkage fields | Reasons |
|---|---|---|---|
| Query | the diagnostic pair has queries: one event per query | `dx_pair_id`, `query_id`, `criteria_status` | matching result, `query_unmapped`, `stain_not_in_reference_wsi` |
| Pair | the diagnostic pair has no query: one event for the pair | `dx_pair_id` | `no_visual_attr_query`, or `stain_not_in_reference_wsi` for a non-reference stain |
| Case | the case has no diagnostic pair: one event per ROI | none | `no_diagnostic_pair` |

Together with `case_id`, `stain_id` and `roi_id`, every query-level event therefore carries the full
`case_id + stain_id + roi_id + dx_pair_id + query_id` audit key; pair- and case-level events exist
only where no query exists to link to.

| Mode | Config | Behavior |
|---|---|---|
| `example` | `configs/example.json` | Contract-only stub for the repository pipeline test. No image or model; every ROI is `skipped` (`example_stub_no_evaluation`). |
| `native` | `configs/native.example.json` | PLIP + CONCH visual attribute extraction, then matching against G `diagnosticCriteria`. |
| `native` (smoke) | `configs/native.smoke.json` | Same path with random-initialised CONCH weights, for verifying the pipeline without gated CONCH access. Decisions have no diagnostic meaning. |

## Input validation (both modes)

`validate_inputs` (`visual_filter.py`) runs before either mode builds H, so `example` and `native`
accept or reject the same E/G pair:

- E/G `case_id` and `data_mode` are equal; H keeps that `data_mode`.
- The E/G stain sets are equal, every `referenceWSI` names a known stain, every query's `dx_pair_id`
  equals its DxItem's, and `roi_id` and `query_id` do not repeat.
- Every mapped query has a `diagnosticCriteria` with a `version` and, for each attribute, `options`
  and `conditions`.
- Every ROI has a valid metadata geometry (`geometry.py`): integer `level0_info.xywh` with
  `x, y >= 0` and positive width and height, positive `main_info.roi_wh`, positive finite MPPs, and
  `roi_wh` within 1 px of the level-0 size times `level0_info.mpp / main_info.mpp`.

Checks that need pixels run where pixels are read, in `native` mode only: the ROI must lie inside the
WSI, and a `main_info.roi_path` crop must be exactly `main_info.roi_wh` pixels. Crops are never
resampled, so a crop of any other size fails; WSI regions are always resampled to `roi_wh`.

## Asset integrity

`native` mode fails before writing H when a reference asset differs from the digest in its config:

| Asset | Config key | Checked |
|---|---|---|
| `visual_attribute_prompts.json` | `extraction.prompts_sha256` | at the start of every native run |
| `criteria_label_map.json` | `matching.label_map_sha256` | at the start of every native run |
| PLIP `pytorch_model.bin` | `extraction.plip.sha256` | before the models load |
| PLIP `config.json`, `preprocessor_config.json`, `special_tokens_map.json`, `tokenizer.json`, `tokenizer_config.json` | `extraction.plip.support_files_sha256` | before the models load |
| CONCH `pytorch_model.bin` | `extraction.conch.sha256` (`null` only for the smoke checkpoint) | before the models load |
| Few-shot example tree | `extraction.example_tree_sha256` | before the models load, when `use_example_prototypes` is on |

The few-shot tree must also have the layout the prototype loader reads: every file in a
`<group>/<attribute>/<option>/` image folder of a vocabulary option. A file anywhere else fails the
run instead of being ignored; H records the file count and the count the loader uses
(`reference_versions.visual_attribute_extraction.example_tree`).

`verify_assets` runs the same checks without loading a model, reports how many few-shot files the
loader uses, checks the accepted vocabulary mapping (next section), and exits 1 when anything is
missing or differs:

```bash
python -m components.person_d.verify_assets --config components/person_d/configs/native.example.json
```

## Vocabulary to diagnosticCriteria mapping

Prompt asset 1.1.0 has 24 attributes with 105 options; diagnosticCriteria 1.2.1 has 138 options for
the same attributes. [`MAPPING.md`](MAPPING.md) lists, per attribute, every vocabulary label, the
criteria option it reaches and the rule that applied, and classifies every criteria option that no
label reaches. It is generated from `mapping_acceptance.json`, the accepted mapping for this criteria
version:

| Finding | Count | Behaviour |
|---|---:|---|
| Unmapped vocabulary option | 1 | `Pattern` `one to several layers`: criteria 1.2.1 lists it under `Specific_Sub_Architectures`. The label is dropped. |
| Vocabulary option mapped to several criteria options | 1 | `Epithelial_Cell_Shape` `Cuboidal/Columnar` maps to `Cuboidal` and `Columnar`: it counts once when both carry the same condition and is dropped as ambiguous when they differ. |
| Unreachable criteria option, not a prediction target | 16 | 14 `Unable to confirm` (the backend shows it cannot assess an attribute through model disagreement) and 2 generic `Present, Not Otherwise Specified`. |
| Unreachable criteria option, not covered | 17 | 16 options the `pipeline_quilt_1m.py` vocabulary has no label for, and 1 it files under another attribute. The backend can never predict them. |

A Must_True or Must_False condition on an unreachable option cannot be verified, so it never counts
as passed (Native method, step 3); any other condition on an unreachable option never contributes to
the score. `tests/test_mapping.py` checks that the acceptance file covers every criteria option,
follows the mapping rule, classifies every unreachable option, matches `MAPPING.md`, and matches the
reference assets when they are present; `verify_assets` checks the assets against it as well. A
change to the prompt asset or the label map therefore needs a new acceptance file and
`python -m components.person_d.mapping --write`.

## Native method

1. **ROI image** (`roi_reader.py`): `main_info.roi_path` when present (below sibling `run/`, exactly
   `roi_wh` pixels); otherwise the WSI at `stains[].filepath` is read with OpenSlide at
   `level0_info.xywh` and resampled to `main_info.roi_wh`. Only an absolute WSI filepath may point
   outside `run/`; relative paths resolve below `run/`.
2. **Visual Attribute Extraction** (`visual_attribute_extraction.py`, ported from
   `pipeline_quilt_1m.py`): for each of the 24 vocabulary attributes (all diagnosticCriteria 1.2.1
   attributes), PLIP and CONCH each score every
   option as `image_score_weight * image-to-option-prompt + example_score_weight *
   image-to-example-prototype + text_score_weight * custom-prompt-to-option`. Long option prompts are
   chunked and averaged. Single-select attributes take the arg-max; `Pattern` and
   `Specific_Sub_Architectures` keep options within `multi_select_margin` of the best. Only labels both
   models agree on are kept (`roi.visualAttrs`); per-model predictions and scores go to
   `roi.visualAttrs_info.models`.
3. **Visual Attribute Matching Filter** (`matching_filter.py`): agreed labels map to criteria options
   through `criteria_label_map.json`, then exact, then case-insensitive matching. An attribute is
   evaluated when it maps to at least one informative condition. The decision is taken in this order:
   1. fewer than `min_evaluated_attributes` evaluated attributes: `skipped` (`insufficient_visual_evidence`);
   2. a Must_False option, or an evaluated Must_True attribute without a Must_True option whose
      Must_True options the vocabulary can all reach: `rejected` (`must_condition_failed`);
   3. an unverified Must condition: an attribute with a Must_True option that was not evaluated (not
      extracted, models disagree, unmapped or ambiguous label), or a Must_True / Must_False option
      that no vocabulary label can reach. It never counts as passed. With
      `unverified_must_true: skip` (default) the query is `skipped` (`insufficient_visual_evidence`);
      with `reject` it is `rejected` (`must_condition_failed`). This is checked before the score
      because a verified condition could change it;
   4. the mean `condition_weights` score `>= score_threshold`: `selected` (`visual_attributes_match`),
      otherwise `rejected` (`score_below_threshold`).

   `selected` therefore requires every Must_True attribute of the criteria to be evaluated and
   satisfied, and every Must_True and Must_False option to be reachable. `must_true_passed` and
   `must_false_passed` are `false` whenever the condition failed or is unverified. Per-attribute
   decisions (with `unreachable_must` where it applies), `evaluated_count`, `must_true_unverified`
   and `must_unverifiable` are stored in `roi.visualAttrs_info.matching.<query_id>`, so the causes
   of `insufficient_visual_evidence` stay distinguishable.

Other `skipped` reasons: `stain_not_in_reference_wsi`, `no_visual_attr_query`, `query_unmapped`,
`no_diagnostic_pair`. Models load only when at least one reference-WSI ROI has a mapped query.

## Runtime

| Item | Value |
|---|---|
| Python / OS | 3.10, Ubuntu 22.04 (`nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04`) |
| Frameworks | torch 2.11.0+cu128, torchvision 0.26.0+cu128, transformers 4.57.6, timm 0.9.16, CONCH `141cc09c`, openslide-python 1.4.6, libopenslide0 3.4.1+dfsg-5build1 |
| CUDA / driver | The base image declares `NVIDIA_REQUIRE_CUDA=cuda>=12.8` and torch is the cu128 build, so the host driver must support CUDA 12.8 (NVIDIA R570 or newer). Verified only with driver 592.00. |
| GPU | Expected for `device: cuda`; one GPU. A CUDA device fails when CUDA is unavailable. |
| CPU fallback | Supported with `device: cpu`; same decisions and scores as the GPU run on the canonical example. |
| Batch size | One image per forward pass for ROIs and example images; not configurable |
| Minimum VRAM | Verified on 8 GB; lower capacity not validated (measured peak below: 2.31 GiB reserved) |
| Suggested timeout | GPU: 300 s plus 1 s per ROI (derived from the measurements below). CPU: no per-ROI figure; allow at least 900 s for the canonical example. |

Measurements. All use this version (0.2.0), `configs/native.example.json` (`cpu` instead of `cuda`
for the CPU row), the official PLIP and CONCH checkpoints, prompt asset 1.1.0 and few-shot tree 1.0.1
(440 images), on one host: NVIDIA GeForce RTX 5060 Laptop GPU 8 GB, driver 592.00, Windows 11,
torch 2.11.0+cu128; the image runs in the Docker Desktop VM (12 vCPU, 7.6 GiB). Each figure is a
single run unless stated. The canonical example has 2 extracted ROIs of 1024 × 1024 px.

| Figure | Value | Data | Method |
|---|---|---|---|
| GPU end to end, image | 121 s | canonical example | wall time of `docker run` as UID 1000, from container start to H written; includes model loading, digest checks and encoding the 440 example images |
| GPU end to end, host | 135 s | canonical example | wall time of the CLI on the host, same scope |
| GPU memory | peak 2.11 GiB allocated, 2.31 GiB reserved | canonical example | `torch.cuda.max_memory_allocated` / `max_memory_reserved` at the end of the host CLI run |
| Host RAM | peak working set 3.24 GiB | canonical example | process peak working set at the end of the host CLI run |
| GPU start-up | 73 s | models, digest checks and 440 example images | wall time of `load_extractor` on the host |
| GPU per ROI | mean 0.071 s, median 0.071 s (0.066 to 0.079 s) | the two canonical ROIs | 30 `extract` calls after 2 warm-up calls on the host, timed with `torch.cuda.synchronize` before and after each call |
| CPU end to end, image | 392 s, peak resident set 2.98 GiB | canonical example | wall time and `ru_maxrss` of the CLI in the image without a GPU; same statuses, reasons, scores and `visualAttrs` as the GPU run |
| CPU per ROI | not measured | | |

Start-up dominates and varied between runs on this host (73 to 89 s for `load_extractor`), so the
end-to-end figures are indicative, not a benchmark.

## External assets

All assets live below sibling `reference/person_d/` (mounted read-only at `/reference`) and are listed
with revision, SHA-256, size, and license in `external-assets.yaml`:

| Logical path | Asset | SHA-256 |
|---|---|---|
| `reference/person_d/checkpoint/plip/` | `vinid/plip` revision `67ade53d`: `pytorch_model.bin` and the five support files `from_pretrained` reads | `pytorch_model.bin` `98a7f8d2a1f4a8fc8f6dedb3a16ff7efbe02a7ef67c93904c80bca9767c69630`; the five support files in `external-assets.yaml` |
| `reference/person_d/checkpoint/conch/pytorch_model.bin` | `MahmoodLab/CONCH` revision `f9ca9f87` (gated, CC BY-NC-ND 4.0) | `40a9644b9ba0e83a74576e0a5e5f7313599fa9c9cdaf3c20f8a3e271b0e9ae7c` |
| `reference/person_d/template_ref/visual_attribute_prompts.json` | Vocabulary (24 attributes), option descriptions, prompts (1.1.0) | `e61b7d784aa8959305c22db7eb71921d5487ab479ebbaa16abb3c3ca957099d4` |
| `reference/person_d/template_ref/criteria_label_map.json` | Label aliases for diagnosticCriteria 1.2.1 (1.0.0) | `e1f59e667358fbca6f6bfe70cbfc140cd6c0a4ed8f6661920b5562a042f46e38` |
| `reference/person_d/template_ref/Example/ROI_Analysis/` | Few-shot example images 1.0.1 (440 files, all used by the loader, de-identified) from WHO Classification of Tumours, Breast Tumours, 5th ed. (IARC, 2019); copyrighted, internal research and testing only | tree `188b5fe0698cb2e5cbe48c24d2e4cc0923864dd76adb5d10cfe71fc81e32cbce` (algorithm in `external-assets.yaml`) |

Weights load from local files only; the image sets `HF_HUB_OFFLINE=1`.

### Obtaining the assets

Place every asset at the logical path above, so that no code or config changes, then run
`verify_assets`. The model weights are not redistributed by person_D; the few-shot images are shared
only in the project's restricted reference-asset folder:

| Asset | How to obtain | Redistribution |
|---|---|---|
| PLIP | Public Hugging Face repository; download the whole snapshot of the pinned revision (below), not only `pytorch_model.bin`. | Not redistributed: the model card declares no licence. |
| CONCH | Request access to the gated `MahmoodLab/CONCH` repository with your own Hugging Face account, accept its terms, then download the pinned revision (below). | Not redistributed: gated, CC BY-NC-ND 4.0. |
| Prompts and label map | Authored by person_D; shared in the project's restricted reference-asset folder. | Apache-2.0, like this repository. |
| Few-shot example images | Selected and cropped by person_D from the WHO Classification of Tumours, Breast Tumours, 5th ed. (IARC, 2019) illustrations of usual ductal hyperplasia, flat epithelial atypia, atypical ductal hyperplasia, ductal carcinoma in situ and invasive carcinoma, filed by attribute and option under `ROI_Analysis/<group>/<attribute>/<option>/`; shared in the project's restricted reference-asset folder. | Internal research and testing only; must not be passed on (copyrighted IARC/WHO material). |

```bash
hf download vinid/plip --revision 67ade53ddd32195868f422585f72698ef5d15094 \
  --local-dir ../reference/person_d/checkpoint/plip
hf download MahmoodLab/CONCH pytorch_model.bin --revision f9ca9f877171a28ade80228fb195ac5d79003357 \
  --local-dir ../reference/person_d/checkpoint/conch
python -m components.person_d.verify_assets --config components/person_d/configs/native.example.json
```

Log in with `hf auth login` in your own shell; never put a token in config, code, or the image.

## CLI

```bash
python -m components.person_d.visual_filter \
  --input ../run/output/work/E_rois.json \
  --input ../run/output/work/G_queries.json \
  --output ../run/output/work/H_matches.json \
  --config components/person_d/configs/native.example.json
```

## Docker

```bash
docker build --no-cache -f components/person_d/Dockerfile -t wlw/person-d:0.2.0 .

docker run --rm --gpus all \
  -v "$(pwd)/../reference:/reference:ro" \
  -v "$(pwd)/../run:/run" \
  wlw/person-d:0.2.0 \
  --input /run/input/person_d/E_rois.json \
  --input /run/input/person_d/G_queries.json \
  --output /run/output/person_d/H_matches.json \
  --config /app/components/person_d/configs/native.example.json
```

The image holds only what a run needs: `contracts/`, the Person D modules, `mapping_acceptance.json`,
`component.yaml` and `configs/`. Tests, examples and the synthetic TIFF are in the `test` target:

```bash
docker build -f components/person_d/Dockerfile --target test -t wlw/person-d:0.2.0-test .
docker run --rm --entrypoint python3 wlw/person-d:0.2.0-test \
  -m unittest discover -s components/person_d/tests -t .
```

The image sets `TORCHINDUCTOR_CACHE_DIR=/run/cache/person_d/torchinductor` so that it also runs under
a UID without a passwd entry, as `integration/compose.yaml` does. torch creates that directory empty;
apart from H, nothing else is written.

## Canonical example and tests

`examples/` holds a de-identified E/G pair, an empty-ROI E, a synthetic generic tiled TIFF, exact
expected H for `example` mode and for the native empty-ROI case, and a structure check for the native
model run (`check_native_structure.py`); see `examples/README.md` for commands and comparison.

```bash
python -m unittest discover -s components/person_d/tests -t . -v
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
```

`test_visual_filter.py` writes a temporary label map below `reference/person_d/template_ref/`, so
that directory must be writable when the tests run. The person_d tests also run in the `test` image
(Docker section). One test is skipped when CUDA is available, and the comparison of the acceptance
file with the reference assets is skipped when `reference/person_d/template_ref/` has no assets.

## Integration with person_c (#1)

Run against PR #1 at commit `0ad461d` (not merged yet). The fixture is reproducible:
`examples/person_c_integration/make_fixture.py` builds G and the synthetic slide from the E that #1
produces, and `examples/person_c_integration/README.md` has the steps, the fixture specification
(dimensions, pyramid levels, MPP, texture settings) and the SHA-256 of the outputs.

- **E**: produced by #1's own `build_region_artifact` from its canonical inputs
  (`case_list.valid.json`, `proposals.valid.json`, the test's `EXAMPLE_CONFIG`); identical to #1's
  `E_rois.expected.json` and used unchanged. Case `example-c-001`: an HE stain with 4 ROIs (level-0
  MPP 0.25; main MPP 0.5, or 2.44140625 for the 20000 × 12000 px ROI so that its longest side is
  2048 px) and an IHC stain without ROIs; `filepath` is the absolute `/example/example-he.svs`.
- **G**: generated for the same case: E's case metadata, one pair `Example_Diagnostic_Item`
  with queries 001, 004 and 005 from `examples/G_queries.valid.json`, `referenceWSI` = the HE stain.
- **WSI**: generated: a synthetic pyramidal generic tiled TIFF (30000 × 20000 px, levels 1/4/16,
  MPP 0.25) with tissue-like texture inside the four ROI boxes, mounted read-only at
  `/example/example-he.svs`.
- **Run**: image `wlw/person-d:0.2.0`, UID 1000, GPU, `configs/native.example.json`, few-shot tree
  1.0.1; about 2 min.

Results:

- Every ROI passes the `roi_wh` / MPP check and is read at exactly `main_info.roi_wh` (800 × 550,
  1500 × 1300, 2048 × 1229, 500 × 500); the large ROI is read from the 4× level in 0.84 s.
- H validates. ROI ids and order, the upstream `selection_history`, `level0_info`, `main_info` and
  `filepath` are unchanged; the IHC stain is kept with `roi_num` 0.
- 12 query-level events, each with the full `case_id + stain_id + roi_id + dx_pair_id + query_id`
  key. On all four ROIs: query 001 `skipped` (`insufficient_visual_evidence`: its 3 Must_True
  attributes are not evaluated, and 3 attributes carry Must_False options the vocabulary cannot
  reach), 004 `selected`, 005 `rejected` (`score_below_threshold`), with 5 to 9 evaluated attributes
  per ROI; all 12 follow the `score_rule` of `examples/H_matches.native.structure.json`.
- OpenSlide 3.4.1 in the image does not report an MPP for a generic TIFF; person_d uses the MPPs
  in E, so this does not affect the result.

## Failure conditions

In both modes the process exits non-zero and writes no H when: E/G `case_id`, `data_mode`, or stain
sets differ; `referenceWSI` names an unknown stain; a query's `dx_pair_id` differs from its DxItem;
`roi_id` or `query_id` repeats; a mapped query's `diagnosticCriteria` lacks `version`, `visualAttrs`,
or an attribute's `options` / `conditions`; or a ROI's metadata geometry is invalid.

In `native` mode it also fails when: a ROI lies outside the WSI or its `roi_path` crop is not exactly
`roi_wh` pixels; the prompt asset or label map is missing or differs from its configured SHA-256; a
ROI crop, WSI, weight, or example directory needed for extraction is missing; a weight, a PLIP support
file or the example tree differs from its configured digest; an example file lies outside a
`<group>/<attribute>/<option>/` image folder; an example image is unreadable; the configured CUDA
device is unavailable; `diagnosticCriteria.version` differs from the label map; or model inference
fails.

## Limitations

- The vocabulary covers all 24 diagnosticCriteria 1.2.1 attributes. The 7 added in prompt asset 1.1.0
  (`Cytoplasmic_Features`, `Mitotic_Activity`, `Tumour_Border`, `Myoepithelial_Cell_Layer`,
  `Squamous_Sebaceous_Differentiation`, `Stromal_Characteristics`, `Tumour_Infiltrating_Lymphocytes`)
  use the criteria options with option descriptions written for 1.1.0, have no few-shot images, and
  have not been validated against pathologist labels.
- This is a research component. Passing the container, model, mapping and integration tests says
  nothing about diagnostic accuracy, and no clinical use is claimed.
- 17 criteria 1.2.1 options are not covered by the vocabulary (`MAPPING.md`). A criteria that puts
  Must_True or Must_False on one of them cannot be `selected`. The Invasive Carcinoma criteria of the
  canonical example do so with four Must_False options (`Pattern` `Absent, No special pattern` and
  `Simple Tubular/Branching Structures`, `Epithelial_Cell_Shape` `Bilayered`, `Endoluminal_Secretion`
  `Physiological`), so those queries are `skipped` or `rejected`, never `selected`. CLEE (person_e)
  only takes ROIs with a `selected` event, so such criteria give it no eligible ROI. Covering these
  options needs new vocabulary labels and is left to the vocabulary and criteria owners.
- A Must_True attribute is also unverified when the two models disagree on it.
- `Cuboidal/Columnar` is ambiguous when `Cuboidal` and `Columnar` carry different conditions;
  `Pattern` `one to several layers` has no criteria option under `Pattern` and is unmapped.
- 49 of the 105 vocabulary options have no example images and receive no prototype score: 14 options
  of the original 17 attributes and all 35 options of the 7 added attributes.
- GPU floating-point differences can change scores near ties and therefore near-tie predictions.
- Unsupported inputs: slide formats that OpenSlide 3.4.1 cannot open, `roi_path` crops that Pillow
  cannot read, and non-brightfield content (images are converted to RGB, so fluorescence or
  multiplex channels are not used). `diagnosticCriteria` versions other than the label map's
  `1.2.1` fail.
- The CONCH release does not include the CoCa `text_decoder`; it is unused because only the image
  and text encoders are called.
- The native path has been run end to end with the official PLIP and CONCH checkpoints on synthetic
  slides only (the canonical example and the person_c integration); it has not been validated on real
  slides.

## Changelog

- `0.2.0`: native PLIP + CONCH extraction and matching filter, weight SHA-256 checks, smoke config,
  native canonical example with a synthetic slide; an unverified Must_True is never `selected`
  (`unverified_must_true: skip` by default); one event per query; the same input validation for
  `example` and `native` mode (`data_mode`, linkage, ROI geometry); `roi_path` crops must be exactly
  `roi_wh`; runtime SHA-256 checks for the prompts, the label map and the few-shot tree, and
  `verify_assets`; 24-attribute vocabulary (prompt asset 1.1.0); accepted vocabulary-to-criteria
  mapping (`mapping_acceptance.json`, `MAPPING.md`) and no `selected` while a Must condition sits on
  an option the vocabulary cannot reach; SHA-256 checks for the PLIP support files; few-shot layout
  validation (few-shot tree 1.0.1); runtime image without tests and examples (`test` build target).
  `example` mode output is otherwise unchanged except for the version string.
- `0.1.0`: contract-only example stub.
