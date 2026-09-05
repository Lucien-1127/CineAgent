# 🎬 CineAgent v4

Provider-neutral、shot-based、reference-first、audio-timeline-driven 的 AI 影片製作系統。

CineAgent v4 把舊版「單一供應商（Agnes）、單一檔案、線性腳本」重構為可接入任意
Provider、可逐步驗證的 Production System。狀態標示遵守 `implemented` / `experimental`
/ `planned` / `deprecated`，文件永遠不超前實作。

> ⚠️ **Agnes 已停止使用**。v4 Runtime 不再耦合 Agnes；Agnes 相關舊文件保留於
> `docs/` 段落作為 migration 歷史，不作為現行架構。

---

## ✅ 目前已實作（implemented）

- **Canonical Domain Model**：`VideoProject`、`CreativeBrief`、`ScriptPackage`、
  `VisualBible`、`ShotSpec`、`Asset`、`GenerationJob`、`QAReport`、`MasterTimeline`
  （Pydantic + JSON Schema 驗證，`cineagent/domain/`）。
- **SQLite + WAL 持久層**：projects / scenes / shots / assets / jobs / usage_events /
  qa_reports / publish_jobs 八表、repositories、cost ledger 聚合
  （`cineagent/storage/`）。
- **Script Engine**：`CreativePlanner` → `HookGenerator`（≥3 candidates+評分）→
  `ScriptWriter` → `ScriptCritic`（重試迴圈）→ `FactVerifier`（資訊型內容）
  → `StoryboardDirector`。JSON parse 失敗不接受自由文字（`cineagent/creative/`）。
- **Audio-First Pipeline**：`AudioProvider` 介面 + Mock TTS（原生 word timestamps）、
  `MasterTimeline`、字幕/SRT 從同一份 canonical timing data 產生
  （`cineagent/orchestration/`、`cineagent/media/captions.py`）。
- **Storyboard + VisualBible**：`StoryboardDirector` 只產 Canonical ShotSpec；
  `PromptCompiler` 只在此對應到 vendor prompt（未實作的 vendor 拋
  `VendorNotImplemented`）。
- **Asset Router**：hash 去重、semantic search、reuse-before-generate
  （Library → Stock → Generate），`cineagent/assets/`。
- **Model Capability Registry + ModelRouter**：依 modality/cost/budget 選
  provider+model+fallback chain（`cineagent/providers/capability.py`）。
- **Image / Video Provider**：介面 + Mock（durable、idempotent remote job、
  poll lifecycle），`cineagent/providers/`。
- **Renderer**：`RendererProvider` 抽象；`FFmpegRenderer`（實作出可播放 MP4：
  拼接、字幕燒錄、音軌混音）；`RemotionRenderer`（primary，`planned`）。
- **QA**：`TechnicalQA`（ffprobe：可解碼/時長/fps/解析度/音軌/比例/大小）、
  `VisualQAProvider` + Mock。
- **Publishing**：`YouTube/TikTok/Instagram/X/Telegram` 五個 publisher，皆有
  dry-run、spec/metadata 驗證、remote post ID 持久化；**預設 dry-run，不自動發布**。
- **Analytics**：`AnalyticsCollector` + `ContentLearningStore`（累積到
  `min_samples` 才形成 learning，禁止單一影片直接改全域規則）。
- **CLI/表層**：`cineagent/` 套件 + Mock providers 可離線跑完整 mainline。

---

## 🚀 快速開始（離線 smoke）

```bash
pip install -e ".[dev]"
python -m pytest -q                       # 56 tests（含 E2E offline smoke）
```

完整測試類別：Unit、Integration、Provider Mock、State Recovery、Idempotency、
Schema Validation、Cost Calculation、Renderer Smoke、E2E Smoke。

## 📁 專案結構（v4）

```
cineagent/            # 核心套件
  domain/             # Canonical models
  creative/           # Script engine
  orchestration/      # pipeline / timeline
  providers/          # text / image / video / audio (+ capability)
  assets/             # library / embeddings / stock / router
  media/              # ffmpeg / audio / captions
  qa/                 # technical / visual
  publish/            # providers (dry-run)
  analytics/          # collector / learning
  storage/            # sqlite + repositories
  renderer/           # Remotion(planned) / FFmpeg(implemented)
tests/                # 單元/整合/mock/E2E
docs/                 # 架構、遷移、provides、狀態
.github/workflows/    # CI + secret scan
```

> 舊 `run_pipeline.py`（Agnes v3）於 migration 期間仍存在於 repo 根目錄，但**不再
> 是 v4 架構的一部分**，將於 Strangler Migration 完成後移除（見 `docs/migration-plan.md`）。

---

## 📊 文件狀態總表

| 組件 | 狀態 |
|------|------|
| Domain models | implemented |
| SQLite storage / ledger | implemented |
| Script Engine | implemented |
| Audio-first timeline | implemented |
| Storyboard / VisualBible | implemented |
| Asset Router | implemented |
| Model Capability Router | implemented (僅 mock provider) |
| Image/Video Mock providers | implemented |
| FFmpeg Renderer | implemented |
| Remotion Renderer | planned |
| Technical QA | implemented |
| Visual QA (multimodal) | planned (介面 implemented) |
| Publishers (dry-run) | implemented |
| 真實發片(YouTube 等 API) | planned |
| Kling/Runway/Veo/Sora/Luma/OrcaRouter | planned |

---

## 🔐 安全

- 不於 repo 保存任一 provider key；全部讀取環境變數（`*.env` 已忽略）。
- CI 含 git-history secret scan。
- Publishers 預設 dry-run，未設定不發布。

## 📜 授權

MIT。
