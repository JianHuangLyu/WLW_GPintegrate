# 甲（Person A）：Report Decompose／Query Generation 準備與交付

甲負責兩個獨立 executable。正式實作必須保留 module 名稱、Unified CLI、單案行為與 schema
version。共通規則見專案根目錄 `README.md`，目前實作方式見同目錄 `README.md`。

## 1. Input／output 規格

| Entrypoint | Input | Output |
|---|---|---|
| `components.person_a.report_decompose` | `CaseListInput@1.0`，且每次只含一個 case | `[D] D.DxPairs@2.0` |
| `components.person_a.query_generation` | `[D] D.DxPairs@2.0` + `[F] F.Chunks@2.0` | `[G] G.VisualAttributeQueries@2.0` |

要求：

- D 必須保留 CaseList 的 case/block/stain 身分與 `stains[].filepath`，並產生 schema 合法的
  `structured_report.DxItems`。
- G 必須保留 D 的診斷結構，將 query 寫入各 DxItem 的 `visualAttrQueries`。
- D/F/G 的 `case_id` 必須一致；不得依 `--input` 出現順序判斷 contract。
- `[B] B.ReportTables` 是上游 ingestion manifest；目前甲的 runtime 邊界從已正規化 CaseList 開始。
  若要改回直接讀表格，必須先調整中央 contract 與 pipeline，不可私下擴充 CLI。
- 不得自行建立 `[C]` artifact；目前沒有 canonical `[C]` schema。

Canonical schemas：

- `contracts/schemas/case_list_input.schema.json`
- `contracts/schemas/D_dx_pairs.schema.json`
- `contracts/schemas/F_chunks.schema.json`
- `contracts/schemas/G_visual_attribute_queries.schema.json`

## 2. 交換 JSON 結構示例

以下片段用來說明元件之間的交換層級；`<...>` 是文件省略標記，不是可直接送入 runtime 的值。
正式 canonical example 必須補齊 schema 的所有 required fields，且不得保留省略標記。

### Report Decompose input：`CaseListInput@1.0`

```json
{
  "DxItem_list": ["Histologic_Type"],
  "case_list": [
    {
      "sample_idx": 0,
      "case_id": "case-001",
      "hospital": "EXAMPLE",
      "patient_info": {},
      "date": "",
      "source": {"fixture": "synthetic"},
      "organ": "Breast",
      "report_raw_content": "<synthetic report text>",
      "tissue_blocks": [
        {
          "block_id": "A",
          "stains": [
            {
              "stain_id": "case-001-he",
              "stain_type": "HE",
              "filename": "case-001-he.svs",
              "filepath": "/data/case-001-he.svs",
              "memo": ""
            }
          ],
          "memo": ""
        }
      ],
      "memo": ""
    }
  ]
}
```

### Report Decompose output：`[D] D.DxPairs@2.0`

```json
{
  "contract": "D.DxPairs",
  "schema_version": "2.0",
  "artifact_id": "D-case-001",
  "case_id": "case-001",
  "producer": "person-a/report-decompose:<version>",
  "payload": {
    "data_mode": "inference",
    "DxItem_list": ["Histologic_Type"],
    "reference_versions": {},
    "case_list": [
      {
        "case_id": "case-001",
        "report_raw_content": "<same source report>",
        "structured_report": {
          "reportType": "<type or null>",
          "reportSubTypes": [],
          "DxItems": {
            "Histologic_Type": {
              "dx_pair_id": "case-001-dx-001",
              "source_report_id": "case-001-report",
              "DxResultCls": "<result class>",
              "DxResultTxt": "<normalized result text>",
              "DxResultRawTxt": "<source evidence or null>",
              "referenceBlock": ["A"],
              "referenceType": ["HE"],
              "referenceWSI": ["case-001-he"],
              "appear_reportTypes": ["<report type>"],
              "optionTypes": "categorical",
              "has_numericalData": false
            }
          }
        },
        "tissue_blocks": ["<metadata-shaped block/stain；roi_list initially empty>"],
        "<其餘 case metadata>": "見 metadata_case_payload.schema.json"
      }
    ]
  }
}
```

