# 🎬 影片／動畫製作指南（Seedance 與 Kling）

狀態：`experimental`（adapter 已實作並有 Mock 測試，尚未以真實 API 驗證）。

動畫生成**只支援 Seedance 與 Kling**。Agnes／AGNETS 已全面棄用，不得再作為動畫模型、
備援模型、Provider、API 路由或設定選項。本文件描述現行動畫層；Agnes 舊文件只存於
標記為 migration 歷史的章節。

## 統一介面

Pipeline 不直接呼叫 vendor API。所有動畫生成走 `cineagent/providers/video/` 的統一契約：

| 模組 | 用途 |
|------|------|
| `schemas.py` | `VideoGenerationRequest`、`VideoTask`、`VideoTaskStatus`（provider-neutral） |
| `generation.py` | `GenerationProvider` Protocol：`create_task` / `get_task` / `download_result` |
| `seedance.py` | Seedance adapter（火山方舟 Ark） |
| `kling.py` | Kling adapter（快手可灵） |
| `mock_generation.py` | 離線 Mock（測試／E2E） |

API Key 一律讀環境變數，不得寫入 repo：

- Seedance：`ARK_API_KEY`
- Kling：`KLING_ACCESS_KEY` + `KLING_SECRET_KEY`（JWT 簽章）

---

## Seedance（火山方舟 Ark）

- Base URL：`https://ark.cn-beijing.volces.com/api/v3`
- 建立任務：`POST /contents/generations/tasks`
- 查詢任務：`GET /contents/generations/tasks/{id}`
- 驗證來源：`docs.volcengine.com/docs/82379/1520757`（create）、`1521309`（query）、`2298881`（tutorial）

### 模型 ID（VERIFIED）

| 模型 | Model ID | 時長(秒) |
|------|----------|----------|
| Seedance 2.5 | `doubao-seedance-2-5-260628` | 4–30 |
| Seedance 2.0 | `doubao-seedance-2-0-260128` | 4–15 |
| Seedance 2.0 fast | `doubao-seedance-2-0-fast-260128` | 4–15 |
| Seedance 2.0 mini | `doubao-seedance-2-0-mini-260615` | 4–15 |
| Seedance 1.5 pro | `doubao-seedance-1-5-pro-251215` | 4–12 |
| Seedance 1.0 pro | `doubao-seedance-1-0-pro-250528` | 2–12 |
| Seedance 1.0 pro fast | `doubao-seedance-1-0-pro-fast-251015` | 2–12 |

### 能力矩陣（VERIFIED）

| 能力 | 2.5 | 2.0 系列 | 1.5 pro | 1.0 pro | 1.0 pro fast |
|------|-----|----------|---------|---------|--------------|
| 文生影片 | ✓ | ✓ | ✓ | ✓ | ✓ |
| 圖生影片（首幀） | ✓ | ✓ | ✓ | ✓ | ✓ |
| 首尾幀 | ✓ | ✓ | ✓ | ✓ | ✗ |
| 參考圖片 | ✓ | ✓ | ✗ | ✗ | ✗ |
| 參考影片／音訊 | ✓ | ✓ | ✗ | ✗ | ✗ |
| 原生音訊（generate_audio） | ✓ | ✓ | ✓ | ✗ | ✗ |

> Adapter 會在 `build_payload` 過濾不支援的欄位（例如 1.0 pro fast 的首尾幀、1.0 系列的
> 參考圖片），不會硬送。

### 重要事實（VERIFIED）

- 影片 URL 有效期 **24 小時**（Seedance 2.5 另有 100 次下載上限）；`last_frame_url` 也是 24h。
- 失敗格式：`status: "failed"` + `error: {code, message}`。
- 狀態列舉：`queued` / `running` / `succeeded` / `failed` / `expired`。
- 計費為 token-based（`usage.completion_tokens`），**單價 UNVERIFIED**，尚未註冊進 registry。

---

## Kling（快手可灵）

- Base URL：`https://api-singapore.klingai.com`（國際版）／`https://api-beijing.klingai.com`（中國版）
- 建立：`POST /v1/videos/text2video`、`/v1/videos/image2video`
- 查詢：`GET /v1/videos/{task_id}`
- 認證：AccessKey + SecretKey 自簽 JWT（HS256）
- 驗證來源：官方 upstream 由多個 provider 鏡像（`docs.maasunion.com` 等）；官方文件為 JS app。

### 模型 ID（PARTIAL — 採保守值）

`kling-v1`、`kling-v1-5`、`kling-v1-6`、`kling-v2`、`kling-v2-master`、`kling-v2-5`、
`kling-v2-5-turbo`、`kling-v2-6`、`kling-v3`（文生＋圖生）；`kling-v2-1`、
`kling-v2-1-master`（僅圖生）。

### 能力（PARTIAL）

- 圖生影片：`image`（首幀）＋ `image_tail`（尾幀）。
- 時長：`"5"` 或 `"10"`（`kling-v2-5-turbo` 僅 5／10）。
- 模式：`std`（720p）／`pro`（1080p）／`4k`。
- 原生音訊：`sound: "on"`，僅 `kling-v2-6`／`kling-v3` 交叉確認。
- 失敗格式：`task_status: "failed"` + `task_status_msg`；成功字串為 `"succeed"`。

### UNVERIFIED（不實作）

- `multi_shot`（多鏡頭）：Kling API 2.0 概念，legacy API 無此欄位 → 不轉送。
- element／character reference（角色／元素參照）：未在 legacy 標準端點驗證 → 不實作。
- 確切計價（Unit／美元）：未驗證 → registry 的 `estimated_cost_usd` 留 `None`。

---

## 長動畫分段

單段超過模型上限時，用 `cineagent/orchestration/planner.py` 的 `plan_segments` 自動拆分，
段與段之間保留 `overlap_seconds`（預設 0.2）供接縫去重。每段為可獨立重跑的最小單位，
保存輸入素材、提示詞、模型、任務 ID、輸出 URL 與狀態。

## 首尾幀接縫

1. 下載每段影片。
2. FFmpeg 抽取每段最後一幀（`cineagent/media/ffmpeg.py::extract_last_frame`）。
3. 該幀作為下一段首幀來源（`orchestration/stitching.py::link_segments`）。
4. 抽幀失敗 → 該連結降級為 prompt continuity，並記錄於 `SeamReport`（不誤判完成）。
5. 合片前裁掉每段重疊頭部（`stitch_segments`），重新編碼後 `ffprobe` 驗證。

## 提示詞原則

- **圖片提示詞**負責靜態構圖、角色、場景、光線與風格。
- **影片提示詞**負責動作、鏡頭、環境運動與節奏；不要每段重寫角色核心特徵。
- 一致性鎖定：`character_bible`、`visual_style_bible`、`continuity_rules`（見
  `cineagent/domain/pipeline.py::SegmentState`）。
- 不同 Provider 的提示詞格式差異放進 adapter，不污染主流程。

## CLI

```bash
python -m cineagent.cli --topic "主題" --video-provider kling --total-duration 30 --long-video
python -m cineagent.cli --topic "主題" --video-provider seedance --plan-only
python -m cineagent.cli --topic "主題" --video-provider mock --total-duration 9   # 離線
```

選項：`--video-provider kling|seedance|mock`、`--long-video`、`--plan-only`、
`--segment-max-duration N`、`--native-audio`、`--multi-shot`（UNVERIFIED，不轉送）、
`--resume STATE.json`。
