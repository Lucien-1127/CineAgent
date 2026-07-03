# ⚠️ Agnes Video API 實測陷阱（重要！）

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
