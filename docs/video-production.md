# 🎬 影片製作指南

## 模型架構

**一律使用 Agnes Video 2.0 架構**（非舊版 1.0）。

- 模型名稱: `agnes-video-v2.0`
- 端點: `POST /v1/videos`
- Polling: `GET https://apihub.agnes-ai.com/agnesapi`

## 長度控制

使用 `num_frames` + `frame_rate` 公式：

```
seconds = num_frames / frame_rate
```

**Duration Presets：**

| 秒數 | num_frames | frame_rate | 最高解析度 |
|------|-----------|------------|-----------|
| 5s | 121 | 24 | 1080p |
| 7s | 169 | 24 | 1080p (max) |
| 10s | 241 | 24 | 720p |
| 12s | 289 | 24 | 720p |
| 15s | 361 | 24 | 720p |
| 17s | 409 | 24 | 720p (max) |

**重要規則：**
- 幀數必須符合 `8n+1` 公式
- 1080p 最大 169 幀（~7s）
- 720p 最大 409 幀（~17s）

## I2V 提示詞原則

**核心原則：圖片鎖定視覺品質，影片提示詞只描述動態。**

| 角色 | 負責 | 不負責 |
|------|------|--------|
| **圖片** | 構圖、主體、光影、風格、材質 | 動態描述 |
| **影片提示詞** | 什麼在動、怎麼動、鏡頭運動 | 描述圖片已有的東西 |

### 一致性控制

角色和背景已在圖片中鎖定。影片提示詞只需：
- 用代名詞或輕度描述指涉主體（`the woman`, `the figure`）
- **不要**重新描述角色的長相、服裝細節（那是圖片的事）
- 如果場景中有多個角色，用位置或動作區分（`the figure on the left`）

### 負面提示詞 (Negative Prompts)

| 類別 | Negative Prompt |
|------|----------------|
| 品質 | `blurry, low quality, jpeg artifacts, flickering` |
| 不一致 | `inconsistent character, morphing, disfigured face` |
| 過度動態 | `excessive motion, shaky, hyper` |
| 風格偏移 | `cartoon, 3d render, anime, cgi, oversaturated` |

### 影片生成 Negative Prompt 組合範本

```
blurry, low quality, jpeg artifacts, flickering,
inconsistent character, morphing, disfigured face,
excessive motion, shaky cam, hyper,
cartoon, 3d render, anime, cgi, oversaturated
```

### Prompt 結構

```
The camera [motion] as the subject [action].
[environmental motion].
[timing/sequence].
```

### Motion Components

| 類別 | 範例 |
|------|------|
| 主體動作 | slowly turns head, blinks, breathes deeply, raises weapon |
| 環境動態 | clouds drift, leaves rustle, water ripples, dust particles float |
| 鏡頭運動 | slow push-in, dolly right, crane up, handheld shake |
| 風格/節奏 | smooth cinematic motion, slow motion, continuous seamless shot |

### Sequential Prompting

```
[00:01] Subject slowly turns to face camera.
[00:03] Clouds begin swirling around.
[00:04] Camera slowly pushes in.
```

## Frame Chaining（串接段落）

前一鏡頭的最後一幀 → 下一鏡頭的起始圖片：

```
Clip 1 (5s): 輸入圖片A → 產出影片A
                    ↓
             取影片A的最後一幀作為新圖片
                    ↓
Clip 2 (5s): 新圖片B → 產出影片B → 兩段無縫銜接
```

## API 注意事項（來自實測）

| 項目 | 正確值 |
|------|--------|
| 提交 endpoint | `POST /v1/videos` |
| Polling endpoint | `GET https://apihub.agnes-ai.com/agnesapi` |
| Polling 參數 | `?video_id=<ID>&model_name=agnes-video-v2.0` |
| 結果欄位 | `remixed_from_video_id`（完成時出現） |

參見 `references/video-api-pitfalls.md`。
