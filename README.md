# WLW contract-first 整合與交付框架

本專案以版本化 JSON Schema、統一 CLI 與獨立容器串接 WLW 批次 DAG。每位成員只需維護自己的
元件與外部資產；其他元件只依賴輸入／輸出 contract、程序 exit code 與檔案路徑，不直接 import
別人的研究實作。

目前 `person_a` 為 0.9.0 正式 Report Decompose／Query Generation 實作，保留獨立的合成範例模式；
正式模型與參考資產另放 sibling `reference/person_a/`，不進 Git 或 image。兩個模型的可信固定 manifest
已提供；模型本體須另以授權方式準備，詳見 `components/person_a/LOCAL_MODELS.md`。`person_b`～`person_d` 仍為
contract／pipeline 範例 stub；`person_e` 保留 CLEE 整合實作。stub 輸出只可用於介面測試，不得用於研究、
診斷、效能評估或 benchmark。

## 1. 框架與資料流

<div align="center">
  <img src="https://github.com/yasaisen/WLW_GPintegrate/blob/main/doc/WLW_arch_v3.png" alt="inference" width="700">
</div>

| 人員 | 元件入口 | 輸入 | 輸出 |
|---|---|---|---|
| 乙 `person_b` | `prepare_literature` | 外部文獻來源或合成範例 | `[A]` |
| 甲 `person_a` | `report_decompose` | `CaseListInput@1.0` | `[D]` |
| 乙 `person_b` | `knowledge_retrieval` | `[A] + [D]` | `[F]` |
| 甲 `person_a` | `query_generation` | `[D] + [F]` | `[G]` |
| 丙 `person_c` | `interest_pattern` | `CaseListInput@1.0` | `[E]` |
| 丁 `person_d` | `visual_filter` | `[E] + [G]` | `[H]` |
| 戊 `person_e` | `clee` | `[D] + [H]` | `[I]` |

```text
CaseList ──> 甲/report_decompose ──> D ──> 乙/knowledge_retrieval ──> F
    │                                  └──────────────────────────────> 甲/query_generation ──> G
    └──────> 丙/interest_pattern ──> E
                                      E + G ──> 丁/visual_filter ──> H
                                      D + H ──> 戊/clee ──────────> I
```

`pipeline/run_pipeline.py` 負責 multi-case fan-out；每份 D/E/G/H/I artifact 只承載一個 case。
`integration/compose.yaml` 保留單案靜態 DAG，供容器整合測試使用。

## 2. Input／output contract

所有正式輸入與輸出以 `contracts/schemas/` 為唯一準則。README、範例輸出或 Python 型別若與 schema
不一致，以 schema 為準；不得在未升版的情況下自行增刪欄位或改變語意。

| 圖中代號 | Canonical contract | Schema |
|---|---|---|
| `[A]` | `A.Literature@2.0` | `A_literature.schema.json` |
| `[B]` | `B.ReportTables@1.0` | `B_report_tables.schema.json` |
| `[C]` | 目前沒有獨立 canonical artifact | 不得自行建立；需要時先提出 contract change request |
| `[D]` | `D.DxPairs@2.0` | `D_dx_pairs.schema.json` |
| `[E]` | `E.ROIs@2.0` | `E_rois.schema.json` |
| `[F]` | `F.Chunks@2.0` | `F_chunks.schema.json` |
| `[G]` | `G.VisualAttributeQueries@2.0` | `G_visual_attribute_queries.schema.json` |
| `[H]` | `H.MatchedROIs@2.0` | `H_matched_rois.schema.json` |
| `[I]` | `I.CLEESelectedROIs@2.0` | `I_clee_selected_rois.schema.json` |

框架另定義 `CaseListInput@1.0`，供 outer runner 將一批 case 拆成單案執行。`[B]` 是表格來源
manifest；目前主 pipeline 的元件邊界從已正規化的 CaseList 開始，不應把院端表格解析偷偷放回其他元件。

交付元件至少必須做到：

1. 讀取輸入後先驗證 contract 與 schema version。
2. 多輸入元件確認所有 artifact 的 `case_id` 一致。
3. 寫檔前再次驗證輸出；失敗時回傳非零 exit code，不留下半套 artifact。
4. 不把影像或大型 binary 以 base64 塞進 JSON；使用 schema 定義的路徑與 metadata。
5. contract 需要變更時，先提交變更提案、schema、canonical example 與上下游影響，不可直接改 producer。

## 3. 專案、reference 與 run 的同層結構

