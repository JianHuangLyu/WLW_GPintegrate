# 丙 → 丁 integration fixture

以丙（Person C）實際產生的 `E.ROIs@2.0` 執行丁的 native 流程所需的 fixture。`make_fixture.py` 只讀取 E，
產生同一 case 的 G fixture 與合成切片；不需提交大型切片。

## 步驟

以下以 PR #1（commit `0ad461d`）的 canonical example 為例，在 repository 根目錄執行。

1. 由丙的程式產生 E（在 #1 的 checkout 內，與其 `CanonicalExampleTests` 相同的呼叫），寫到本 repository 同層的
   `run/input/person_d/integration_c/E_rois.json`：

   ```python
   import json
   from pathlib import Path
   from components.person_c.interest_pattern import build_region_artifact
   from components.person_c.tests.test_interest_pattern import EXAMPLE_CONFIG, EXAMPLE_SLIDE

   examples = Path("components/person_c/examples")
   source = json.loads((examples / "case_list.valid.json").read_text(encoding="utf-8"))
   features = json.loads((examples / "proposals.valid.json").read_text(encoding="utf-8"))
   e = build_region_artifact(source, EXAMPLE_CONFIG,
                             propose=lambda path, region: features["features"],
                             slide_info=lambda path: EXAMPLE_SLIDE)
   Path("../run/input/person_d/integration_c/E_rois.json").write_text(
       json.dumps(e, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
   ```

2. 產生 G 與合成切片（需要 `numpy`、`tifffile`，不是元件的 runtime dependency）：

   ```bash
   python components/person_d/examples/person_c_integration/make_fixture.py \
     --e ../run/input/person_d/integration_c/E_rois.json \
     --out-dir ../run/input/person_d/integration_c
   ```

3. 執行丁，把合成切片掛到 E 記載的 `filepath`：

   ```bash
   docker run --rm --gpus all \
     -v "$(pwd)/../reference:/reference:ro" \
     -v "$(pwd)/../run:/run" \
     -v "$(pwd)/../run/input/person_d/integration_c/example-he.tiff:/example/example-he.svs:ro" \
     wlw/person-d:0.2.0 \
     --input /run/input/person_d/integration_c/E_rois.json \
     --input /run/input/person_d/integration_c/G_queries.json \
     --output /run/output/person_d/integration_c/H_matches.json \
     --config /app/components/person_d/configs/native.example.json
   ```

## Fixture 規格

| 項目 | 值 |
|---|---|
| Slide dimensions | 30000 × 20000 px（level 0；`--width`、`--height`） |
| Pyramid levels | 3 層：downsample 1、4、16（30000 × 20000、7500 × 5000、1875 × 1250）；level 0 tile 512 px，其餘 256 px；縮圖層為 4 × 4、16 × 16 平均並標記 `NewSubfileType=1`（OpenSlide 4 需要） |
| MPP | 0.25（level 0；TIFF resolution 40000 px/cm；`--mpp`） |
| 格式 | OpenSlide generic tiled TIFF（BigTIFF、RGB、zlib） |
| Texture | 只有 E 的 ROI `level0_info.xywh` 範圍內有內容，其餘為 RGB 245 底色。每個 512 px tile：stroma 底色 `(232, 168, 196)` 加上以 32 px 為一格（每 tile 16 × 16 格）、標準差 8 的 Gaussian 雜訊；隨機橢圓形 nuclei `(92, 58, 150)`。依 ROI 順序循環使用（每 tile 的 nuclei 數、半徑範圍 px、長短軸不規則度）：`(110, 7–13, 0.45)`、`(25, 3–5, 0.05)`、`(60, 5–9, 0.25)`、`(90, 6–11, 0.35)` |
| 亂數 | `numpy.random.default_rng((tx * 100003 + ty) * 31 + roi_index)`，`tx`、`ty` 為 tile 座標 |
| G | E 的 case metadata；單一 diagnostic pair（E 的第一個 DxItem），query 取自 `examples/G_queries.valid.json` 的 001（真實 criteria）、004、005（合成驗收 query）；`referenceWSI` 為有 ROI 的 stain |

以 #1 的 canonical E（4 個 HE ROI：`[1000, 2000, 1601, 1100]`、`[2500, 2900, 3000, 2600]`、
`[6000, 6000, 20000, 12000]`、`[29000, 19000, 1000, 1000]`）在 Python 3.11.9、numpy 2.0.2、tifffile 2026.3.3、
imagecodecs 2026.3.6（Windows 11）產生的 artifact：

| Artifact | SHA-256 |
|---|---|
| `example-he.tiff`（17,035,678 bytes） | `6913e229ac87c6ddcef69f444f4b6cc8edf27a182e8b4294fb79a263e02cb204` |
| level-0 RGB 像素（row-major，8-bit） | `7c09e28df70fdbf8fe982f6f64b0880ca135f84a6c85796cb2050cd87b1f86a7` |
| `G_queries.json` | `2f0ad44823c3042e4c02a981b4036f1794f7c17b02191507970247d2af15d3cf` |

`make_fixture.py` 會印出這三個值。檔案 SHA-256 取決於 zlib 與 tifffile 的版本；像素 SHA-256 只取決於 numpy 的
亂數與浮點運算，兩者在其他版本下都可能不同。驗收不依賴逐位元組相同的切片：下列預期結果對任何依上述規格
產生的切片都成立。

## 預期結果

- 4 個 ROI 都通過 `roi_wh`／MPP 檢查，讀出的影像尺寸等於 `main_info.roi_wh`
  （800 × 550、1500 × 1300、2048 × 1229、500 × 500）。
- H 通過 schema；`roi_id` 與順序、上游 `selection_history`、`level0_info`、`main_info`、`filepath` 不變；
  沒有 ROI 的 IHC stain 保留（`roi_num` 0）。
- 12 筆 query-level event（4 ROI × 3 query），每筆都有 `dx_pair_id`、`query_id`、`criteria_status`。
- query 004 為 `selected`／`visual_attributes_match`，query 005 為 `rejected`／`score_below_threshold`；
  query 001（真實 criteria）不會是 `selected`。所有經過 matching 的 event 符合
  `examples/H_matches.native.structure.json` 的 `score_rule`。

實測結果記錄在 `components/person_d/README.md` 的 "Integration with person_c (#1)"。
