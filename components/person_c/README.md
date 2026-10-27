# Person C: WSI interest pattern extraction

This component reads one raw CaseList case and writes `E.ROIs@2.0`.
`stain_type_whitelist` controls which WSI types are opened; the default is `HE`.
Other stains remain present with empty ROI lists.

The MRCPS checkpoint is stored at sibling
`reference/person_c/checkpoint/central_breast_inference.pt`; its path and SHA-256 are owned only by
`configs/default.json`. Runtime artifacts and optional PNG crops stay below sibling `run/`.
The only external runtime path is each WSI `stains[].filepath` supplied by CaseList metadata.

```bash
python -m components.person_c.interest_pattern \
  --input ../run/input/pipeline/case-001.json \
  --output ../run/output/work/E_rois.json \
  --config components/person_c/configs/default.json
```

`save_roi_png=true` writes RGB crops to the config's `roi_output_dir`, which is constrained to
`run/output`. Otherwise downstream components reopen the authoritative WSI path and use
`level0_info.xywh`.

Coordinates use an upper-left origin and half-open rectangles. `level0_info.xywh` is authoritative
at level 0; `main_info` describes the virtual working-MPP image. See
[configs/README.md](configs/README.md) for parameters.

`configs/demo.json` is a path-free fixture backend for the local pipeline and does not perform WSI
inference. Invalid CaseList input, missing WSI, unreadable MPP, missing/wrong checkpoint, and model
errors fail without writing E.

```bash
python -m unittest discover -s components/person_c/tests -v
```