`reference/` 與 `run/` 必須和專案目錄位於同一層。`contracts/paths.py` 會檢查這些邊界：

```text
lab_20/
├── WLW_GPintegrate/                 # 程式碼、schema、Dockerfile、測試與非敏感 config
│   ├── components/
│   │   ├── person_a/
│   │   ├── person_b/
│   │   ├── person_c/
│   │   ├── person_d/
│   │   └── person_e/
│   ├── contracts/
│   ├── integration/
│   ├── pipeline/
│   └── tests/
├── reference/                       # 外部參考檔，runtime 原則上唯讀
│   ├── person_a/
│   │   ├── checkpoint/
│   │   └── template_ref/
│   ├── person_b/
│   │   ├── checkpoint/
│   │   └── template_ref/
│   ├── person_c/
│   │   ├── checkpoint/
│   │   └── template_ref/
│   ├── person_d/
│   │   ├── checkpoint/
│   │   └── template_ref/
│   └── person_e/
│       ├── checkpoint/
│       └── template_ref/
└── run/                             # 輸入、輸出、暫存與 log；可重建，不納入程式提交
    ├── input/
    │   └── pipeline/
    ├── output/
    │   ├── pipeline/
    │   │   └── cases/<case_id>/
    │   ├── materialized/
    │   └── work/
    ├── cache/
    └── logs/
```

路徑原則：

- 程式與可版本化、非敏感的 example config 放在 `WLW_GPintegrate/components/person_x/`。
- 模型、checkpoint、corpus、index、template reference 等外部資產放在 `reference/person_x/`。
- pipeline 輸入、輸出、暫存影像、cache 與 log 放在 `run/`。
- config 內建議使用 `../reference/person_x/...` 或 `../run/...`，不可依賴開發者家目錄的絕對路徑。
- WSI 的 `stains[].filepath` 可由資料來源提供外部絕對路徑；除此之外的 runtime 產物不得逃出 `run/`。
- 容器中以唯讀 `/reference` 與可寫 `/run` mount 對應上述目錄，不把外部資產 `COPY` 進 image。

## 4. 打包準備：四類內容必須分離

| 類別 | 放置位置 | 交付要求 |
|---|---|---|
| 執行環境 | `Dockerfile`、`requirements.txt` | Python／CUDA／系統套件與版本固定，可由 clean machine 重建 |
| 超參數與路徑 | `components/person_x/configs/` | 不硬編碼於程式；提供去敏感的 example config 與欄位說明 |
| 程式 | `components/person_x/*.py` | 只實作本人的 contract 邊界，不 import 其他人的私有實作 |
| 外部參考檔案 | sibling `reference/person_x/` | 不進 Git、不進 image；另附名稱、版本、SHA-256、授權與 mount 路徑 |

密碼、token、私有 registry credential 不得寫入 config、程式或 image layer；部署時使用環境變數或 secret
機制。component version、image tag、artifact `producer` 與 README 所列版本必須可互相對應。

## 5. Unified CLI

容器對外統一成以下介面：

```bash
component \
  --input /input/input.json \
  --output /output/output.json \
  --config /config/config.yaml
```

多輸入元件重複使用 `--input`，不得依參數順序猜測 contract：

```bash
component \
  --input /input/D_dx_pairs.json \
  --input /input/F_chunks.json \
  --output /output/G_queries.json \
  --config /config/config.yaml
```

本專案目前以 Python module 作為 `component` entrypoint，且 shared runtime 讀取 JSON config：

```bash
python -m components.person_a.query_generation \
  --input ../run/output/work/D_dx_pairs.json \
  --input ../run/output/work/F_chunks.json \
  --output ../run/output/work/G_queries.json \
  --config components/person_a/configs/example.json
```

若元件採 YAML，必須自行提供 loader、schema 與 canonical config；不得只更換副檔名。CLI 必須可在
非互動模式執行、將診斷訊息送至 stdout/stderr，成功回傳 `0`，錯誤回傳非零值。

## 6. Dockerfile 與 requirements.txt

每位成員維護自己的 Dockerfile 與依賴，不共用開發機上的 Conda environment。交付前至少在沒有
本機 site-packages、沒有未宣告檔案的 clean machine 或 clean CI runner 執行：

```bash
docker build --no-cache \
  -f components/person_x/Dockerfile \
  -t wlw/person-x:<component-version> .
```

接著以唯讀 reference、可寫 run 執行 canonical example：