### Query Generation second input：`[F] F.Chunks@2.0`

```json
{
  "contract": "F.Chunks",
  "schema_version": "2.0",
  "artifact_id": "F-case-001",
  "case_id": "case-001",
  "producer": "person-b/knowledge-retrieval:<version>",
  "payload": {
    "corpus_id": "corpus-v1",
    "knowledge_base": {"<manifest fields>": "見 F_chunks.schema.json"},
    "chunks": [
      {
        "chunk_id": "chunk-001",
        "dx_pair_id": "case-001-dx-001",
        "literature_id": "lit-001",
        "section_id": "sec-001",
        "text": "<retrieved evidence>",
        "retrieval_rank": 1,
        "relevance_score": 0.9,
        "<其餘 provenance/score fields>": "見 F_chunks.schema.json"
      }
    ]
  }
}
```

### Query Generation output：`[G] G.VisualAttributeQueries@2.0`

```json
{
  "contract": "G.VisualAttributeQueries",
  "schema_version": "2.0",
  "artifact_id": "G-case-001",
  "case_id": "case-001",
  "producer": "person-a/query-generation:<version>",
  "payload": {
    "data_mode": "inference",
    "DxItem_list": ["Histologic_Type"],
    "case_list": [
      {
        "case_id": "case-001",
        "structured_report": {
          "DxItems": {
            "Histologic_Type": {
              "dx_pair_id": "case-001-dx-001",
              "visualAttrQueries": [
                {
                  "query_id": "query-001",
                  "dx_pair_id": "case-001-dx-001",
                  "text": "<visual attribute question>",
                  "criteria_status": "mapped",
                  "diagnosticCriteria": {"<criteria fields>": "見 metadata schema"},
                  "mapping_source": "<reference version>",
                  "chunk_ids": ["chunk-001"]
                }
              ],
              "<其餘 DxItem fields>": "沿用 D"
            }
          },
          "<其餘 structured report/case fields>": "沿用 D"
        }
      }
    ]
  }
}
```

交換時以 `case_id`、`dx_pair_id`、`chunk_id` 與 `query_id` 串接，不能依陣列位置配對。

## 3. 打包準備

```text
WLW_GPintegrate/components/person_a/       # 程式、Dockerfile、requirements、文件、非敏感 config
reference/person_a/checkpoint/             # 正式 MedGemma／Gemma 本地模型目錄與 soft prompt
reference/person_a/template_ref/           # 診斷候選、mapping、vocabulary 等外部參考
run/input/                                 # CaseList、D、F
run/output/                                # D、G、暫存與測試產物
```

- 執行環境只由 `Dockerfile` 與 `requirements.txt` 宣告。
- 超參數、feature flag 與 logical path 放在 `configs/`，不得散落於 Python 常數。
- 模型、reference table、院端資料與 credential 不得進 Git 或 image。
- 外部資產須在 `external-assets.yaml` 列出名稱、revision、SHA-256、授權與預期 mount path。
- 正式 config 使用 `asset_integrity: enforce`；路徑未宣告或 SHA-256 不符時必須停止。
- 正式模型路徑固定為 `checkpoint/gemma-3-1b-it/` 與 `checkpoint/medgemma-1.5-4b-it/`；
  來源 ID、revision、預期 mount path 與可信 tree manifest 記錄在 `external-assets.yaml`。
- 模型載入前必須核對固定 manifest 的 SHA、model ID／revision、完整檔案清單、size、SHA-256；
  symlink 或相對路徑不得逃出模型 root。manifest 每次驗證重新讀取，不沿用舊快取。
- 模型使用 `from_pretrained(model_path, local_files_only=True)`；本地推論不要求 HF token，
  也不下載或回退線上 ID。`record_only` 不會停用模型完整性驗證。
