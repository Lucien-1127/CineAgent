# CineAgent v4 — 遷移計畫 (Migration Plan)

- 狀態：`planned`
- 依賴：`docs/audit-v4.md`（Phase 0）、`docs/architecture-v4.md`（目標架構）

## 0. 遷移策略：Strangler Migration

不進行 Big Bang Rewrite。新的 `cineagent/` 套件與舊 `run_pipeline.py` 並存；每完成一個 Phase，新流程可測試、可離線驗證（Provider 全 Mock）。舊 Agnes runtime 保留至最後再封存（放入 `migration/archive/`），避免中途退回。

### 並存與斷層規則
- 新套件新增檔案，不刪舊檔，直到相對應階段驗證完成。
- 每 Phase 結束：`pytest` 全綠、記錄修改檔案、記錄測試結果、記錄未解決問題。
- 僅 local commit；未獲授權不 push。

## 1. Phase 清單與範圍

| Phase | 名稱 | 交付物 | 驗證方式 |
|-------|------|--------|----------|
| P0 | Audit | `docs/audit-v4.md` | 已完成 ✅ |
| P0.5 | 規劃 | `docs/architecture-v4.md`、`docs/migration-plan.md`、測試基線（pytest+CI 設定） | 本文 |
| P1 | Canonical schemas | `cineagent/domain/*`（Pydantic）+ schema validation tests | unit tests |
| P2 | State/Storage | SQLite+WAL、repositories（projects/scenes/shots/assets/jobs/usage_events/qa_reports/publish_jobs）、state recovery 測試 | unit + recovery tests |
| P3 | TextProvider + Script Engine | `providers/text/*`、`creative/`（planner/hook/writer/critic/fact_check）、PromptCompiler | mock provider + integration |
| P4 | Audio Timeline | `providers/audio/*`、TimingAlign、MasterTimeline、captions | mock TTS + alignment test |
| P5 | Storyboard + VisualBible | `creative/storyboard.py`、`domain/visual.py`、VisualBible repo | unit + mock |
| P6 | Asset Router | `assets/library.py`+`embeddings.py`+`stock.py`、AssetRouter | reuse 決策單元測試 |
| P7 | Image/Video Providers | `providers/image/*`、`providers/video/*`、Capability Registry、Router | provider mock tests |
| P8 | Renderer | `renderer/`（Remotion FFmpeg）、`media/ffmpeg.py` | renderer smoke tests |
| P9 | QA | `qa/technical.py`、`qa/visual.py`、QAReport | ffprobe + mock multimodal |
| P10 | Publishing | `publish/providers/*`（含 dry-run） | dry-run + mock |
| P11 | Analytics | `analytics/collector.py`、`learning.py` | unit tests |
| P12 | 收尾 | 文件同步、README/AGENTS 對齊、CI、DoD 驗證、舊 runtime 封存 | E2E smoke + DoD checklist |

## 2. 模組處置（對齊 audit §8）

- **保留**：創作框架概念（beat sheet / Hook-Value-CTA / character_card 一致性思路）、ffmpeg 抽幀與 8n+1 規則、negative prompt 預設、templates/、部分 references/。
- **重構**：`main()` 三階段 → orchestration；prompt 建構 → PromptCompiler；script JSON → domain/Pydantic；async httpx → providers/base transport。
- **淘汰／封存**：`AgnesAPI` 與 `AGNES_*`、Agnes docs、Telegram/X「已實作」宣稱。

## 3. 測試基線（Phase P0.5 建立）

- pytest 9.1.1 已裝（venv：`/home/droid/workspace/CineAgent/.venv`）。
- `pyproject.toml` 定義專案與 `[tool.pytest.ini_options]`。
- 每 Phase 新增對應測試；Provider 一律 Mock 注入，test 不需金鑰。
- CI（GitHub Actions）於 P1 建立，跑 `pip install -e .[dev] && pytest`。
- E2E smoke：`Topic → Script → Voice → Timeline → Shots → Assets → Render → Final MP4`，全部 Mock 或本地合成（ffmpeg），不需外部 vendor。

## 4. 風險與回滾

- 每 Phase 有獨立 commit；回滾 = revert 該 commit。
- 舊 `run_pipeline.py` 保留到 P12，期間仍可手動執行（需 Agnes key，但不被 v4 依賴）。
- 新增 package 使用 `cineagent/` 名，與舊單檔不衝突。

## 5. 未解決問題（持續清單）

- 各 vendor（Kling/Runway/Veo/Sora/Luma）確切 price/duration/concurrency：依原則「遇到未知 API 或模型能力時必須查官方文件」，於 P7 Router/Adapter 實作前逐一查證，禁止猜測 payload/價格/模型名。
- Embedding：真實語意 embedding 需外部模型；offline fallback 標 `experimental`，不宣稱是真語意相似度。
- Remotion 是否安裝於本機環境：P8 前確認；建構時以 FFmpeg 為可驗證的真正 fallback。
