# ⚠️ Video API 實測陷阱

> ⚠️ **Agnes 陷阱段落為 v3 遷移歷史**，僅供參考。Agnes／AGNETS 已全面棄用。
> Seedance 與 Kling 的現行驗證見 `references/video-provider-verification.md`，
> 使用方式見 `docs/video-production.md`。以下 Agnes 內容不再是實作依據。

## Seedance／Kling 快速提醒

- Seedance 影片 URL 有效期 24h（2.5 另有 100 次下載上限），務必及時轉存。
- Kling 成功狀態字串是 `succeed`（不是 `succeeded`）；Seedance 是 `succeeded`。
- 首尾幀：Seedance 用 `content[].role = "first_frame"/"last_frame"`；Kling 用 `image`/`image_tail`。
- 不支援的能力欄位（如 1.0 系列參考圖片、legacy Kling 的 multi_shot）不得硬送，adapter 已過濾。

---

## Agnes 陷阱（歷史）

## 端點正確值

| 項目 | 正確值 | 錯誤範例 |
|------|--------|---------|
| 提交 endpoint | `POST /v1/videos` | ❌ `/v1/video/generations`（舊版） |
| Polling endpoint | `GET https://apihub.agnes-ai.com/agnesapi` | ❌ `/agnesapi`（走 base_url 會變 /v1/agnesapi） |
| Polling 參數 | `?video_id=<ID>&model_name=agnes-video-v2.0` | — |
| 回傳 ID | `video_id`（長字串，用於 polling） | ❌ `task_id`（僅供參考） |
| 結果欄位 | `remixed_from_video_id`（完成時出現） | ❌ `url` 或 `output.url`（不存在） |
| 提交回傳 | `{"id","video_id","task_id","status":"queued","seconds":"5.0"}` | — |

## 幀數規則

- 必須符合 `8n+1` 公式
- 1080p 最大 169 幀（~7s）
- 720p 最大 409 幀（~17s）

## 多圖轉場

```json
{
  "extra_body": {
    "image": ["url1", "url2", "url3"]
  }
}
```

## 額度

| 項目 | 限制 |
|------|------|
| 每日影片額度 | 500 秒 |
| 安全水位線 | 480 秒（留 20s 緩衝） |