```bash
docker run --rm \
  -v "$(pwd)/../reference:/reference:ro" \
  -v "$(pwd)/../run:/run" \
  wlw/person-x:<component-version> \
  --input /run/input/example/input.json \
  --output /run/output/example/output.json \
  --config /app/components/person_x/configs/example.json
```

要求如下：

- Python 套件固定可重建版本；git dependency 固定 commit，不使用浮動 branch。
- CUDA image、PyTorch 與 driver 相容性要寫入 component README。
- `requirements.txt` 只列直接 runtime dependency；開發／測試依賴另行區分。
- build 不得依賴工作站上未提交檔案，也不得把 `reference/`、`run/`、credential 或病人資料包進 image。
- README 必須記錄 CPU fallback 是否支援、GPU 數量、最低 VRAM、預估 RAM／timeout 與實測環境。

## 7. Canonical example

每個 executable 至少交付一組：

```text
components/person_x/examples/
├── input.valid.json                 # 每種必要 input contract 各一份
├── expected_output.json             # 完整且通過 schema 的預期輸出
├── config.example.json              # 無 credential、無機器限定絕對路徑
└── README.md                        # 精確執行命令與比對方式
```

多輸入元件應以 contract 命名，例如 `D_dx_pairs.valid.json`、`F_chunks.valid.json`。範例必須小、可合法
再散布、不含 PHI；大型 WSI 或 checkpoint 不得提交，可使用合成 fixture 或在 `external-assets.yaml`
列出另行取得方式。若模型含非決定性，應定義結構與容許誤差，不可提交只在某張 GPU 偶然得到的輸出。

根目錄另提供整合用合成 fixture：

```bash
mkdir -p ../run/input/pipeline
cp integration/fixtures/input/cases.example.json ../run/input/pipeline/cases.json
python3 pipeline/run_prepare_literature.py
python3 pipeline/run_pipeline.py
```

## 8. README 與版本資訊

每位成員的 `components/person_x/README.md` 至少要列出：

1. 元件用途、owner、component version、支援的 input/output contract 與 schema version。
2. 模型名稱與 revision；沒有模型也要明示。
3. Python、OS、CUDA、主要 framework 版本。
4. GPU 是否必要、GPU 數量、最低 VRAM、CPU fallback 與預估 RAM。
5. checkpoint／template／corpus／index 的 logical path、版本與 SHA-256；不得寫 credential。
6. Unified CLI、Docker build/run、canonical example、測試命令。
7. 限制、失敗條件、已知非決定性與不支援的資料型態。
8. 變更紀錄或 release tag，以及和 `component.yaml`、image tag 的對應。

`PREPARATION.md` 是交付檢查表；README 是使用者操作與 runtime 規格。兩者不得用尚未驗證的數值宣稱
支援某張 GPU、某個資料集或某項效能。

## 9. 提交內容與流程

每位成員提交前應整理成：

```text
components/person_x/
├── __init__.py
├── <entrypoint>.py
├── component.yaml
├── Dockerfile
├── requirements.txt
├── README.md
├── PREPARATION.md
├── configs/
│   ├── README.md
│   └── *.example.json
├── examples/
├── tests/
└── external-assets.yaml             # 有外部資產時必須提供
```

提交步驟：

1. 先以 canonical examples 驗證本人元件，再執行根目錄 contract 與 pipeline tests。
2. 提交 source、非敏感 config、Dockerfile、requirements、examples、tests、README 與 manifest。
3. 外部資產另行放置於 `reference/person_x/`；提交 `external-assets.yaml`，但不提交資產本體。
4. 不提交 `run/`、模型、cache、log、暫存 crop、`.pyc`、`__pycache__` 或 credential。
5. 提供 component version、Git revision、image tag、資產 SHA-256、測試結果與尚未完成的限制。
6. 若 contract 不變，其他元件與 orchestrator 不應需要修改；若需要修改，必須一併提出介面變更理由。

## 10. 專案驗證

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
docker compose -f integration/compose.yaml config --quiet
```

各人的詳細交付要求：

- [甲：Report Decompose／Query Generation](components/person_a/PREPARATION.md)
- [乙：Literature Preparation／Knowledge Retrieval](components/person_b/PREPARATION.md)
- [丙：Interest Pattern／ROI Extraction](components/person_c/PREPARATION.md)
- [丁：Visual Attribute Filter](components/person_d/PREPARATION.md)
- [戊：CLEE Evidence Selection](components/person_e/PREPARATION.md)
