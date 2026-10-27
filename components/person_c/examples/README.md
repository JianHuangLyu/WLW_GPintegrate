# Person C example command

為遵守 runtime I/O 只放 sibling `run` 的規則，本目錄不再保存 input/output JSON 或第二份 config。
`command.txt` 直接讀取單案 CaseList fixture，並將結果寫入 `run/output/work`。真實 inference
使用 `configs/default.json`。
