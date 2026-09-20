# CineAgent v4 — 現況稽核報告 (Repository Audit)

- 稽核日期：2026-09-03
- Repository：`Lucien-1127/CineAgent`（origin 已確認相符）
- Branch / HEAD：`main` @ `f77e7cc3f04a34c9c7e17316a0b30a3099504b44`
- Working tree：乾淨（clone 後未修改）
- 稽核人：CineAgent v4 重構（Phase 0）
- 結論摘要：**現行 Runtime 為「單一供應商（Agnes）+ 單一檔案（run_pipeline.py）+ 線性、無音訊、無成本、無 QA、無發布」的流程。文件宣稱的功能（Telegram/X 發布、斷點續傳、成本與一致性控制）與 Runtime 實際能力有顯著落差。** 採用 Strangler Migration 漸進重構。

---

## 0. 稽核方法

- `git remote -v`：`https://github.com/Lucien-1127/CineAgent.git`（fetch/push 皆相符）✅
- 全 repo 檔案清單、行數、尺寸盤點。
- `run_pipeline.py`（1375 行）逐段閱讀：AgnesAPI、PipelineState、main() 流程、script/storyboard 生成。
- 全檔案（含 git history 所有 blob）scalning：`agnes`、硬編碼 URL、API key/secret、Telegram/X/publish、cost、except Exception、測試/CI 目錄。
- 實際執行驗證：`python3 run_pipeline.py --help`、依賴安裝、ffmpeg/ffprobe 可用性。

---

## 1. 現行架構

### 1.1 檔案地圖

```
CineAgent/
├── run_pipeline.py        # 全部 Runtime：1375 行、單一檔案、v3.4
├── requirements.txt       # 僅 httpx>=0.27.0
├── AGENTS.md              # Hermes 操作手冊（含大量已過時宣稱）
├── README.md              # 產品說明（含未實作的 Telegram/X 發布宣稱）
├── docs/                  # 6 份文件（大量 Agnes 專屬規格）
├── references/            # 4 份參考（含 Agnes Video API 陷阱筆記）
├── templates/             # 3 份模板（script / beat-sheet / storyboard）
└── output/                # 產出（目前僅 .gitkeep）
```

### 1.2 Runtime 實際執行流程（非 README 推測）

`main()` 三階段線性流程，全部依賴 Agnes：

```
Phase 0 Script Design（Agnes chat）
  ├─ design_script(): 需求萃取 + Beat Sheet（Save the Cat）+ write_script_v3()
  ├─ consistency: coherence_pass() 統一 character_card
  └─ 產出 output/script_package.json、beat_sheet.json、scene_prompts.json
        ↓
Phase 1 Images（Agnes Image）
  └─ 逐 scene：build_image_prompt() → /v1/images/generations → URL
        ↓
Phase 2 Videos（Agnes Video，I2V）
  ├─ 單 scene：generate_video() → poll_video()（GET /agnesapi 輪詢）
  ├─ Frame Chaining：ffmpeg 抽末幀 → Agnes/imgbb 上傳 → 當下一鏡 anchor
  └─ --multi-image：generate_multi_image_video()
        ↓
Complete
  └─ 寫入 output/notify_payload.json（這是「發布」唯一產物，任何平台皆未實際送出）
```

### 1.3 關鍵實作事實

- **供應商耦合**：`AgnesAPI` class + 硬編碼 `AGNES_*` 常數、模型名、endpoint。Text/Image/Video 全部走 `apihub.agnes-ai.com`，無任何 adapter 分層。
- **狀態機**：單一 JSON `agents_workflow_state.json`，欄位為粗粒度 `current_stage` 字串
  `INIT / SCRIPT_DONE / IMAGE_GEN / IMAGE_DONE / VIDEO_GEN / VIDEO_DONE / COMPLETE`，加上 `image_urls` / `video_urls` / `last_frame_urls` dict。
- **遠端 Job**：提交後取得 `video_id`（`generate_video()` 回傳值），但**只把輸出 URL 存進 state，未保存 video_id** → 重啟後無法 resume polling。
- **音訊**：完全沒有 narration / dialogue / TTS / timeline。每場景時長由 `duration_seconds × scenes` 猜算，直接違反「Audio-first Master Timeline」原則。
- **Scene vs Shot**：無 Shot 概念。「scene」同時當故事單位與生成單位混用。
- **成本**：僅 `QUOTA_VIDEO_SEC = 500` 秒數計數。無 planned/actual cost、無 per-call cost ledger。
- **錯誤處理**：全文 15 處 `except Exception` 吞錯（僅 429 有指數退避）。無 401/5xx/timeout 分類。

### 1.4 可立即執行性

- 語法：`run_pipeline.py` 通過 `ast.parse` ✅
- 依賴：httpx 原本未安裝（venv 已裝 httpx 0.28.1 + pytest 9.1.1）✅
- ffmpeg / ffprobe：`/usr/bin/ffmpeg`、`/usr/bin/ffprobe` 存在 ✅
- 真實跑完整 pipeline **需要 AGNES_API_KEY**（已 deprecated，無法再驗證完整流程；local 無測試基線）。

