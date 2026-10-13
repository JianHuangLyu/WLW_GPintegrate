# 丁（Person D）canonical example

`visual_filter` 的單案範例：`[E] E.ROIs@2.0` + `[G] G.VisualAttributeQueries@2.0` →
`[H] H.MatchedROIs@2.0`。

| 檔案 | 內容 |
|---|---|
| `E_rois.valid.json` | case `case-001`；`case-001-he`（參考切片，指向 `synthetic_slide.tiff`）與 `case-001-er`（非參考切片）各 2 個 ROI |
| `E_rois.empty.valid.json` | 同一 case，所有 stain 皆無 ROI |
| `G_queries.valid.json` | `Histologic_Type`：真實 criteria 的 `case-001-query-001` 與合成驗收 query `case-001-query-004`（所有選項 High_Possibly_True）、`case-001-query-005`（所有選項 Low_Possibly_True）；`Microcalcification`：真實 criteria 的 `case-001-query-002` 與合成 unmapped query `case-001-query-003`；`referenceWSI` 皆為 `case-001-he` |
| `synthetic_slide.tiff` | OpenSlide generic tiled TIFF，33792 × 19968 px，mpp 0.5；只有兩個 HE ROI 範圍內有程式產生的仿 H&E 紋理，其餘為白底；SHA-256 `a1f9c031b72c67308a860e24ba3f1a6fa2a04e00564a6990322ba47e22eb3d30` |
| `H_matches.expected.json` | `example` 模式完整預期輸出（逐內容比對） |
| `H_matches.empty.expected.json` | `native` 模式、空 ROI case 的完整預期輸出；不載入模型（逐內容比對） |
| `H_matches.native.structure.json` | `native` 模式、完整 case 的預期結構 |
| `check_native_structure.py` | 依結構檔檢查 `native` 輸出 |
| `person_c_integration/` | 以丙（#1）的 E 執行丁 native 所需的 fixture 產生程式與規格 |

## 涵蓋情境

| 情境 | 位置 | canonical run 的判定 |
|---|---|---|
| selected | 兩個 HE ROI 的 `query-004` | 固定 `selected`／`visual_attributes_match` |
| rejected | 兩個 HE ROI 的 `query-005` | 固定 `rejected`／`score_below_threshold` |
| 真實 criteria（無法驗證的 Must 條件） | 兩個 HE ROI 的 `query-001`、`query-002` | 不可能 `selected`：`skipped`／`insufficient_visual_evidence` 或 `rejected`／`must_condition_failed`（實測：he-roi-001 為前者，he-roi-002 為後者） |
| 非 reference WSI（skipped） | `case-001-er` 的所有 ROI × 所有 query | 固定 `skipped`／`stain_not_in_reference_wsi`，每個 query 一筆並帶 `query_id` |
| unmapped query（skipped） | `case-001-query-003` | 固定 `skipped`／`query_unmapped` |
| 空 ROI case | `E_rois.empty.valid.json` | 逐內容比對 |

`query-004`、`query-005` 的 criteria 由 `query-001` 衍生：每個屬性的選項分別全設為 High_Possibly_True
或 Low_Possibly_True（`Unable to confirm` 設為 Not_Mentioned），沒有任何 Must_True／Must_False。只要兩個
模型在至少一個屬性上達成共識（`min_evaluated_attributes` = 1），score 就分別是 1 與 -1，結果與模型
預測的是哪個標籤無關；實測每個 HE ROI 有 5–6 個共識屬性。`query-001`、`query-002` 的真實 criteria
（Invasive Carcinoma）有 4 個 Must_False 選項是 vocabulary 無法預測的（`Pattern` 的
`Absent, No special pattern`、`Simple Tubular/Branching Structures`，`Epithelial_Cell_Shape` 的 `Bilayered`，
`Endoluminal_Secretion` 的 `Physiological`；見 `components/person_d/MAPPING.md`），這些 Must 條件無法驗證，
因此這兩個 query 不會 `selected`。各分支以假模型做的確定性覆蓋另見 `components/person_d/tests/`。

## 來源與去識別化

- E 取自丙提供的合成樣本：移除 `roiCase` schema 不允許的 `structured_report`，並將 `case-001-he`
  的 `filename`／`filepath` 改指向合成切片。
- G 取自甲提供的樣本。病理號、日期、報告原文、WSI 檔名與路徑已移除；case metadata 與 E 相同，
  `dx_pair_id`、`query_id`、`referenceWSI` 改為 `case-001` 命名。`diagnosticCriteria`、
  `candidateReference` 維持原樣；`case-001-query-003`、`case-001-query-004`、`case-001-query-005` 為合成。
