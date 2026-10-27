# Person C delivery report

- Date: 2026-09-22
- Component: `person-c/interest-pattern:0.4.0`
- Contracts: `D.DxPairs@2.0` → `E.ROIs@2.0`
- Kit version: no separate Component Kit or `KIT_MANIFEST.json` was supplied; implementation uses the current `dark-wlw-gp` contract snapshot.
- Model revision: `sha256:1f8aa23202e4efda656b227efa1114cea74036f79f6dd0deba20f50bde90b12b`; weight remains outside the repository.

## Validation performed

- `MVLM_WLW` Python 3.10.12, PyTorch 2.6.0+cu118, OpenSlide Python 1.4.6; CUDA was unavailable on this host.
- `python -m unittest discover -s components/person_c/tests -v`: 5 passed, covering valid and empty E, HE-only inference, stain/reference preservation, normalized geometry, PNG switch, invalid D, missing WSI and missing checkpoint.
- `python3 -m unittest discover -s tests -v`: 14 passed, including the historical multi-case pipeline fixture.
- Real BRACS_265 WSI was opened; level-0 size 103,767 × 62,084 and MPP 0.2524 were read. The MRCPS checkpoint loaded and produced a 512 × 512 prediction on a tissue patch.
- A temporary 2048 × 2048 pyramidal TIFF crop made from that WSI was processed by the complete D→E CLI with the real checkpoint. E validated; HE produced one ROI and ER remained empty. Repeating with `save_roi_png=true` produced a 517 × 517 PNG matching `main_info.roi_wh`.
- The committed synthetic example was rerun and matched `examples/output.example.json` byte for byte.

## Remaining validation and limits

- The full BRACS_265 WSI had 21,197 background-screened candidate patches. A full CPU inference was not run; a GPU-enabled machine is needed for a practical full-slide smoke test and VRAM measurement.
- Docker daemon access was confirmed. A clean build reached the Python dependency installation step after successfully pulling the pinned Python base and installing `libopenslide0`. Dependency downloads stalled, so the build was interrupted; no container CLI smoke test is claimed. Rebuild on a machine with a working package mirror before submission acceptance.
- ROI coordinate wording needs central schema and downstream person_d agreement; see `CONTRACT_CHANGE_REQUESTS.md`.
- The historical integration config omits `backend`; its old all-stain fixed-box output remains for compatibility with central smoke tests. Explicit `demo` and real `mrcps` configs leave non-HE ROI lists empty. Demo boxes have no tissue-detection meaning.