---

## 2. 技術債

| # | 項目 | 嚴重度 | 說明 |
|---|------|--------|------|
| T1 | Provider 全耦合 | 高 | AgnesAPI 混入 runtime；pipeline 知道 vendor schema（`/v1/videos`、`extra_body`、`remixed_from_video_id`） |
| T2 | 單一檔案 1375 行 | 高 | 無模組邊界，難測試、難加入新 provider |
| T3 | 無音訊 / 無 timeline | 高 | 違反 Audio-first 原則；時長靠猜 |
| T4 | 無 Scene/Shot 分離 | 高 | 無法逐鏡頭恢復、逐鏡頭 QA、逐鏡頭成本 |
| T5 | 狀態機不持久、不冪等 | 高 | 單一 JSON；`current_stage` 粗粒度；COMPLETE 無條件設定（即使部分/全部失敗也標 COMPLETE，違反原則 9）；video_id 未保存無法 resume |
| T6 | 無 Asset Library / reuse | 高 | 無 hash 去重、無 embedding、無 reuse 判斷；每次全重新生成 |
| T7 | Reference 僅靠文字提示詞 | 中 | character_card 靠 prompt 注入；無 VisualBible、無 first/last frame 真正用於維持一致性（Frame Chaining 只是末幀 anchor） |
| T8 | 無 Renderer | 高 | 生成模型輸出孤立影片 URL，從不組裝；無字幕/BGM/轉場/Logo/End Card |
| T9 | 無成本控管 | 高 | 無 budget_limit、無 planned/actual cost、失敗計費無法追蹤 |
| T10 | 錯誤全吞 | 中 | `except Exception` 將 401/5xx/malformed 一律重試，可能浪費費用 |
| T11 | 無 CI / 無測試 | 高 | repo 無 tests/、無 pytest 設定、無 .github |

---

## 3. 過時功能（將淘汰 / 封存）

- **Agnes 串接**（整個 Runtime 核心）：`AgnesAPI`、`AGNES_API/ROOT/KEY/IMG/VIDEO/TEXT_MODEL`、polling endpoint、`/v1/videos` schema → 全數移除自 runtime，改為 Provider-neutral contract。
- **Agnes 專屬文件**：`docs/pipeline-architecture.md`、`docs/image-generation.md`、`docs/video-production.md`、`references/video-api-pitfalls.md` → 移至 `migration/archive/`（保留歷史事實，不宣稱仍在使用）。
- **AGENTS.md 現有內容**：載明 agnes 模型與斷點續傳宣稱 → 重寫。
- `--multi-image` 單場景整段生成舊模式（與逐鏡頭架構衝突）→ 重設計為開場/結尾可選功能。

---

## 4. 安全問題

| # | 項目 | 嚴重度 | 說明 |
|---|------|--------|------|
| S1 | Secret 硬編碼 | 低（已緩解） | 目前金鑰皆來自 env；git history 全 blob scan 僅出現 README placeholder `AGNES_API_KEY="your_key"`，**未發現真實 secret**。commit `37442c4` 已移除硬編碼金鑰。 |
| S2 | 金鑰缺省無驗證 | 中 | `AGNES_KEY` 空字串時仍建 AsyncClient 帶空 Bearer 靜默失敗；無啟動時驗證。 |
| S3 | 預設第三方圖床上傳 | 中 | Frame Chaining 失敗時自動降級上傳 imgbb（免費圖床）→ 預設把生成畫面送到第三方；需改為使用者可控、預設關閉。 |
| S4 | 無成本閘門 | 高 | 昂貴生成前無 planned cost / budget_limit 檢查，可能默默超支。 |
| S5 | 錯誤吞掉隱藏 401/429 | 中 | 認證失敗被當一般異常重試 4 次，浪費額度。 |

> 結論：無已洩漏 secret；但有過度自動化第三方上傳與缺成本/認證閘門的安全缺口。

---

## 5. 文件漂移（Document Drift）

| 文件 | 宣稱 | Runtime 實際 | 落差 |
|------|------|--------------|------|
| README.md | 「最後直接送到 Telegram 或 X」、Phase 3 平台傳送（Telegram 推送 / X Post API 自動發布）、X 整合規格表 | 僅寫 `output/notify_payload.json`，**無任何平台 API 呼叫** | 重大：發布功能不存在 |
| README.md | `run_pipeline.py v3.1` | 檔案 header 為 v3.4 | 版本號過時 |
| AGENTS.md | 斷點續傳（`SCRIPT_DONE/VISUAL_DONE/VIDEO_DONE` 自動從中斷處恢復） | 只有粗粒度 stage；且 COMPLETE 無條件設定 | 續傳宣稱過度 |
| AGENTS.md | 推理模型 `agnes-2.0-flash` 等 | Agnes 已 deprecated | 核心組態過時 |
| docs/bot-ui-design.md | `Telegram API | Bot 訊息 | ✅`、`/share 發布` | 未實作 | 狀態標記不實 |
| 全體 | 無狀態詞彙 | — | 全 repo 未使用 `implemented / experimental / planned / deprecated` 狀態語義 |

