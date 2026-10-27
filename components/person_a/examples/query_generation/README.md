# Query Generation canonical example

All content is synthetic. The D and F inputs have the same `case_id` and the
expected G preserves D while adding an empty `visualAttrQueries` list. This is
the deterministic `example` backend; production reference and learnable
backends use mounted assets declared in `external-assets.yaml`.

From the repository root:

```bash
mkdir -p ../run/input/person_a_example ../run/output/person_a_example
cp components/person_a/examples/query_generation/D_dx_pairs.valid.json \
  ../run/input/person_a_example/D_dx_pairs.valid.json
cp components/person_a/examples/query_generation/F_chunks.valid.json \
  ../run/input/person_a_example/F_chunks.valid.json
python -m components.person_a.query_generation \
  --input ../run/input/person_a_example/D_dx_pairs.valid.json \
  --input ../run/input/person_a_example/F_chunks.valid.json \
  --output ../run/output/person_a_example/G_queries.json \
  --config components/person_a/configs/example.json
```

Input order is contract-based; swapping the two `--input` arguments produces
the same output. `G_queries.json` must exactly match `G_queries.expected.json`.
