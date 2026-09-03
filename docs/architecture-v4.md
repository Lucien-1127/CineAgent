# CineAgent v4 — 目標架構設計 (Architecture Proposal v4)

- 狀態：`planned` → 逐 Phase 轉 `implemented`
- 依賴：`docs/audit-v4.md`（Phase 0 稽核）

## 1. 設計目標

把 CineAgent 從「單一供應商（Agnes）、單一檔案、線性、無音訊」升級為 Provider-neutral、Shot-based、Reference-first、Audio-timeline-driven 的 AI 影片製作系統。核心原則是「能力（capability）為中心，而非供應商」：pipeline 只認識抽象 contract，vendor 細節全部封在 Adapter 內。

完整流程：
```
Idea → Research → Script → Voice → Timeline → Storyboard → Visual Bible
→ Shot Plan → Asset Routing → AI Generation → Editing → QC → Review
→ Publish → Analytics Feedback
```

## 2. 分層架構

```
┌────────────────────────────────────────────────────────────┐
│  API / CLI 層            api/                             │
├────────────────────────────────────────────────────────────┤
│  編排層 (orchestration)                                    │
│   pipeline.py state.py worker.py routing.py               │
│   - Audio-first Master Timeline 驅動                       │
│   - 每 Shot 獨立狀態機（idempotent、可恢復）                 │
│   - Production Mode (draft/auto/cinematic) + Approval Gate │
├────────────────────────────────────────────────────────────┤
│  創作層 (creative)                                         │
│   planner / hook / script_writer / critic / fact_check /   │
│   storyboard → 產出 Canonical ShotSpec，不直出 vendor prompt│
├────────────────────────────────────────────────────────────┤
│  資產層 (assets) + 語意庫 / stock       reuse before gen    │
├────────────────────────────────────────────────────────────┤
│  媒體層 (media)          ffmpeg / audio / captions          │
├────────────────────────────────────────────────────────────┤
│  QA 層 (qa)              technical(ffprobe) + visual(multimodal)│
├────────────────────────────────────────────────────────────┤
│  Provider 層 (providers) base + text/ image/ video/ audio   │
│   - 只有 Adapter 知道 vendor schema (Kling/Runway/Veo/…)     │
│   - Capability Registry 驅動 Router                         │
├────────────────────────────────────────────────────────────┤
│  儲存層 (storage)        SQLite+WAL repositories           │
├────────────────────────────────────────────────────────────┤
│  Domain 層 (domain)      Pydantic canonical models         │
└────────────────────────────────────────────────────────────┘

渲染 (renderer/ Remotion@primary, FFmpeg@utility)
發布 (publish/ providers)
分析 (analytics/ collector + learning)
```

## 3. 關鍵架構決策

### 3.1 Provider 抽象（原則 2）
- `providers/base.py` 定義抽象契約：
  - `TextProvider`（chat, structured 輸出，回傳 validated Pydantic）
  - `ImageProvider`（generate / image-to-image，可 reference）
  - `VideoProvider`（submit async job → webhook 或 polling；保存 remote_job_id）
  - `AudioProvider`（TTS + 原生或 forced-alignment timestamps）
- Pipeline 只依賴契約與 capability，不 import 任何 vendor class。

### 3.2 Scene 與 Shot 分離（原則 3）
- Scene ＝ 故事單位（隸屬 ScriptPackage 的 scenes）。
- Shot ＝ 最小生成單位，持有 `start_time/end_time/duration`、`narration_segment`、`referencence_assets`、`generation_strategy`。
- 一個 Scene 有多個 Shot；恢復、QA、成本都以 Shot 為粒度。

### 3.3 Audio-first Master Timeline（原則 4）
- `Final Script → TTS → Timing Alignment → Master Timeline → Storyboard timing → Shot timing`。
- 只有 TTS 完成、取得實際語音時長與 word/segment timestamps 後，才計算 Shot duration 與字幕 timecode。
- 禁止依 `每幕預設秒數` 猜整支影片。