---

## 6. 測試基線

- **測試數量**：0（無 `tests/`、無 pytest 設定、無 CI、無 `.github/`）。
- **即刻可驗證項目**：`run_pipeline.py` 語法 OK；ffmpeg/ffprobe 存在；venv 依賴可安裝。
- **完整 E2E 無法執行**：需要 AGNES_API_KEY（已 deprecated）＋ 線上 Agnes 服務。
- **缺少的測試**（對齊 v4 原則 21）：Unit / Integration / Provider Mock / State Recovery / Idempotency / Schema Validation / Cost Calculation / Renderer Smoke，以及 15 個指定失敗案例（401/429/422/timeout/5xx/crash/remote dup/webhook 重複/晚到/malformed/schema fail/partial video/disk full/missing ffmpeg/budget）。
- **測試基線策略（Phase 0 結論）**：所有 provider 用 Mock 注入，讓 pipeline 可在「無任何 vendor 金鑰」下被完整測試；Technical QA 用 ffprobe 對合成片段做真實驗證。

---

## 7. 遷移風險

| 風險 | 說明 | 緩解 |
|------|------|------|
| 無測試 / 無 CI | 改寫易回歸 | 每個 Phase 先建立該 Phase 的測試再改；CI 從 Phase 1 起加入 |
| 單一檔案耦合深 | Big Bang 風險高 | Strangler：先建 domain/schema contract，再逐模組抽出 |
| Agnes schema 是唯一現況依據 | 但 Agnes 已 deprecated → 不需保留其 payload，改定義 Provider-neutral contract | 以「能力（capability）」而非 vendor 為核心 |
| 文件宣稱超前 | 新文件只寫已實作 | 全 repo 導入 `implemented/experimental/planned/deprecated` 狀態語彙；未實作者標 planned 或移除 |
| Git history 含 Agnes 文件 | 不可改寫歷史 | 移動到 `migration/archive/` 於新 commit（保留歷史；新樹不含 runtime 依賴） |
| 遠端 push 授權 | 未獲授權不得 push | 本階段全程僅 local commit，不 push |

---

## 8. 現行模組處置清單（保留 / 重構 / 淘汰）

### 保留或改寫再利用（不含 Agnes 依賴）
- **Beat Sheet / Save the Cat、Hook-Value-CTA、character_card / visual_style 一致性** 的創作框架 → 改寫進 `creative/`（planner、script_writer、critic）。
- **ffmpeg 抽末幀、8n+1 幀規則、duration presets、IMG/VID negative prompt 預設** → 移到 `media/ffmpeg.py`、shot timing / model capability、`domain/visual.py::negative_constraints`。
- **async httpx client 使用模式** → `providers/base.py` 的 transport 基礎。
- `templates/`（script-template.json、beat-sheet-template.md、storyboard-template.md）、`references/script-frameworks.md`、`references/beat-sheet-templates.md`、`references/writing-persona-framework.md` → 保留為內容參考，視需要遷移。

### 重構
- `main()` 三階段流程 → `orchestration/pipeline.py` + `state.py` + `worker.py`。
- `build_image_prompt / build_video_prompt / coherence_pass` → `PromptCompiler` + `VisualBible`。
- 腳本/分鏡 JSON 手動 parse → Pydantic domain models（`domain/`）。

### 淘汰 / 封存（Agnes 專屬）
- `AgnesAPI` class、`AGNES_*` 常數、polling、Agnes endpoint/model。
- `docs/pipeline-architecture.md`、`docs/image-generation.md`、`docs/video-production.md`、`references/video-api-pitfalls.md`（移至 `migration/archive/`）。
- `bot-ui-design.md`、`AGENTS.md`、`README.md` 中關於 Telegram/X「已實作」的宣稱 → 改標 `planned` 或移除。

---

## 9. 優先建議（指向 Phase 1+）

1. 建立 `domain/` Canonical schemas（VideoProject / CreativeBrief / ScriptPackage / VisualBible / ShotSpec / Asset / GenerationJob / QAReport）。
2. 建立 `storage/`（SQLite + WAL）取代單一 JSON 狀態。
3. 建立 `providers/base.py` capability-based contract（Text/Image/Video/Audio 分離）。
4. 導入測試框架 + CI + Provider Mock，建立可離線執行的基線。
5. 依 Strangler Phases 逐項替換，每 Phase 跑測試後再前進。

---

*本檔案為 Phase 0 稽核交付物。後續 Architecture Proposal 見 `docs/architecture-v4.md`，Migration Plan 見 `docs/migration-plan.md`。*
