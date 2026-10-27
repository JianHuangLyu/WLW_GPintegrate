# Provenance of fixed model manifests

These files contain integrity metadata only. Weights, tokenizer bytes,
research reference content, credentials and patient data are not included.

## Gemma 3 1B

- Model: `google/gemma-3-1b-it`.
- Revision: `dcc83ea841ab6100d6b47a070329e1ba4cf78752`.
- Source: existing handoff export of the exact pinned seven-file snapshot,
  with independently recorded manifest SHA-256
  `60568de4fdcf4c2e3e294141be14d4ba1ef459e09646a2b2b97ce8019280d7bf`.
- The source hash was checked before copying metadata. Only CRLF-to-LF
  normalization changed; file entries, sizes and hashes were preserved.
- Versioned manifest SHA-256:
  `0925391b778e16eed1025e8c8581905f4c51a62022e49337aef4dcad2056d0b0`.
- Seven files, 2,034,354,586 bytes.

## MedGemma 1.5 4B

- Model: `google/medgemma-1.5-4b-it`.
- Revision: `91850547d9f0b2fdd21aa7c5f4f3d1a8a52c243b`.
- Source checked 2026-10-24: [official immutable revision API](https://huggingface.co/api/models/google/medgemma-1.5-4b-it/revision/91850547d9f0b2fdd21aa7c5f4f3d1a8a52c243b).
- `HfApi.model_info(..., revision=..., files_metadata=True)` returned the exact
  revision. For each LFS file, the expected size and SHA-256 came directly from
  that official revision metadata, before local weight materialization.
- Every non-LFS file was fetched from the same revision in an authorized
  preparation environment. Its bytes and length were checked against the
  official Git blob ID (`SHA1("blob " + size + NUL + contents)`), then its
  SHA-256 was fixed in the versioned manifest. Arbitrary local bytes were not
  accepted as a new baseline.
- Versioned manifest SHA-256:
  `9e83fdd3b9b4871002b671af08abde51994de624534c0392922c65af52ccec7f`.
- Fifteen files, 8,639,646,105 bytes. Both original weight shards, tokenizer and
  processor files, configuration, README and source `.gitattributes` are
  declared. HF download cache metadata is excluded from the deployed tree.

## Runtime trust boundary

`external-assets.yaml` pins the expected manifest SHA-256. `.gitattributes`
keeps versioned manifest bytes stable across checkouts. Runtime checks that
digest before parsing metadata, checks original model identity and revision,
and verifies the exact local file set, sizes and SHA-256 values before loading.
The same trusted metadata is used regardless of host filesystem paths.

Preparation and deployment are separate: possession of a manifest does not
mean the gated weights have been delivered or a model inference has passed.
Use the actual materialization check and acceptance evidence to establish those
results. Licenses and model access must be satisfied in the download environment;
runtime does not accept terms, acquire tokens, or regenerate expected manifests.
