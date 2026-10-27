# Person C configuration

`default.json` runs the MRCPS extractor. `model.path` must resolve below sibling
`reference/person_c/checkpoint/`; `roi_output_dir` must resolve below sibling `run/`. Do not create
run-specific configs outside this directory.

| Key | Type / range | Meaning |
|---|---|---|
| `component_version` | nonempty string | Producer recorded in E and each selection event. |
| `backend` | `mrcps` or `demo` | `mrcps` opens selected WSI and runs inference. `demo` uses fixed fixture boxes. |
| `stain_type_whitelist` | nonempty list[string] | Case-insensitive stain types allowed to open and process; default is `["HE"]`. |
| `model.path` | nonempty path | Read-only MRCPS checkpoint. Required in `mrcps` mode. |
| `model.revision` | `sha256:<64 hex>` | Optional runtime checksum check; the default pins the approved checkpoint. |
| `device` | `auto`, `cpu`, `cuda` | `auto` uses CUDA when available. Explicit `cuda` fails if unavailable. |
| `patch_size` | positive integer | MRCPS input width and height in read-level pixels; trained value is 512. |
| `stride` | positive integer, at most `patch_size` | Patch grid spacing; trained value is 512. |
| `low_resolution_ratio` | positive integer | Low-resolution context ratio; trained value is 8. |
| `batch_size` | positive integer | Number of patches per model forward pass. Reduce after CUDA OOM. |
| `check_mpp` | positive number | Approximate MPP for tissue background screening. |
| `postprocess_mpp` | positive number | MPP of the stitched mask and morphology. |
| `background_lower`, `background_upper` | integers with `0 <= lower < upper <= 255` | Mean-RGB window used for tissue screening. |
| `background_dilation_kernel` | positive integer | Square grid dilation kernel for background screening. |
| `hole_area_threshold` | nonnegative integer | Fill smaller holes in the stitched mask. |
| `min_object_size` | positive integer | Remove smaller connected tissue objects. |
| `save_roi_png` | boolean | Whether to write PNG crops and set `main_info.roi_path`. |
| `roi_output_dir` | path below sibling `run` | PNG directory when `save_roi_png=true`. |

The legacy area-to-working-MPP ladder is 0.25, 0.5, 1, 2, 4, 8 and 16 µm/pixel for level-0 ROI areas up to 1, 4, 16, 64, 256, 1024 and over 1024 million pixels² respectively. Input and model revisions, resolved config, and WSI references should be snapshotted with each experiment. `demo` output is only a compatibility fixture and does not locate tissue.
