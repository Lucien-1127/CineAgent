# 動畫 Provider 驗證報告（Seedance 與 Kling）

本文件記錄 Seedance 與 Kling 的官方 API 驗證結果，作為 `cineagent/providers/video/`
adapter 的實作依據。狀態標示：`VERIFIED`（官方文件）、`PARTIAL`（官方＋供應商／第三方
交叉，但未逐欄逐字比對官方）、`UNVERIFIED`（未實作）。

研究日期：2026-09-12。研究規則：官方文件優先，Provider／第三方僅作線索。

---

## 一、Seedance（火山方舟 Ark）

### 1.1 端點（VERIFIED）

- Base URL：`https://ark.cn-beijing.volces.com/api/v3`
- 建立任務：`POST /contents/generations/tasks`
- 查詢任務：`GET /contents/generations/tasks/{id}`
- 查詢列表：`GET /contents/generations/tasks`
- 取消／刪除：`DELETE /contents/generations/tasks/{id}`
- 鑑權：`Authorization: Bearer <ARK_API_KEY>`（環境變數 `ARK_API_KEY`）

來源：https://docs.volcengine.com/docs/82379/1520757（建立）、1521309（查詢）。

### 1.2 模型 ID（VERIFIED，官方教學 2298881）

| 模型 | Model ID |
|---|---|
| Seedance 2.5 | `doubao-seedance-2-5-260628` |
| Seedance 2.0 | `doubao-seedance-2-0-260128` |
| Seedance 2.0 fast | `doubao-seedance-2-0-fast-260128` |
| Seedance 2.0 mini | `doubao-seedance-2-0-mini-260615` |
| Seedance 1.5 pro | `doubao-seedance-1-5-pro-251215` |
| Seedance 1.0 pro | `doubao-seedance-1-0-pro-250528` |
| Seedance 1.0 pro fast | `doubao-seedance-1-0-pro-fast-251015` |

### 1.3 能力矩陣（VERIFIED）

| 能力 | 2.5 | 2.0 | 2.0 fast | 2.0 mini | 1.5 pro | 1.0 pro | 1.0 pro fast |
|---|---|---|---|---|---|---|---|
| 文生視頻 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 圖生視頻-首幀 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 圖生視頻-首尾幀 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ |
| 全模態參考（圖） | ✓ (1-30) | ✓ (1-9) | ✓ (1-9) | ✓ (1-9) | ✗ | ✗ | ✗ |
| 參考視頻 | ✓ (≤10) | ✓ (≤3) | ✓ (≤3) | ✓ (≤3) | ✗ | ✗ | ✗ |
| 參考音訊 | ✓ (≤10) | ✓ (≤3) | ✓ (≤3) | ✓ (≤3) | ✗ | ✗ | ✗ |
| 原生音訊（generate_audio） | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ |

### 1.4 時長（VERIFIED，整數秒）

- Seedance 1.0 系列：`[2, 12]`
- Seedance 1.5 pro：`[4, 12]` 或 `-1`（智慧指定）
- Seedance 2.0 系列：`[4, 15]` 或 `-1`
- Seedance 2.5：`[4, 30]` 或 `-1`

### 1.5 content 結構（VERIFIED，建立任務文件）

`content[]` 元素（`type` 固定字串）：

- 文本：`{"type":"text","text":"..."}`
- 圖片：`{"type":"image_url","image_url":{"url":"..."},"role":"first_frame"|"last_frame"|"reference_image"}`
  - 圖生-首幀：1 張，`role` 為 `first_frame` 或不填。
  - 圖生-首尾幀：2 張，`role` 必填（`first_frame` + `last_frame`）。
  - 全模態參考：`role` 皆為 `reference_image`。
- 視頻：`{"type":"video_url","video_url":{"url":"..."},"role":"reference_video"}`
- 音訊：`{"type":"audio_url","audio_url":{"url":"..."},"role":"reference_audio"}`
- 樣片：`{"type":"draft_task","draft_task":{"id":"..."}}`

「首幀」「首尾幀」「全模態參考」三種場景互斥，不可混用。

### 1.6 請求參數（VERIFIED）

`model`、`content[]`、`ratio`（16:9／9:16／1:1／21:9／adaptive）、
`resolution`（480p／720p／1080p）、`duration`（整數秒）、`frames`（與 duration 二選一）、
`seed`、`camera_fixed`、`watermark`、`generate_audio`、`return_last_frame`、`draft`、
`service_tier`、`execution_expires_after`、`callback_url`。

### 1.7 查詢回應（VERIFIED，1521309）

- `status`：`queued`／`running`／`succeeded`／`failed`／`expired`
- `content.video_url`：影片 URL，**24 小時有效**；Seedance 2.5 下載上限 100 次。
- `content.last_frame_url`：尾幀圖 URL（24 小時），僅當 `return_last_frame:true`。
- `content.file_url`、`error.code`、`error.message`、`duration`、`frames`、
  `framespersecond`、`ratio`、`resolution`、`seed`、`generate_audio`、
  `output_format`（2.5）、`usage.completion_tokens`、`usage.total_tokens`。