### 3.4 Generation Job 狀態機（原則 9，DoD 6-7）
- SQLite + WAL 為唯一狀態來源（非單一 JSON）。
- 每個 Shot／Job 獨立狀態：`pending → submitted → generating → succeeded/failed/retrying`，加上 `approved/rejected`。
- 保存 `remote_job_id`；webhook 優先、無則 polling；crash 後由 DB 恢復，**不得**跳成 COMPLETE。
- Idempotent：`submitted` 的遠端 job 存在即不重複計費。

### 3.5 Reference-first 與 Asset Router（原則 5/6）
- `VisualBible` 集中角色／服裝／場景／風格／燈光／鏡頭語言／reference assets／負面約束。
- `AssetRouter` 依序：semantic library → existing project → stock → generated image → image-to-video → text-to-video → premium video。
- Asset Library：hash 去重、metadata、tags、embeddings（`EmbeddingProvider` 介面；offline fallback 為實驗性純 hash 近似）、reuse_count、license。

### 3.6 Capability-based Router（原則 9 / 第九節）
- `ModelCapabilityRegistry` 記錄每模型 capabilities（modalities、I2V/T2V/V2V、first/last frame、reference、duration、AspectRatio、resolution、latency、cost、reliability）。
- Router 輸入：Shot 需求＋品質模式＋預算＋provider health＋成本 → 輸出 `selected (provider, model)` + fallback chain。
- OrcaRouter 可為其中一個 Gateway，但 CineAgent 不依賴它。

### 3.7 Production Mode（第十節）
- `draft`：低成本、stock/library、Ken Burns、單 candidate。
- `auto`：I2V 為主、AI QA、auto repair、hero shot 2 candidates。
- `cinematic`：Approval Gate（Script → Storyboard/Hero Frames → Video → Final Preview → Publish），未核准不執行昂貴下一步。

### 3.8 Candidate 策略（第十五節）
- normal shot：1 candidate；hero shot：2；低 QA score → repair/regenerate；Cinematic 允許人比較。

### 3.9 Cost Ledger（第十六節）
- `usage_events` 表記錄每 API call（planned/actual cost、retry、status、operation、tokens/seconds）。
- 提供 per-project / per-provider / per-model / per-stage / failed-cost / cost-per-finished-second。
- 超過 `budget_limit` 的預估時停止昂貴生成並要求決策。

### 3.10 Renderer（第十二節）
- `RendererProvider`：Remotion（primary）＋ FFmpeg（utility/fallback）。
- Renderer 負責字幕、Karaoke captions、title、hook overlay、watermark、logo、end card、transition、BGM、ducking、SFX、各平台 aspect ratio。
- 生成模型不負責最終字幕與 UI typography。

### 3.11 QA 兩層（第十四節）
- Technical：ffprobe 驗證解碼/duration/fps/resolution/audio stream/aspect/黑幀/尺寸/loudness/safe area。
- Semantic/Visual：multimodal 檢查 ShotSpec adherence、character/wardrobe/environment consistency、unwanted text、artifact、continuity。
- 只重生低於 threshold 的 Shot，不整支重生成。

### 3.12 Publisher（第十七節）
- 獨立 `publish/providers/{youtube,tiktok,instagram,x,telegram}.py`。
- 皆具 dry-run、規格驗證、metadata 驗證、remote post ID 保存、failed/published 判別。
- 預設不自動公開。

### 3.13 Analytics Feedback（第十八節）
- `AnalyticsCollector` 收集 views/retention/engagement 等；`ContentLearningStore` 累積樣本後才形成 Content Learning，**不**允許 LLM 依單支影片改全域規則。

### 3.14 錯誤處理（第二十一節）
- 分類：`AuthError / RateLimitError / ValidationError / TimeoutError / ProviderError / BudgetExceededError / RemoteJobError`。禁止單一 `except Exception` 吞錯。

## 4. 擴充性承諾
新增 Provider（Kling/Runway/Veo/Sora/Luma/OrcaRouter）時只需：
1. 實作對應 Adapter（`providers/video/<name>.py`）。
2. 註冊 capability 到 ModelCapabilityRegistry。
3. （可選）寫成本模型。
核心 pipeline 與 domain 不需改動。
