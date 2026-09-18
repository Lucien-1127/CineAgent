# 影片任務復原與 OrcaRouter 串接

狀態：`experimental`。本輪以離線回歸測試與 HTTP 模擬契約測試驗證；尚未完成真實付費生成驗收。

## 已修正的執行行為

- 提交前保存 `submitting`；取得遠端任務編號後立即保存，再開始查詢。
- 檢查點採同目錄暫存檔、flush/fsync、原子替換。CLI 鎖定狀態檔及輸出目錄，避免同時執行兩份任務。
- 重啟後讀取原始供應商、模型、分段計畫、提示詞與畫面參數，不用預設值覆寫。
- 有遠端編號一律先查詢；查詢逾時、下載失敗不會觸發重新生成。
- 提交逾時、5xx、回應格式損毀或沒有任務編號，標記不明結果並停止。**這是避免盲目重送，不是宣稱供應商保證一次計費。**
- 已知 429 拒絕才允許有限次提交重試；不明提交須先在供應商後台核對。
- 所有分段都必須有非空本機檔案才能合片；最後檔案須可讀且符合計畫長度才標記 `STITCHED`，CLI 才回傳 0。
- 下載、合片使用暫存檔；舊 `final.mp4` 不會被當成本次成功交付。
- 分段保留「剪輯需要秒數」及「合法生成秒數」，不足模型最低長度的尾段生成合法長度再裁切。

## 執行方式

執行位置：Linux／WSL／VM 的專案虛擬環境。金鑰只放在環境變數，勿提交至 Git。

```bash
# 只規劃，不呼叫 API、不收費。
.venv/bin/python -m cineagent.cli --topic '產品動畫示意' \
  --video-provider orcarouter --model kling/kling-v3 \
  --total-duration 5 --plan-only

# 須由執行環境事先安全載入 ORCAROUTER_API_KEY；此指令會提交付費任務。
.venv/bin/python -m cineagent.cli --topic '依核准產品圖緩慢推近，保持產品輪廓與標示' \
  --video-provider orcarouter --model kling/kling-v3 \
  --image-url 'https://your-approved-host.example/product.png' \
  --total-duration 5 --aspect 16:9 --output-dir ./output/product-shot-001

# 續跑只讀取原計畫；不可加入修改模型、秒數或畫面的參數。
.venv/bin/python -m cineagent.cli --resume ./output/product-shot-001/state.json
```

預設供應商改為 `orcarouter`，預設模型 `kling/kling-v3`。官方直連 `kling`／`seedance` 仍保留為明確選項。已存在的舊狀態若沒有 `plans`，會拒絕自動續跑，需要先人工核對遠端任務並遷移。

## 首尾幀與長片

`VideoPipelineRunner(frame_publisher=...)` 可注入非同步圖片發佈函式，接收抽出的圖片檔案路徑，回傳供應商可存取的 HTTP(S) URL。本專案未替使用者選定或部署外部圖片儲存服務。

CLI 尚未接圖片發佈服務，因此真實跨段首尾幀接續會在付費提交前擋下。可明確使用 `--independent-shots` 製作獨立片段後合片；這不保證跨鏡頭角色或產品一致。每鏡不同內容應先分別製作及人工核准，不能把一個提示詞重複生成當成完整產品腳本。

離線測試的假影片、假供應商不代表真實產品成片。

## OrcaRouter 契約

依 2026-09-18 官方文件核對：

- [Kling Video](https://docs.orcarouter.ai/kling-video/overview)
- [Seedance Video](https://docs.orcarouter.ai/seedance-video/overview)

僅允許已列明的七個 Kling 模型與 `byteplus/dreamina-seedance-2-0-260128`。不把文件中尚未開放的 Seedance 模型當成可用服務。

建立任務與查詢分別使用 `POST /v1/video/generations`、`GET /v1/video/generations/{task_id}`；兩家有不同 metadata 欄位。轉接器拒絕不支援的參數，避免靜默丟棄影響畫面的要求。未驗證遠端提交冪等欄位，因此不附上捏造的防重複計費標頭。

## 仍需驗收

1. 在已設定金鑰的執行環境，完成單一 5 秒任務的提交、查詢、下載、合片、人工畫質審核與實際帳單核對。
2. 圖片託管及真實首尾幀跨段接續；網址有效期與存取權限。
3. 專案預算／計價上限尚無金額閘門；目前 CLI 限每輪計畫 60 秒，這不是金額保證。
4. 專業旁白、中文與英文雙語字幕、產品資訊人工核准，尚未接入此影片 CLI 的完整交付流程。底層已有音軌與字幕渲染能力，但不代表商業成片流程已完成。
5. 此 CLI 合片目前產生靜音音軌，不會保留模型原生音訊，因此在付費提交前拒絕 `--native-audio` 合片。原生音訊可由轉接器或 `runner.run(..., stitch=False)` 產生單段素材；專業旁白須另製、核准並混合。
6. 供應商真實可用模型、素材限制、單價與帳戶餘額仍須在實際執行時確認。

不明提交的檢查點不可直接刪除重跑。先在供應商後台核對；找到原任務後由維護者將正確編號補回狀態再續查，未確認前不新建付費任務。

## 本輪驗證（2026-09-18）

- Python 3.12 虛擬環境：`python -m pytest -o addopts='' -q` → **172 passed**。
- CLI 離線首次產片與讀取 state.json 重啟續跑：皆回傳 0、stage=STITCHED。
- ffprobe：3.000 秒、720×1280、H.264 + AAC 靜音軌。
- 此執行環境未設定 `ORCAROUTER_API_KEY`；未呼叫真實付費影片 API，也未驗證帳單。
- 本輪沒有合併主分支，也沒有向任何影音平台發片。
