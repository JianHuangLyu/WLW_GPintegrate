# Local model delivery acceptance inputs

All three inputs are synthetic. There are no patient reports or real WSI files;
the stain path is metadata only and is never opened by these entrypoints.

- `case_list.valid.json`: CGMH case with free-form text that invokes MedGemma.
- `D_dx_pairs.valid.json`: mapped ADH diagnosis for real Gemma inference.
- `F_chunks.valid.json`: three ranked synthetic chunks for contract checks.

From the repository root, Windows PowerShell users can run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File components/person_a/validate_local_delivery.ps1 -PrepareModels
```

The script makes a clean image build, runs Linux unit/CLI tests against an
isolated copy of the six Person A assets plus two small Person E fixture
JSONs required by the repository-wide tests, then runs both real model entrypoints
with `--network none` and `/reference:ro`. It checks schemas and verified model
provenance and writes logs and `acceptance-summary.json` below sibling `run/`.
`-PrepareModels` downloads missing declared files using the existing authorized
`HF_TOKEN` in `integration/.env`. Only preparation containers receive that file,
network access and a writable reference mount. Omit the switch to require
already prepared models. No token file is loaded by inference.
For actual model execution the script builds a smoke F from three ADH chunks
in the mounted, SHA-verified reference vocabulary. That restricted text stays
under `run/`, never in Git or the image. Its retrieval metadata is explicitly
synthetic, with whitespace token counts; this smoke test does not measure
retrieval quality or model generalization. Generic public F text is not used
to claim model inference success.
Gemma uses the explicit `query_generation.single_device.json` profile, requiring
enough free VRAM for the whole model. The existing CPU-offload profile remains
available for other hardware. `-SkipBuild` explicitly reuses an existing image;
such a run does not establish a clean build result.
