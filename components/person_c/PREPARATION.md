# 丙：準備與交付

丙負責單案 `CaseList input -> E.ROIs`。輸出保留 case/block/stain/WSI metadata，並只為 config
白名單中的 WSI 加入 ROI 座標與 `interest_pattern_extraction` event；JSON 不放 pixels。

## 路徑規則

- checkpoint 只放在 sibling `reference/person_c/checkpoint/`，路徑只由
  `components/person_c/configs/default.json` 指定。
- CaseList/E 與 materialized ROI 一律放在 sibling `run/`。
- CaseList metadata 的 `stains[].filepath` 是唯一可指向外部 WSI 的路徑；C 不維護第二份 WSI root。
- `stain_type_whitelist` 預設為 `["HE"]`；非白名單 stain 保留，但不開檔且 ROI 為空。

`level0_info.xywh` 使用 level-0、左上角原點、半開 pixel rectangle；`main_info` 表示工作 MPP
座標。丁應使用相同 `filepath + level0_info` 重建 ROI。

## 驗證

```bash
python -m components.person_c.interest_pattern \
  --input ../run/input/pipeline/case-001.json \
  --output ../run/output/work/E_rois.json \
  --config components/person_c/configs/default.json

python -m unittest discover -s components/person_c/tests -v
```

缺檔、錯誤 checkpoint/hash、WSI read error 與模型錯誤必須 non-zero exit，且不得寫半套 E。
