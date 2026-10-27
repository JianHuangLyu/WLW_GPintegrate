# Report Decompose canonical example

All content is synthetic. `case_list.valid.json` is a single-case
`CaseListInput@1.0`; `D_dx_pairs.expected.json` is the deterministic output of
`components/person_a/configs/example.json`. `case_list.invalid.json`
demonstrates fail-fast input validation and must exit non-zero without writing
a partial D artifact.

From the repository root, copy the runtime input below `../run/` and invoke the
real CLI boundary:

```bash
mkdir -p ../run/input/person_a_example ../run/output/person_a_example
cp components/person_a/examples/report_decompose/case_list.valid.json \
  ../run/input/person_a_example/case_list.valid.json
python -m components.person_a.report_decompose \
  --input ../run/input/person_a_example/case_list.valid.json \
  --output ../run/output/person_a_example/D_dx_pairs.json \
  --config components/person_a/configs/example.json
```

`D_dx_pairs.json` must exactly match `D_dx_pairs.expected.json`. The canonical
subprocess check is also covered by `components/person_a/tests/test_examples.py`.