### 1.8 價格（PARTIAL）

官方以 token 計費（`usage.completion_tokens`），並有 TPD 限流。近期官方刊例折扣錨點：
Seedance 2.5 1080p 約 2.7 元/秒、2.0 mini 720p 約 0.2 元/秒、2.0 fast 720p 約 0.6 元/秒。
**精確每模型／解析度刊例價未完整驗證 → 標 UNVERIFIED。**

---

## 二、Kling（快手可靈）

### 2.1 兩代 API（PARTIAL）

- **Legacy API**（`/v1/videos/*`）：JWT 鑑權（AccessKey + SecretKey），`model_name`
  欄位，成功拼字為 `succeed`。圖片上限 10MB。官方表示暫不淘汰。
- **API 2.0**（2026-06-17）：Bearer API Key，模型 ID 在 URL path，國際站
  `api-singapore.klingai.com`，成功拼字 `succeeded`，圖片上限 50MB。官方文件為
  JS app，無法以純 HTTP 取得 → **多數欄位 UNVERIFIED**。

本專案 adapter 實作 **Legacy API**（最多來源一致、可驗證）。

### 2.2 端點（Legacy，VERIFIED via 官方上游鏡像）

- Base：`https://api-singapore.klingai.com`（國際）或 `https://api-beijing.klingai.com`
- 文生視頻：`POST /v1/videos/text2video`
- 圖生視頻：`POST /v1/videos/image2video`
- 多圖生視頻：`POST /v1/videos/multi-image2video`
- 查詢：`GET /v1/videos/{task_id}`
- 列表：`GET /v1/videos`
- 鑑權：`Authorization: Bearer <JWT>`（`KLING_ACCESS_KEY` + `KLING_SECRET_KEY`）

### 2.3 模型（model_name，PARTIAL）

`kling-v1`、`kling-v1-5`、`kling-v1-6`、`kling-v2`、`kling-v2-1`、
`kling-v2-1-master`、`kling-v2-master`、`kling-v2-5`、`kling-v2-5-turbo`、
`kling-v2-6`、`kling-v3`。

- 圖生視頻（image2video）：上述全數支援（`kling-v2-1`／`kling-v2-1-master` 僅 I2V）。
- 文生視頻（text2video）：除 `kling-v2-1`／`kling-v2-1-master` 外均支援。

### 2.4 參數（Legacy，PARTIAL）

- image2video：`model_name`、`image`（首幀 URL/Base64）、`image_tail`（尾幀）、
  `prompt`、`negative_prompt`、`duration`、`mode`（std/pro/4k）、`aspect_ratio`、
  `sound`（on/off）、`cfg_scale`（0~1）、`camera_control`、`callback_url`、
  `external_task_id`。
- text2video：`model_name`、`prompt`、`negative_prompt`、`mode`、`aspect_ratio`、
  `sound`、`cfg_scale`、`callback_url`、`external_task_id`。

### 2.5 回應（Legacy，PARTIAL）

- 建立：`{code:0, message, request_id, data:{task_id, task_status:"submitted", ...}}`
- 查詢：`{code:0, data:{task_id, task_status: submitted|processing|succeed|failed,
  task_result:{videos:[{id,url,duration}], images:[]}, task_status_msg, ...}}`
- 成功拼字 `succeed`；失敗 `failed` + `task_status_msg`。

### 2.6 限制與時效（PARTIAL）

- 429 併發超限 → `code 1303`；審核拒回 1300/1301（第三方轉述，UNVERIFIED）。
- 產物 URL 30 天清除、需轉存（第三方 riffkit 轉述官方，UNVERIFIED）。
- 時長：2.6/o1 最高 10s；2.5-turbo 僅 5/10s；3.0 家族 3-15s（第三方，UNVERIFIED）。

### 2.7 未實作（UNVERIFIED，不得硬送）

- `multi_shot`（多鏡頭語法）：僅 API 2.0 描述，Legacy 未見 → UNVERIFIED，不實作。
- Element／Character 參考：Legacy 有 `multi-image2video`，但 element 引用語法
  屬新 API → UNVERIFIED，不實作。
- 原生音訊（`sound`）的逐模型支援清單：僅 `kling-v2-6`／`kling-v3` 有交叉佐證
  → adapter 僅對這兩者轉送 `sound:"on"`，其餘 drop。
- 價格：以 Units 計（$0.14/Unit，第三方 riffkit），**精確逐模型價格 UNVERIFIED**。

---

## 三、實作決策摘要

1. Seedance adapter：官方文件完全驗證，直接實作。
2. Kling adapter：實作 Legacy `/v1/videos/*`（JWT），欄位以官方上游鏡像為準；
   API 2.0、multi_shot、element 參考列為 UNVERIFIED 不實作。
3. 未支援參數一律在 adapter 內 **drop**（過濾），不回傳錯誤、不硬送 API。
4. 首尾幀不支援時降級為首幀／prompt continuity。
5. 兩者皆無真實金鑰（環境僅 DEEPSEEK/OPENROUTER/NOTION），真實 API 驗證列為缺口。
