# Fixed local models (Person A 0.9.0)

Production reads complete, self-contained model directories from read-only
`reference/person_a/checkpoint/`. It does not reconstruct an HF cache, download
weights, or use a token at inference time.

| Model ID | Pinned revision | Model directory below `reference/person_a/checkpoint/` | Delivery |
|---|---|---|---|
| `google/gemma-3-1b-it` | `dcc83ea841ab6100d6b47a070329e1ba4cf78752` | `gemma-3-1b-it/` | Fixed seven-file manifest supplied |
| `google/medgemma-1.5-4b-it` | `91850547d9f0b2fdd21aa7c5f4f3d1a8a52c243b` | `medgemma-1.5-4b-it/` | Fixed fifteen-file manifest supplied; weights external |

The soft-prompt `.pt` remains alongside these directories. The paths above are
the canonical layout used by both production configs and `external-assets.yaml`.
Original Hub identities remain `model_name` for Gemma and `model_id` for
MedGemma, separate from `model_path`; soft-prompt model identity and optional
revision checks use those identities, never the filesystem directory name.

## Preparation (before deployment)

1. Obtain the exact pinned revision in an authorized environment under the
   model's license. A download token, when necessary, belongs only to this
   preparation step. Do not publish weights or credentials in Git or an image.
2. Materialize the complete required snapshot into the directory above. Copy
   file bytes rather than links to an HF blob store. The Gemma export contains
   `added_tokens.json`, `config.json`, `generation_config.json`,
   `model.safetensors`, `special_tokens_map.json`, `tokenizer.json`, and
   `tokenizer_config.json` (2,034,354,586 bytes total).
3. Verify against the trusted, pre-established manifest. Keep tree metadata
   in the component and model bytes outside it. Do not add download/cache
   metadata or extra files to the model directory.

The Gemma metadata originated in the handoff manifest with SHA-256
`60568de4fdcf4c2e3e294141be14d4ba1ef459e09646a2b2b97ce8019280d7bf`.
Only CRLF line endings were normalized to LF for portable Git checkouts;
`.gitattributes` fixes LF for these metadata files. The committed manifest SHA-256
is `0925391b778e16eed1025e8c8581905f4c51a62022e49337aef4dcad2056d0b0`.
Its file sizes/hashes, model ID, and revision are unchanged. No model content
was used to generate a new runtime baseline.

MedGemma expected metadata is established from the official immutable Hub API
for revision `91850547d9f0b2fdd21aa7c5f4f3d1a8a52c243b`. LFS file size/SHA-256
comes directly from that revision's official metadata; small files were fetched
from the same revision and independently checked against its Git blob IDs before
fixing their SHA-256. This is separate from scanning a deployment's current tree.
The fifteen-file manifest SHA-256 is
`9e83fdd3b9b4871002b671af08abde51994de624534c0392922c65af52ccec7f`;
total bytes are 8,639,646,105. See [MODEL_MANIFEST_SOURCES.md](MODEL_MANIFEST_SOURCES.md).

Download the complete pinned snapshot in an authorized environment, then copy
only its fifteen declared files to the external model directory (including
README/license context, tokenizer/processor files and both weight shards).
HF local download cache metadata belongs under `run/`, not in the model tree.
A download token may be needed for preparation; runtime does not use one.
Verify with the command below after materialization. Do not replace expected
metadata with hashes of arbitrary local files.

The network-enabled preparation CLI uses the shipped expected manifests and
keeps its download staging/cache under sibling `run/`:

```powershell
# Supply an authorized HF_TOKEN in the preparation process environment.
python -m components.person_a.prepare_local_models --asset gemma-query-generator
python -m components.person_a.prepare_local_models --asset medgemma-report-extractor
```

This command deliberately enables Hub access only for preparation. It never
accepts license terms, generates tokens or changes the expected manifest. It
reuses matching files, rejects changed existing/downloaded files, materializes
only the declared file bytes, and runs the production verifier at completion.
Runtime loaders never invoke it. If downloading manually, preserve the same
declared paths and run the production verification command afterwards.

## Verification without loading the model

Run from the repository root; no Transformers/GPU is required:

```bash
python -m components.person_a.local_model_integrity \
  --model-path ../reference/person_a/checkpoint/gemma-3-1b-it \
  --model-id google/gemma-3-1b-it \
  --revision dcc83ea841ab6100d6b47a070329e1ba4cf78752
```

Verification first checks the asset's declared path, source and pinned revision,
then checks the trusted manifest's SHA-256, identity, schema and safe relative
paths. It checks exact file membership, size and SHA-256 for every file.
Missing/extra/modified files, malformed/changed manifests and escapes fail
non-zero. Contained file symlinks are checked; external or broken symlinks and
directory symlinks are rejected. External junction targets are also rejected
by resolved-path containment. Manifest reads are not cached.

Both model loaders run this same check before any `from_pretrained` call, then
pass only the local directory with `local_files_only=True`. There is no model
`record_only` bypass and no online-ID fallback. Use read-only mounts so model
files cannot change between verification and loading.

## Docker and provenance

The existing commands in the two operation guides use `/reference:ro`,
`--network none`, and no token file. Docker additionally sets
`HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`; framework caches, if any, remain
under `/run`, outside the image and model tree.

Successful model use records `model_id`, `model_revision`, logical `model_path`,
manifest name/SHA-256, canonical `tree_sha256`, file count/total bytes,
`integrity_verified: true`, and `local_files_only: true` in:

- D: `payload.reference_versions.medgemma_report_extraction`.
- G: `payload.reference_versions.learnable_query_generation.model_integrity`.

Model-free routes do not claim model verification. Failure does not produce
a partial D/G. The D/G schema, ranking policy and inference algorithm are
unchanged.

## Regression tests

```bash
python -m unittest discover -s tests -v
python -m unittest discover -s components/person_a/tests -v
docker compose -f integration/compose.yaml config --quiet
```

Synthetic tests cover relocated local directories, missing/extra files, size
and same-size digest tampering, revision/identity mismatch, trusted manifest
mismatch, unsafe paths, symlink escape, same-process manifest refresh,
token-free local-only loaders and retained soft-prompt compatibility checks.
Symlink creation tests skip explicitly on Windows accounts lacking the OS
privilege; run them on Linux for complete coverage. Mock tests do not establish
real model inference; report real GPU/offline checks separately.

## Reproducible acceptance

From the repository root in an ordinary user PowerShell with Docker access:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File components/person_a/validate_local_delivery.ps1 -PrepareModels
```

With `-PrepareModels`, the script prepares missing pinned model files using the
existing authorized `HF_TOKEN` in `integration/.env`. Only those preparation
containers have network access and a writable reference mount; the token is
never passed to inference. Omit the switch when models are already prepared.

The script makes a clean image build, executes root and canonical CLI tests in
Linux against an isolated writable copy of the six Person A assets and the two
small Person E fixture JSONs required by the full repository suite, then invokes
real MedGemma and Gemma using `/reference:ro`, `--network none`, and no token
file. It checks schema-valid D/G and verified model provenance. Logs, outputs
and `acceptance-summary.json` go under sibling `run/output/`. Failure is non-zero
and is recorded as failed, including missing Docker permission or missing assets.

The model smoke test uses a synthetic case and three ADH chunks from the mounted,
SHA-verified reference vocabulary. Restricted source text is written only to
`run/`; it is never committed. F uses explicitly synthetic retrieval metadata and
whitespace token counts. This establishes model execution, not retrieval quality
or generalization accuracy. Public generic F fixtures are for contract checks;
model-generated malformed JSON is rejected rather than repaired.