- D/G 的 `reference_versions` 保存實際模型驗證結果；沒有呼叫模型時不宣稱已驗證模型。
- MedGemma 的授權固定 snapshot 與可信 manifest 尚缺，標記 `BLOCKED_MISSING_ASSET`；
  正式 CGMH model-invoked 路徑待資產齊備另驗收。準備步驟見 `LOCAL_MODELS.md`。
- RAM 規劃 16 GB（Gemma CPU offload 可用至 12 GiB，另留 overhead），不是已驗證最低需求；
  4 GB VRAM 也不是兩個模型共同的已認證最低規格。
- runtime 只寫入 sibling `run/`；不得在 component 或 `reference/` 下產生 cache。

## 4. Unified CLI

容器介面：

```bash
component \
  --input /input/case.json \
  --output /output/D_dx_pairs.json \
  --config /config/report_decompose.yaml

component \
  --input /input/D_dx_pairs.json \
  --input /input/F_chunks.json \
  --output /output/G_queries.json \
  --config /config/query_generation.yaml
```

目前專案的 Python／JSON config 等價命令：

```bash
python -m components.person_a.report_decompose \
  --input ../run/input/pipeline/case-001.json \
  --output ../run/output/work/D_dx_pairs.json \
  --config components/person_a/configs/example.json

python -m components.person_a.query_generation \
  --input ../run/output/work/D_dx_pairs.json \
  --input ../run/output/work/F_chunks.json \
  --output ../run/output/work/G_queries.json \
  --config components/person_a/configs/example.json
```

錯誤 input、未知 schema version、case 不一致、reference 缺失或模型錯誤必須非零結束，且不可寫出
部分 D/G。

## 5. Dockerfile／requirements.txt

正式 runtime 由 `component.yaml`、Dockerfile、requirements 與 README 共同宣告 Python、NLP/LLM
framework、CPU/GPU 與 RAM/VRAM 需求。

```bash
docker build \
  -f components/person_a/Dockerfile \
  -t wlw/person-a:<version> .
```

在 clean machine 執行 D 與 G 兩個 entrypoint；不得因工作站已安裝套件或存在未宣告的 reference file
而成功。若使用 GPU，必須另驗證 CUDA image、driver、framework 與最低 VRAM。

## 6. Canonical examples

至少交付兩組：

```text
components/person_a/examples/
├── report_decompose/
│   ├── case_list.valid.json
│   ├── D_dx_pairs.expected.json
│   └── README.md
└── query_generation/
    ├── D_dx_pairs.valid.json
    ├── F_chunks.valid.json
    ├── G_queries.expected.json
    └── README.md
```

範例不得包含 PHI、院端原始報告或私有 mapping；使用合成內容並確保 expected output 可重現且通過
canonical schema。兩組範例共用合法路徑下的 `components/person_a/configs/example.json`。另至少加入一個
invalid input，並以 subprocess 執行正式 CLI，驗證元件會 non-zero fail 且不留下部分輸出。

## 7. README 必填資訊

甲的 `README.md` 必須列出 component version、D/G contract version、報告／query 模型名稱與 revision、
Python/framework 版本、GPU/VRAM 或 CPU/RAM、checkpoint/reference logical path 與 SHA-256、完整 CLI、
Docker build/run、canonical example、限制與已知失敗條件。若完全不使用模型，需明確寫「無模型」。

## 8. 提交檢查

- [ ] D、G 皆通過 schema，且 D/F/G case identity 一致。
- [ ] `component.yaml`、image tag、artifact `producer` 與 README version 一致。
- [ ] clean-machine build/run 成功，沒有隱含 Conda 或本機路徑依賴。
- [ ] source、configs、examples、tests、Dockerfile、requirements、README、PREPARATION 已提交。
- [ ] 外部資產只放 `reference/person_a/`，並附 manifest；`run/` 產物不提交。
- [ ] 根目錄 contract 與 pipeline tests 全部通過。
