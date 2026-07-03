# 🤖 AI Media Pipeline — AGENTS.md

## Mission Control

本專案為「AI 多模態影音自動化生產流水線」。請遵循以下規範：

### 1. 狀態讀取
執行任何操作前，優先讀取 `agents_workflow_state.json` 確認先前的執行狀態。

### 2. 斷點續傳
若 `current_stage` 為 `SCRIPT_DONE` 或 `VISUAL_DONE` 或 `VIDEO_DONE`，嚴禁從頭執行。
直接調用 `python run_pipeline.py`，腳本會自動從中斷處恢復。

### 3. API 風控
若遇到 429 且重試失敗，記錄 `[API_PAUSE]` 並掛起，等待人工介入。

### 4. 腳本設計為必經環節
所有影片專案須先完成設計腳本（5 步驟：需求萃取→節奏表→腳本撰寫→分鏡→審查）。

---

## 系統組態

| 參數 | 值 |
|------|-----|
| 推理模型 | `agnes-2.0-flash` |
| 圖片模型 (非 NSFW) | `agnes-image-2.1-flash` |
| 圖片模型 (NSFW) | 本地 SD Forge (DS8/RV6) |
| 影片模型 | `agnes-video-v2.0` (異步渲染) |
| 本地繪圖 | SD WebUI Forge `http://127.0.0.1:7860` |
| 最大並發生圖 | 3 任務並行 |
| 影片安全水位線 | 每日 480 秒 |

---

## 指令集

```bash
# 安裝依賴
pip install -r requirements.txt

# 一鍵啟動
python run_pipeline.py --topic "你的主題"

# 指定分鏡數
python run_pipeline.py --scenes 5

# 指定每場景秒數
python run_pipeline.py --duration 10

# 多圖轉場模式
python run_pipeline.py --multi-image

# 跳過腳本階段（用已有 scene_prompts.json 繼續）
python run_pipeline.py --skip-script

# 結構化 JSON 輸出
python run_pipeline.py --structured

# 重置所有狀態
python run_pipeline.py --reset
```

---

## 專案結構

```
ai-media-pipeline/
├── README.md                    # 專案說明
├── AGENTS.md                    # 本文件
├── run_pipeline.py              # 主執行腳本
├── docs/                        # 文件
├── references/                  # 參考資料
├── templates/                   # 模板
└── output/                      # 產出
```

---

## 📊 當前進度

| 欄位 | 值 |
|------|-----|
| **階段** | 待執行 |
| **分鏡** | 0/0 |
| **失敗** | 0 |
| **影片已用秒數** | 0/500 |
| **更新時間** | - |
