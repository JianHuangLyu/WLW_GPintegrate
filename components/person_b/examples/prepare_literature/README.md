# Example: `prepare_literature`

Synthetic input, expected `A.Literature@2.0` output. The text is written for contract testing only;
it is not literature and may be redistributed.

| File | Role |
|---|---|
| `source.synthetic/` | input in the `rag_database@1` format: 5 disease files, each with 3 text sections and one literal `"None"` section, plus an empty `Adenomas` placeholder with no extension |
| `config.example.json` | `mode: rag_database` config |
| `A_literature.expected.json` | the exact A that the command below produces |

The source format is a directory, not the single `source.synthetic.json` file sketched in
`PREPARATION.md`: it is the format of the real corpus (one JSON per disease). Its definition is in
the docstring of `components/person_b/prepare_literature.py`.

## What the example shows

- 5 nodes and 20 sections are kept in A; the 5 literal `"None"` sections stay unchanged in A.
- `Adenomas` (no `.json` extension) is skipped.
- `images` are never copied into A.
- `source_path` is `repo://components/person_b/examples/prepare_literature/source.synthetic`, never a
  host path; `sha256` covers the file names and raw bytes of the `*.json` files. The folder carries a
  `.gitattributes` forcing LF so that the digest is the same on every platform.

## Run it

The CLI output must be below the sibling `run/` and the config below `components/person_b/configs/`,
so use the loadable copy of the config (a test checks it equals `config.example.json`):

```bash
python -m components.person_b.prepare_literature \
  --source components/person_b/examples/prepare_literature/source.synthetic \
  --output ../run/output/work/A_literature.json \
  --config components/person_b/configs/example.rag_database.json
```

The file written equals `A_literature.expected.json` (apart from line endings on Windows).
`tests/test_person_b_examples.py` checks this on every run.
