# 動畫流水線架構（Seedance / Kling）

狀態：`experimental`（Seedance／Kling adapter）＋ `implemented`（離線 pipeline）。

## 目標

以 Seedance 與 Kling 兩個動畫模型，支援 5–15 秒短動畫，並可延伸至長動畫的工業化分段管線。
Agnes／AGNETS 已全面棄用，不作為動畫模型、備援、Provider、路由或設定選項。

## 元件

| 元件 | 位置 | 責任 |
|------|------|------|
| 統一 schema | `providers/video/schemas.py` | `VideoGenerationRequest`／`VideoTask`／`VideoTaskStatus` |
| 生成契約 | `providers/video/generation.py` | `GenerationProvider` Protocol（create/get/download） |
| Seedance adapter | `providers/video/seedance.py` | 火山方舟 Ark 內容生成 API |
| Kling adapter | `providers/video/kling.py` | 快手可灵 legacy `/v1/videos/*` JWT API |
| 能力註冊 | `providers/capability.py` | Seedance／Kling 已驗證能力（時長、比例、能力、價格留 None） |
| 分段規劃 | `orchestration/planner.py` | `plan_segments`（超長拆分＋重疊） |
| 接縫處理 | `orchestration/stitching.py` | `link_segments`（末幀→下段首幀）＋ `stitch_segments`（去重＋合片） |
| 狀態／續傳 | `domain/pipeline.py` | `PipelineRunState`＋`SegmentState`（JSON 持久化） |
| 執行器 | `orchestration/runner.py` | `VideoPipelineRunner`（submit/poll/download＋重試＋續傳） |
| CLI | `cli.py` | `python -m cineagent.cli`（`--video-provider` 等） |

## 資料流

```
CLI ──► plan_segments ──► VideoPipelineRunner ──► GenerationProvider ──► 下載
                                │                        │
                                │ (resume：跳過完成段)     │ create_task/get_task
                                ▼                        ▼
                          SegmentState（持久化）      Seedance / Kling / Mock
                                │
                                ▼
                     link_segments（末幀串接）→ stitch_segments（去重合片）
                                │
                                ▼
                     final.mp4 → TechnicalQA（ffprobe 驗證）
```

## 斷點續傳

- 每段保存 `remote_job_id`、`output_url`、`local_path`、`status`、`retry_count`。
- 重跑時：`is_complete`（succeeded 且有輸出）→ 跳過；有 `remote_job_id` 但狀態不明 → 先查詢，不盲目重送。
- 錯誤分流：`AuthError`／`ValidationError`（422）→ `BlockerError`，停整條並回報；
  `RateLimitError`（429）／`ProviderFailure`／timeout → 在 `budget.max_retries_per_segment` 內重試。

## 已驗證 vs 未驗證

- **VERIFIED**（官方文件）：Seedance 模型 ID／端點／能力矩陣／時長範圍／URL 24h 有效期／失敗格式。
- **PARTIAL**：Kling legacy API（官方 upstream 由多 provider 鏡像，官方文件為 JS app）。
- **UNVERIFIED（不實作）**：multi-shot、element/character reference、確切價格、Seedance 2.5「180 秒模式」。

完整驗證與來源見 `references/video-provider-verification.md`。

## 真實 API 驗證缺口

- 本機無 Seedance／Kling／OrcaRouter 金鑰（僅 DEEPSEEK／OPENROUTER／NOTION），無法做真實 E2E。
- 「建立任務成功」與「Mock 測試成功」不得描述為真實 API 已驗證。
- 首尾幀跨段連結需把本地上傳為公網 URL；上傳通道未驗證（離線 path 用本機檔案即可）。