- E、G `reference_versions` 的 `source_path` 原為產生者工作站的絕對路徑，改為
  `example://<source_name>`；`source_name` 與 `sha256` 維持原樣。
- 合成切片由程式產生，不含任何影像來源或 PHI。

## 執行

CLI 只接受 sibling `run/` 下的輸入；`E_rois.valid.json` 的切片路徑
`../run/input/person_d/examples/synthetic_slide.tiff` 也依此複製位置設定：

```bash
mkdir -p ../run/input/person_d/examples
cp components/person_d/examples/E_rois.valid.json \
   components/person_d/examples/E_rois.empty.valid.json \
   components/person_d/examples/G_queries.valid.json \
   components/person_d/examples/synthetic_slide.tiff \
   ../run/input/person_d/examples/

# 1. example 模式：不需外部資產
python -m components.person_d.visual_filter \
  --input ../run/input/person_d/examples/E_rois.valid.json \
  --input ../run/input/person_d/examples/G_queries.valid.json \
  --output ../run/output/person_d/examples/H_matches.json \
  --config components/person_d/configs/example.json

# 2. native 模式、空 ROI case：需 reference/person_d/template_ref 的 prompt 與 label map
python -m components.person_d.visual_filter \
  --input ../run/input/person_d/examples/E_rois.empty.valid.json \
  --input ../run/input/person_d/examples/G_queries.valid.json \
  --output ../run/output/person_d/examples/H_matches.empty.json \
  --config components/person_d/configs/native.example.json

# 3. native 模式、完整 case：需 PLIP、CONCH 與 Example 範例圖
#    尚無 CONCH 授權時改用 configs/native.smoke.json（隨機權重，只驗證流程）
python -m components.person_d.visual_filter \
  --input ../run/input/person_d/examples/E_rois.valid.json \
  --input ../run/input/person_d/examples/G_queries.valid.json \
  --output ../run/output/person_d/examples/H_matches.native.json \
  --config components/person_d/configs/native.example.json
```

`contracts/paths.py` 只允許 `components/person_x/configs/` 下的 config，因此範例直接使用
`configs/` 內的設定，不另放 `config.example.json`。Docker 執行方式見 `components/person_d/README.md`。

## 比對

```bash
compare() { python -c "import json, sys; a, b = (json.load(open(p, encoding='utf-8')) for p in sys.argv[1:]); sys.exit(a != b)" "$1" "$2" && echo "match: $2"; }
compare components/person_d/examples/H_matches.expected.json ../run/output/person_d/examples/H_matches.json
compare components/person_d/examples/H_matches.empty.expected.json ../run/output/person_d/examples/H_matches.empty.json
python components/person_d/examples/check_native_structure.py \
  components/person_d/examples/H_matches.native.structure.json \
  ../run/output/person_d/examples/H_matches.native.json
```

- 1、2 以 JSON 內容逐一比對；2 的 `reference_versions` 含 prompt 與 label map 的 SHA-256，
  更新 `template_ref` 資產後需重新產生。
- 3 的模型相似度分數取決於模型與 GPU 浮點誤差，不與固定輸出逐值比對：ROI 與 event 的順序、`roi_id`、
  `dx_pair_id`、`query_id` 必須完全相同；結構檔中列 `status` 的 event（非 reference WSI、unmapped、
  `query-004`、`query-005`）必須完全相同，列 `status_in`／`reason_in` 的 event（`query-001`、`query-002`）
  須落在允許值內。
- 3 的 score 容許誤差與最終狀態判定定義於 `H_matches.native.structure.json` 的 `score_rule`
  （與 `configs/native.example.json` 的 `matching` 相同），套用於所有經過 matching 的 event：由
  `visualAttrs_info.matching.<query_id>` 的逐屬性判定重算 score，與 event `score` 差距須 ≤
  `score_tolerance`（1e-6，score 取到小數 6 位）；status／reason 依序須符合：evaluated 屬性數 <
  `min_evaluated_attributes` → `skipped`／`insufficient_visual_evidence`；Must_False 命中或已評估的
  Must_True 未滿足 → `rejected`／`must_condition_failed`；有未驗證的 Must 條件（Must_True 屬性未被評估，
  或 Must_True／Must_False 落在 vocabulary 無法預測的選項）→ `skipped`／`insufficient_visual_evidence`；
  score < `score_threshold` → `rejected`／`score_below_threshold`；其餘 →
  `selected`／`visual_attributes_match`。各選項的模型相似度分數不比對；同一張 GPU 上 Windows 與 Linux
  容器的實測差距 ≤ 1e-6。
